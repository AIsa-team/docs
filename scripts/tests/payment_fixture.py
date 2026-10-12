"""Frozen payment inputs; unit tests never bind themselves to generated main."""
import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / 'fixtures/payment-discovery'


def install_payment_fixture(root):
    from generate_payment_discovery import candidate
    root = Path(root)
    source = json.loads((FIXTURES / 'source-v3.json').read_text())
    # This helper tests payment closure, not bilingual runtime page generation.
    source['info'].pop('x-aisa-document', None)
    provider = root / 'openapi/polymarket-data.json'
    provider.parent.mkdir(parents=True, exist_ok=True)
    provider.write_text(json.dumps(source))
    evidence = root / 'discovery/payment-evidence.json'
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_bytes((FIXTURES / 'evidence-v2.json').read_bytes())
    (root / 'discovery/openapi.json').write_text(json.dumps(candidate(root)))
