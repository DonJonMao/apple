"""Run a frozen public/synthetic retrieval benchmark on a local knowledge snapshot.

A-D remove semantic applicability only, retaining source/rights/lifecycle checks;
E uses the production pipeline. A_filtered is an additional fair lexical
comparison with the same applicability policy as E. The bypass exists only in
this offline evaluator and must never run in an application server process.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import time
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch

from healthzip.knowledge import KnowledgeWorkbench, domains, metric_retrieval, query_forms
from healthzip.knowledge.model_services import load_services
from healthzip.knowledge.retrieval_evaluation import aggregate, evaluate_saved_rankings, score_case
from healthzip.knowledge.store import digest, dumps, now
from healthzip.science import evaluate
from healthzip.science import observations as observation_engine

VARIANTS = {"A": ("lexical", False), "B": ("dense", False), "C": ("hybrid", False),
            "D": ("hybrid_rerank", False), "E": ("hybrid_rerank", True),
            "A_filtered": ("lexical", True)}


def public_run_identity(identity):
    """Keep service locations local without changing model/cache identity semantics."""
    def project(value):
        if isinstance(value, dict):
            return {key: project(item) for key, item in value.items()
                    if key.lower() not in {'endpoint', 'tokenizer_endpoint', 'api_key',
                                           'api_token', 'authorization', 'headers'}}
        if isinstance(value, (list, tuple)):
            return [project(item) for item in value]
        return value

    public = project(identity)
    public['private_run_identity_sha256'] = digest(dumps(identity).encode())
    for original, model in zip(identity['models'], public['models']):
        model['service_identity_sha256'] = digest(dumps(original).encode())
    return public


def validate_candidate_scope(freeze, candidate_scope):
    if not isinstance(candidate_scope, str) or candidate_scope not in metric_retrieval.CANDIDATE_SCOPES:
        raise ValueError('unknown_metric_candidate_scope')
    scopes = freeze.get('candidate_scopes', ['all'])
    if (not isinstance(scopes, list) or not scopes or any(not isinstance(s, str) for s in scopes)
            or len(set(scopes)) != len(scopes) or not set(scopes) <= metric_retrieval.CANDIDATE_SCOPES):
        raise ValueError('invalid_frozen_candidate_scopes')
    if candidate_scope not in scopes:
        raise ValueError('gold_freeze_must_pin_selected_candidate_scope')
    if ('reviewed_metric' in scopes
            and freeze.get('candidate_scope_version') != metric_retrieval.CANDIDATE_SCOPE_VERSION):
        raise ValueError('gold_freeze_must_pin_candidate_scope_version')


def implementation_identity():
    package = Path(domains.__file__).parent
    paths = [*package.glob("*.py"), *package.glob("data/*.json")]
    result = {str(path.relative_to(package)): digest(path.read_bytes()) for path in sorted(paths)}
    science = Path(observation_engine.__file__).parent
    result.update({'science/' + str(path.relative_to(science)): digest(path.read_bytes())
                   for path in sorted([*science.glob('*.py'), *science.glob('*.json')])})
    return result


def run(root, gold_path, services_config, release_id, private_output, public_output, *,
        evaluation_purpose="development_replay", query_form=None, candidate_scope='all', _resume_completed=False):
    raw = Path(gold_path).read_bytes()
    gold = json.loads(raw)
    if (gold.get("schema") != "metric-retrieval-gold-1.5.0" or not gold.get("created_at")
            or not gold.get("annotator") or not gold.get("synthetic_context_only")
            or not all(c.get("synthetic_context") is True for c in gold["cases"])):
        raise ValueError("identified_frozen_public_synthetic_gold_required")
    freeze_path = Path(gold_path).with_name(Path(gold_path).stem + "-freeze.json")
    freeze = json.loads(freeze_path.read_text())
    if (freeze["gold_sha256"] != digest(raw) or freeze["production_profiles_sha256"] !=
            digest(dumps(domains.configuration()).encode())):
        raise ValueError("frozen_gold_or_retrieval_profile_changed")
    validate_candidate_scope(freeze, candidate_scope)
    if query_form is not None and freeze.get('query_forms_sha256') != query_forms.identity():
        raise ValueError('gold_freeze_must_pin_selected_query_forms')
    if (any(c['metric_id'] in observation_engine.definitions() for c in gold['cases'])
            and freeze.get('observation_profiles_sha256') != digest(dumps(domains.observation_configuration()).encode())):
        raise ValueError('gold_freeze_must_pin_observation_profiles')
    fixed_queries = {case['case_id']: query_forms.select(case['metric_id'],
        case.get('analysis_task', 'explain_metric'), domains.configuration(include_observations=True),
        form=query_form)[1] for case in gold['cases']}
    private = Path(private_output)
    private.mkdir(parents=True, exist_ok=True)
    w = KnowledgeWorkbench(root)
    try:
        release = metric_retrieval._release(w, release_id)[2]
        if (candidate_scope != 'all'
                and release.get('candidate_scope_version') != metric_retrieval.CANDIDATE_SCOPE_VERSION):
            raise ValueError('scoped_evaluation_requires_pinned_index_release')
        services = load_services(w.root, config_path=services_config)
        identity = {"gold_sha256": digest(raw), "release_id": release_id,
                    "release": release if release_id else {'membership': 'current'},
                    "gold_freeze_sha256": digest(freeze_path.read_bytes()),
                    "candidate_scope": candidate_scope,
                    "candidate_scope_version": metric_retrieval.CANDIDATE_SCOPE_VERSION if candidate_scope != 'all' else None,
                    "profile_sha256": digest(dumps(domains.configuration()).encode()),
                    "runner_sha256": digest(Path(__file__).read_bytes()),
                    "implementation_sha256": implementation_identity(),
                    "evaluation_purpose": evaluation_purpose,
                    "query_form": query_form or 'legacy_combined', "fixed_queries": fixed_queries,
                    "annotation_provenance": freeze.get('annotation_provenance'),
                    "models": [provider.config.identity for provider in services],
                    "variants": VARIANTS}
        public_identity = public_run_identity(identity)
        identity_path = private / "run-identity.json"
        if identity_path.exists():
            if json.loads(identity_path.read_text()) != json.loads(dumps(identity)):
                raise ValueError("resume_requires_same_frozen_run_identity")
        else:
            with identity_path.open("x") as stream:
                stream.write(dumps(identity) + "\n")
        completed = private / 'completed-public-sha256.json'
        if _resume_completed and completed.exists():
            for name, expected in json.loads(completed.read_text()).items():
                if digest((Path(public_output) / name).read_bytes()) != expected:
                    raise ValueError('completed_public_report_changed')
            report = json.loads((Path(public_output) / 'evaluation.json').read_text())
            if report['retrieval_config']['identity'] != json.loads(dumps(public_identity)):
                raise ValueError('completed_report_identity_changed')
            return report
        experiments, filtered_rows, timings = {}, [], []
        for variant, (mode, applicability) in VARIANTS.items():
            outputs = {}
            for case in gold["cases"]:
                if implementation_identity() != identity['implementation_sha256']:
                    raise ValueError('implementation_changed_during_frozen_run')
                saved = private / (variant + "-" + case["case_id"] + ".json")
                if saved.exists():
                    record = json.loads(saved.read_text())
                    result = record["result"]
                else:
                    engine = observation_engine.evaluate if case['metric_id'] in observation_engine.definitions() else evaluate
                    metric = engine(case["metric_id"], [], cutoff_time="2026-11-17T00:00:00+00:00",
                        window_start="2026-11-01T00:00:00+00:00", window_end="2026-11-17T00:00:00+00:00")
                    # Intentional experiment ablation, isolated to this offline process.
                    context = contextlib.nullcontext() if applicability else patch(
                        "healthzip.knowledge.metric_retrieval.context_match", return_value=(True, "evaluation_ablation"))
                    started = time.monotonic()
                    with context:
                        result = w.retrieve_for_metric(case["metric_id"], case.get('analysis_task', 'explain_metric'), metric,
                            case["context"], release_id, mode=mode, k=6, services=services, query_form=query_form,
                            candidate_scope=candidate_scope)
                    record = {"created_at": now(), "variant": variant, "case_id": case["case_id"],
                              "elapsed_seconds": round(time.monotonic() - started, 6), "result": result}
                    with saved.open("x") as stream:
                        stream.write(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
                    print(variant, case["case_id"], result["status"], record["elapsed_seconds"], flush=True)
                outputs[case["case_id"]] = result
                timings.append({"variant": variant, "case_id": case["case_id"],
                                "elapsed_seconds": record["elapsed_seconds"]})
                if variant == "A_filtered":
                    filtered_rows.append(score_case(case, result))
            if variant != "A_filtered":
                experiments[variant] = outputs
        config = {"schema": metric_retrieval.RETRIEVAL_VERSION, "k": 6, "rrf_constant": 60,
            "candidate_budget": 20, "reranker_input_utf8_bytes": 24000,
            "ablation": "A-D semantic applicability disabled; source rights and lifecycle always enforced",
            "A_filtered": "additional lexical reference with the identical applicability policy as E",
            "candidate_scope": candidate_scope,
            "candidate_scope_comparison_limit": "Reviewed-metric scope uses previously reviewed bindings; it does not measure discovery in the full corpus.",
            "identity": public_identity, "gold_label_scope": gold.get("annotation_scope")}
        report = evaluate_saved_rankings(gold_path, experiments, public_output,
            model_identities=public_identity["models"], retrieval_config=config)
        extra = {"created_at": now(), "gold_sha256": digest(raw), "timings": timings,
                 "filtered_lexical_reference": {"overall": aggregate(filtered_rows), "cases": filtered_rows},
                 "latency_scope": "A,B,C,D,E,A_filtered sequential; query embeddings warm after B; one measurement per cell, not P95 or a latency ablation"}
        splits = {case["case_id"]: case.get("evaluation_split", "unspecified") for case in gold["cases"]}
        extra["by_annotation_split"] = {}
        for variant, records in [(key, value["cases"]) for key, value in report["experiments"].items()] + [("A_filtered", filtered_rows)]:
            groups = defaultdict(list)
            for row in records:
                groups[splits[row["case_id"]]].append(row)
            extra["by_annotation_split"][variant] = {split: aggregate(rows) for split, rows in groups.items()}
        with (Path(public_output) / "filtered-lexical-and-latency.json").open("x") as stream:
            stream.write(json.dumps(extra, ensure_ascii=False, indent=2) + "\n")
        with completed.open('x') as stream:
            stream.write(dumps({name: digest((Path(public_output) / name).read_bytes()) for name in
                ('evaluation.json', 'filtered-lexical-and-latency.json')}) + '\n')
        return report
    finally:
        w.close()


def run_query_forms(root, gold_path, services_config, release_id, private_output, public_output, *,
                    forms=('zh', 'en', 'zh_synonym'), evaluation_purpose='development_replay', candidate_scope='all'):
    """Paired forms share Gold and budgets; they never add independent knowledge cases."""
    registry = query_forms.configuration()
    if not forms or len(set(forms)) != len(forms) or not set(forms) <= set(registry['forms']):
        raise ValueError('distinct_known_query_forms_required')
    private, public = Path(private_output), Path(public_output)
    # Fail before model calls when an immutable matrix already exists.
    if (public / 'query-forms-evaluation.json').exists():
        raise FileExistsError('immutable_query_forms_evaluation')
    reports, filtered = {}, {}
    for form in forms:
        reports[form] = run(root, gold_path, services_config, release_id, private / form, public / form,
            evaluation_purpose=evaluation_purpose, query_form=form, candidate_scope=candidate_scope, _resume_completed=True)
        extra = json.loads((public / form / 'filtered-lexical-and-latency.json').read_text())
        filtered[form] = extra['filtered_lexical_reference']
    identities = [report['retrieval_config']['identity'] for report in reports.values()]
    for key in ('gold_sha256', 'gold_freeze_sha256', 'release_id', 'release', 'candidate_scope',
                'candidate_scope_version', 'implementation_sha256', 'runner_sha256', 'models'):
        if any(item[key] != identities[0][key] for item in identities):
            raise ValueError('paired_forms_require_identical_frozen_inputs')
    summary = {'schema': 'paired-query-forms-evaluation-1.5.0', 'created_at': now(),
        'gold_sha256': identities[0]['gold_sha256'], 'query_forms_sha256': query_forms.identity(),
        'candidate_scope': candidate_scope, 'candidate_scope_version': identities[0]['candidate_scope_version'],
        'evaluation_purpose': evaluation_purpose, 'forms': {f: registry['forms'][f] for f in forms},
        'unique_knowledge_case_count': len(next(iter(reports.values()))['experiments']['A']['cases']),
        'paired_form_count': len(forms),
        'denominator_scope': 'Scores count query instances. Multiple forms of one case are correlated and add no independent knowledge cases. No population confidence intervals.',
        'experiments': {}}
    summary['query_instance_count_per_experiment'] = summary['unique_knowledge_case_count'] * len(forms)
    for variant in VARIANTS:
        by_form, by_language, by_form_domain = {}, defaultdict(list), {}
        for form, report in reports.items():
            scored = filtered[form] if variant == 'A_filtered' else report['experiments'][variant]
            by_form[form] = scored['overall']
            rows = scored['cases']
            by_language[registry['forms'][form]['language']].extend(rows)
            groups = defaultdict(list)
            for row in rows:
                for domain in row['domains']:
                    groups[domain].append(row)
                if len(row['domains']) > 1:
                    groups['cross_domain'].append(row)
            by_form_domain[form] = {key: aggregate(value) for key, value in sorted(groups.items())}
        summary['experiments'][variant] = {'by_form': by_form, 'by_form_domain': by_form_domain,
            'by_language': {key: aggregate(value) for key, value in sorted(by_language.items())}}
    with (public / 'query-forms-evaluation.json').open('x') as stream:
        stream.write(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "gold", "services-config", "release-id", "private-output", "public-output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--evaluation-purpose", choices=["development_replay", "independent_test"],
                        default="development_replay")
    parser.add_argument('--query-forms', nargs='+', choices=sorted(query_forms.configuration()['forms']))
    parser.add_argument('--candidate-scope', choices=sorted(metric_retrieval.CANDIDATE_SCOPES), default='all',
                        help='Default all preserves historical runs; reviewed_metric requires a pinned Gold policy and index release.')
    args = parser.parse_args()
    runner = run_query_forms if args.query_forms else run
    options = {'forms': args.query_forms} if args.query_forms else {}
    result = runner(args.root, args.gold, args.services_config, args.release_id,
                    args.private_output, args.public_output,
                    evaluation_purpose=args.evaluation_purpose, candidate_scope=args.candidate_scope, **options)
    print(json.dumps({"gold_sha256": result["gold_sha256"], "experiments": list(result["experiments"])}))
