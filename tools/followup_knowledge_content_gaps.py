"""Append bounded topic uses of retained originals, without changing old reviews.

Use a public-library backup first. No health database or network is opened.
Existing conditional RIR claims are deliberately not republished as public uses.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from healthzip.knowledge import KnowledgeWorkbench, domains, vector_index
from healthzip.knowledge.core import _claim, _spans
from healthzip.knowledge.revisions import knowledge_authority_clock, prepare_retrieval_revisions
from healthzip.knowledge.topics import ANSWER_NEEDS, question_sources

VERSION = 'followup-2026-11-27.2'
REVIEW = {'reviewer': 'Codex retained-original passage review, 2026-11-27',
    'reviewer_kind': 'ai_assisted', 'reviewed_at': '2026-11-27',
    'content_checked': True, 'application_checked': True, 'independent_expert_validation': False,
    'rationale': 'Read exact retained methods, results and limitations. Only the stated measurement scope is applied; no individual accuracy, prescription or new permission.'}

READINGS = {
    'hrv_identity': {'source': 'MSTR-H1',
        'version': 'MSTR-H1:fulltext:45bfd2404589e7b5f6f7:reviewed-author-html-2-master-hrv-identity',
        'paragraphs': [0, 1], 'domain': 'wearable',
        'population': 'Committee psychophysiological measurement guidance, author accepted manuscript',
        'protocol': 'SDNN and RMSSD definitions; recording epoch length in sections 5.2.3 and 5.3.1',
        'limits': 'No transfer of ECG study duration, accuracy or population thresholds to a watch.'},
    'hr_context': {'source': 'MSTR-H1',
        'version': 'MSTR-H1:fulltext:45bfd2404589e7b5f6f7:reviewed-author-html-2-master-hr-context',
        'paragraphs': [0, 1], 'domain': 'wearable',
        'population': 'Ambulatory psychophysiological methods guidance, author accepted manuscript',
        'protocol': 'Activity/posture strata and co-recorded state, sections 8.2 and 8.2.1',
        'limits': 'Only actual recorded context; no inferred fatigue, illness or personal recovery threshold.'},
    'davis': {'source': 'HC-DAVIS-WILSON-MISSING-2025', 'hash': 'cb1b7bee85974ab202df',
        'paragraphs': [13, 14, 15, 18, 43], 'domain': 'wearable',
        'population': 'Adult community volunteers; 16 missingness analyses and 5 ECG comparisons',
        'protocol': 'Garmin Fenix 6/6s IBI, five-minute windows, semisimulated real missingness patterns; Polar H10 comparison',
        'limits': 'Within-window IBI loss does not validate missing-day rules or current Apple SDNN accuracy.'},
    'repetitions': {'source': 'S6', 'hash': 'e35899ff7de80b190b8d',
        'paragraphs': [27, 28], 'domain': 'strength',
        'population': 'Approximately 7000 participants across included resistance exercise studies',
        'protocol': 'Meta-regression of repetitions to failure against percentage of measured 1RM; exercise moderators',
        'limits': 'Group means and between-person variation do not validate Epley, RIR-corrected e1RM or individual cross-exercise conversion.'},
    'one_rm': {'source': 'S7', 'hash': '729133bc561790f5e421',
        'paragraphs': [45], 'domain': 'strength',
        'population': 'Participants and protocols of the direct 1RM test-retest systematic review',
        'protocol': 'Repeated maximal dynamic strength tests, not estimates from ordinary submaximal sets',
        'limits': 'Review reliability cannot become personal SEM/MDC or validation of estimated 1RM.'},
    'watch': {'source': 'E7', 'hash': '06624723060915c0599f',
        'paragraphs': [18, 21, 22, 25, 34, 37, 39, 40, 43], 'domain': 'wearable',
        'population': 'Heterogeneous Apple Watch validation cohorts; disproportionate active and male participants; limited free-living and older/patient evidence',
        'protocol': 'Metric-specific comparisons with criterion measurements; studied models and protocols differ',
        'limits': 'No personal error bound, longitudinal change threshold or transfer to every model; ECG-app results do not validate irregular-rhythm notifications.'},
}

EXISTING_USES = [
    {'id': 'MASTER-HRV-IDENTITY', 'version': '1', 'reading': 'hrv_identity', 'spans': [0, 1],
     'need': 'hrv_metric_and_recording_identity', 'relation': 'limits'},
    {'id': 'MASTER-HR-CONTEXT', 'version': '1', 'reading': 'hr_context', 'spans': [0, 1],
     'need': 'training_state_measurement_context', 'relation': 'limits'},
    {'id': 'HC-DAVIS-IBI-GAPS', 'version': '1.0.0', 'reading': 'davis', 'spans': [14, 18, 43],
     'need': 'hrv_missing_observation_unit'},
    {'id': 'V15-CLAIM-REPETITIONS-POPULATION-VARIATION', 'version': '1.5.0',
     'reading': 'repetitions', 'spans': [27, 28], 'need': 'repetition_load_population_transfer'},
    {'id': 'V15-CLAIM-MEASURED-ONE-RM-RELIABILITY-SCOPE', 'version': '1.5.0',
     'reading': 'one_rm', 'spans': [45], 'need': 'measured_estimated_1rm_reliability'},
]
NEW_USES = [
    {'id': 'FOLLOWUP-WATCH-OXYGEN-AGREEMENT-SCOPE', 'reading': 'watch', 'spans': [21, 37, 40],
     'need': 'watch_oxygen_agreement_scope',
     'statement': '这份综述的血氧研究涉及Apple Watch Series 6至8。平均偏差较小与单次读数一致性不是一回事，较低血氧范围中的误差表现也可能不同。比较记录时保留型号和测量条件，不能把群体平均值当作本人每次读数准确的证明。',
     'limits': ['研究人群和协议不同，且部分研究偏倚较高；不将结果推广到全部型号、后续算法、其他厂商或未知年龄人群。',
                '不从合并一致性界限推算个人误差区间、诊断线或前后变化阈值；本条不证明某次读数正常或异常。',
                '不能精确区分硬件与软件更新的影响；保留已有数值，并核对实际测量背景和原设备记录。']},
    {'id': 'FOLLOWUP-WATCH-STEPS-VALIDATION-SCOPE', 'reading': 'watch', 'spans': [25, 40, 43],
     'need': 'watch_steps_validation_scope',
     'statement': '这份综述的步数验证只有三项研究，涉及Apple Watch初代和Series 1；这些研究没有覆盖久坐或坐着活动手臂的场景。设备记录的步数仍可按实际日期描述，但不能把这些早期验证直接当成当前型号、所有活动场景或个人步数变化的精度证明。',
     'limits': ['这是该综述纳入研究的范围，不是断言世界上不存在其他或后续研究。',
                '不把步数等同于步行能力，不给统一校正系数、最小真实变化或个人达标线。',
                '换设备或活动场景改变时保留来源和日期，不把群体相关性当作个人一致性。']},
    {'id': 'FOLLOWUP-WATCH-NIGHT-VITAL-SCOPE', 'reading': 'watch', 'spans': [34, 43],
     'need': 'watch_night_vital_validation_scope',
     'statement': '这份Apple Watch综述仍将呼吸率和腕温列为需要验证的指标，并指出纵向趋势还需要精度与可靠性研究。其他指标已有的验证不能直接证明这两项的个人变化准确；现有数值可按其来源和实际观察时段描述。',
     'limits': ['这是该综述的证据范围，不是已检索全部后续资料，也不是证明当前设备不准确。',
                '没有从本文取得当前呼吸率或腕温的个人误差、变化阈值或病因解释。',
                '本条仅说明综述中这两项验证的缺口，不为其他温度、呼吸事件或设备通知字段提供验证。']},
]


def version(reading):
    if reading.get('version'):
        return reading['version']
    return f"{reading['source']}:fulltext:{reading['hash']}:jats-owned-text-1.4.1"


def references(spec):
    reading = READINGS[spec['reading']]
    vid = version(reading)
    return [{'source_id': reading['source'], 'source_version_id': vid,
             'span_ids': [f'{vid}:s{n:05d}' for n in spec['spans']]}]


def preflight(w):
    """Check all exact originals and old claims before adding any authority."""
    for spec in [*EXISTING_USES, *NEW_USES]:
        refs = references(spec)
        _spans(w, refs)
        if spec in EXISTING_USES:
            claim, _, _ = _claim(w, {'claim_id': spec['id'], 'version': spec['version']})
            if claim.get('conditions'):
                raise ValueError('conditional_claim_requires_computed_context')
            if claim['evidence_links'] != refs:
                raise ValueError('existing_claim_exact_evidence_changed:' + spec['id'])


def apply(w):
    preflight(w)
    results = []
    for spec in [*EXISTING_USES, *NEW_USES]:
        reading, refs = READINGS[spec['reading']], references(spec)
        spans, vid = refs[0]['span_ids'], refs[0]['source_version_id']
        unit = w.lib.sources.execute('SELECT domains_json,assignment_status FROM retrieval_unit WHERE span_id=?',
                                    (spans[0],)).fetchone()
        vector_index.register_spans(w, vid, json.loads(unit[0]) if unit else [reading['domain']],
                                    assignment_status=unit[1] if unit else 'provisional')
        for sid in spans:
            if not w.lib.sources.execute('SELECT 1 FROM retrieval_unit_domain_review WHERE span_id=?', (sid,)).fetchone():
                vector_index.review_unit_domains(w, [sid], [reading['domain']], REVIEW)
        claim_version = spec.get('version', VERSION)
        if spec in NEW_USES:
            w.review_claim({'claim_id': spec['id'], 'version': claim_version,
                'statement': spec['statement'], 'conditions': [], 'limitations': spec['limits'],
                'scope': {'explanation_purpose': 'measurement_context', 'population': reading['population'],
                          'protocol': reading['protocol'], 'use': 'source_specific_measurement_limits'},
                'evidence_links': refs}, REVIEW)
        need = ANSWER_NEEDS[spec['need']]
        binding = {key: need[key] for key in ('question', 'target_claim')}
        binding.update(relation='supports', answer_complete=True, target_coverage_complete=True,
                       rationale='The exact retained passages and claim answer this limited question; no transfer of individual accuracy.')
        edges = [domains.link(w,
            origin={'type': 'claim', 'id': spec['id'], 'version': claim_version}, relation=spec.get('relation', 'applies_to'),
            target={'type': 'metric', 'id': topic, 'version': domains.profile_version(topic)},
            span_ids=spans, applicability={}, actor=REVIEW['reviewer'],
            rationale='Limited public measurement explanation; preserve original claim, conditions, rights and review.',
            evidence_types=need['purposes'], review=REVIEW, answer_bindings=[binding]) for topic in need['topics']]
        results.append({'claim_id': spec['id'], 'version': claim_version,
                        'existing_claim_reused': spec in EXISTING_USES, 'edges': edges})
    prepare_retrieval_revisions(w)
    return results


def audit(w, output, applied):
    output.mkdir(parents=True, exist_ok=True)
    readings = []
    for key, reading in READINGS.items():
        manifest = w.lib.source(reading['source'])['manifest']
        refs = []
        for n in reading['paragraphs']:
            span = w.lib.span(f'{version(reading)}:s{n:05d}', include_metadata=False)
            refs.append({'span_id': span['span_id'], 'text_hash': span['text_hash'],
                'section': span['section_path'], 'locator': json.loads(span['locator_json']),
                'eligible': w.lib.eligible(span, 'fulltext'), 'rights': json.loads(span['rights_json'])})
        readings.append({'id': key, **reading, 'title': manifest['title'], 'url': manifest['canonical_url'],
            'year': manifest.get('year'), 'source_version': version(reading), 'references': refs,
            'whole_article_reread': False, 'independent_expert_review': False})
    before = knowledge_authority_clock(w.lib.root)
    topics = sorted({topic for spec in [*EXISTING_USES, *NEW_USES]
                     for topic in ANSWER_NEEDS[spec['need']]['topics']})
    # Keep derived claims, citations and audit metadata, not licensed source prose.
    answers = [question_sources(w, topic) for topic in topics]
    for name, value in [('passage-readings.json', readings), ('retrieval.json', answers),
                        ('ingestion.json', {'applied': applied, 'only_append': True, 'external_calls': 0,
                         'retrieval_authority_stable': before == knowledge_authority_clock(w.lib.root)})]:
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    from followup_knowledge_install import compare_rows
    if args.root.resolve() == args.baseline.resolve():
        raise ValueError('independent_public_backup_required')
    before = compare_rows(args.baseline, args.root)
    w = KnowledgeWorkbench(args.root)
    try:
        preflight(w)
        applied = apply(w) if args.apply else []
        audit(w, args.output, applied)
    finally:
        w.close()
    after = compare_rows(args.baseline, args.root)
    (args.output / 'preservation.json').write_text(json.dumps({'before': before, 'after': after,
        'installed': args.apply, 'private_health_opened': False, 'existing_rights_changed': False},
        ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
