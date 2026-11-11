"""Validate this delivery's specification links; this does not test the product."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent
def read(name):
    return json.loads((ROOT / name).read_text(encoding='utf-8'))

metrics = read('metrics.json')['metrics']
sources_doc = read('sources.json')
sources = sources_doc['sources']
routes = read('knowledge_routes.json')
cards = read('theory_seed_cards.json')['cards']
exercises = read('exercise_catalog_seed.json')['exercises']
rag = read('rag_eval_cases.json')['cases']
source_ids = {s['source_id'] for s in sources}
metric_ids = {m['metric_id'] for m in metrics}
aliases = sources_doc.get('source_aliases', {})
assert aliases == routes['aliases'], 'Source aliases differ across files'
def resolved(source):
    if source in source_ids:
        return [source]
    assert source in aliases, f'Unknown source: {source}'
    out = aliases[source]
    assert out and all(s in source_ids for s in out), source
    return out

required = read('metric_definition.schema.json')['required']
assert len(metric_ids) == len(metrics)
assert len(source_ids) == len(sources)
assert len({x['core_theory_id'] for x in cards}) == len(cards)
assert len({x['exercise_id'] for x in exercises}) == len(exercises)
assert len({x['case_id'] for x in rag}) == len(rag)
for metric in metrics:
    assert all(k in metric for k in required), metric['metric_id']
    assert metric['tests'], metric['metric_id']
    for source in metric['evidence_refs']:
        resolved(source)
for card in cards:
    assert card['review_status'] == 'draft_pending_fulltext_review'
    assert not card['evidence_span_ids'], 'Draft must not invent source spans'
    assert card['core_theory_id'] == card['theory_id']
    assert set(card['metric_ids']) <= metric_ids
    for source in card['source_ids']:
        resolved(source)
for route in routes['routes']:
    for source in route['source_ids']:
        resolved(source)
for case in rag:
    for source in case['gold_source_ids']:
        resolved(source)
for exercise in exercises:
    for muscle in exercise['muscle_participation_proposals']:
        assert muscle['review_status'] == 'unreviewed'
        assert muscle['quantitative_use_allowed'] is False
for source in sources:
    assert source['fetch_status'] == 'not_fetched'
    assert source.get('corpus_receipt', {}).get('sha256') is None
acceptance = read('metric_acceptance_catalog.json')
assert acceptance['case_count'] == len(acceptance['cases'])
assert all(x['metric_id'] in metric_ids for x in acceptance['cases'])
summary = {
    'validation_scope': 'specification_structure_and_references_only',
    'result': 'passed',
    'metrics': len(metrics),
    'sources': len(sources),
    'theory_drafts': len(cards),
    'exercise_seeds': len(exercises),
    'rag_development_cases': len(rag),
    'metric_acceptance_statements': len(acceptance['cases']),
    'product_tests_executed': False,
    'scientific_validation_performed': False,
}
print(json.dumps(summary, ensure_ascii=False, indent=2))
