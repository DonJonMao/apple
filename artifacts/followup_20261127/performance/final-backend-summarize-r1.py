import hashlib,json,sys
from pathlib import Path
base=Path(sys.argv[1])
output=Path(sys.argv[2])
assert not output.exists(), 'preserve existing summary'
result={'scope':'backend service calls; no browser or physical-device timing','timing':'perf_counter; no cProfile; OS cache retained','warm_samples':30,'p95_method':'nearest-rank','tiers':[]}
for tier in ('personal','100k','1m'):
    p=base/f'final-backend-{tier}-r1'
    receipt=json.loads((p/'receipt.json').read_text())
    g,r,a=[json.loads((p/f'{phase}.json').read_text()) for phase in ('generation','read','audit')]
    manifests=[json.loads((p/name).read_text()) for name in ('source-manifest.json','generation-source.json','read-source.json','audit-source.json')]
    assert all(m==manifests[0] for m in manifests)
    assert receipt['complete'] and receipt['raw_source_tables_unchanged'] and receipt['source_unchanged_across_all_phases']
    assert receipt['shared_knowledge_authority_unchanged']
    assert len(g['samples'])==31 and len(set(g['new_explicit_report_ids']))==31
    assert g['warm']['n']==30 and r['warm']['n']==30
    assert a['offline_reconstruction_exact']
    assert all(not s['full_analysis_returned'] and not s['full_analysis_read'] for s in r['samples'][:31])
    row={'tier':tier,'artifact_directory':str(p),'fixture':receipt['fixture'],'original_database_bytes':receipt['original_database_bytes'],
         'cold_generation_seconds':g['samples'][0]['seconds'],'warm_generation':g['warm'],'generation_budgets':g['budgets'],
         'cold_read_seconds':r['samples'][0]['seconds'],'warm_read':r['warm'],'read_budgets':r['budgets'],
         'markdown_utf8_bytes':g['samples'][0]['markdown_utf8_bytes'],'reading_payload_utf8_bytes':r['reading_payload_utf8_bytes'],
         'report_manifest_utf8_bytes':g['samples'][0]['manifest_utf8_bytes'],'unique_frozen_content_bytes':a['referenced_unique_bytes'],
         'audit_export_seconds':a['samples'][0]['seconds'],'audit_export_bytes':a['samples'][0]['export_bytes'],
         'offline_reconstruction_seconds':a['samples'][1]['seconds'],'offline_reconstruction_exact':True,
         'integrity':a['integrity'],'raw_source_tables_unchanged':True,'all_31_report_ids_unique':True,
         'ordinary_read_never_loaded_full_analysis_or_workflow':True,'shared_knowledge_authority_unchanged':True,
         'resources':receipt['phases'],'source_manifest_sha256':hashlib.sha256(json.dumps(manifests[0],sort_keys=True,separators=(',',':')).encode()).hexdigest(),
         'concurrent_load':receipt['concurrent_load'],'generation_initial_host_load':g['initial_host_load'],'generation_final_host_load':g['final_host_load']}
    result['tiers'].append(row)
assert len({t['source_manifest_sha256'] for t in result['tiers']})==1
result['source_identical_across_all_tiers']=True
result['all_generation_budgets_met']=all(all(t['generation_budgets'].values()) for t in result['tiers'])
result['all_read_budgets_met']=all(all(t['read_budgets'].values()) for t in result['tiers'])
output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='tiers'},ensure_ascii=False))
for t in result['tiers']:
    print(json.dumps({k:v for k,v in t.items() if k not in ('integrity','resources')},ensure_ascii=False))
