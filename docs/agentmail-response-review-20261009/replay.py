"""Offline actual-provider comparison; no network or generated publication writes."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts'))
from compose_openapi import compose
from runtime_registry import public_mirror_index
from prepare_agentmail_response_reference import BASE_SHA256
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--facts', type=Path, required=True)
p.add_argument('--base', type=Path, required=True)
a=p.parse_args()
receipt=json.loads((Path(__file__).parent/'actual-provider-replay.json').read_text())
assert hashlib.sha256(a.facts.read_bytes()).hexdigest()==receipt['actual_provider_facts_sha256']
assert hashlib.sha256(a.base.read_bytes()).hexdigest()==BASE_SHA256
facts=json.loads(a.facts.read_text())
before=json.loads(a.base.read_text())
after=json.loads((ROOT/'openapi/upstream/agentmail-official.json').read_text())
mirrors=public_mirror_index(ROOT)
old, old_pending=compose(facts,before,public_mirrors=mirrors)
new, new_pending=compose(facts,after,public_mirrors=mirrors)
assert old_pending==new_pending==[]
assert set(old['paths'])==set(new['paths'])
for path,item in old['paths'].items():
    assert set(item)==set(new['paths'][path])
    for method,operation in item.items():
        for field in ('operationId','requestBody','parameters','x-aisa-pricing','x-aisa-validation','security'):
            assert operation.get(field)==new['paths'][path][method].get(field),(path,method,field)
counts={'request_pending_before':len(old_pending),'request_pending_after':len(new_pending),
        'response_pending_before':len(old['info']['x-aisa-document']['response_pending']),
        'response_pending_after':len(new['info']['x-aisa-document']['response_pending']),
        'operations':sum(len(item) for item in new['paths'].values())}
assert all(receipt[key]==value for key,value in counts.items())
print(json.dumps(counts,sort_keys=True))
