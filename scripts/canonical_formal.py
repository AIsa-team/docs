"""Reproduce a formal canonical assessment without changing workflow selection."""
from datetime import datetime, timezone
from pathlib import Path
import tempfile

import yaml

from canonical_import import assess_canonical_candidate
from export_schema_input_bundle import GitSource
from formal_assessment import FORMAL_SCOPE, ARTIFACT_SCOPE, validate_formal_assessment
from schema_input_bundle import (REBINDING_PATH, UniqueLoader, canonical, regular_read,
    reject_unimplemented_inputs, require, strict_json, INPUT_CONTEXT_PATH, INPUT_RECEIPTS_PATH)


def assess_formal_canonical(root, facts, *, previous_formal_ref, assessed_base,
                            source_receipts=None, checked_at=None):
    """Rebuild pre-import inputs from the assessed Git HEAD, never old coverage.

    A producer caller must pass its independently selected previous formal ref.
    Export replays this same operation before writing or retaining any pointer.
    Main CAS, live reacquisition and publisher provenance remain workflow gates.
    """
    root, facts = Path(root), Path(facts)
    source = GitSource(root, assessed_base)
    require(source.git('rev-parse', 'HEAD').decode().strip() == assessed_base,
            'Canonical assessed base is not the current Git HEAD')
    source.ancestor(previous_formal_ref)
    registry = source.read(assessed_base, 'openapi/registry.yaml')
    reject_unimplemented_inputs(yaml.load(registry, Loader=UniqueLoader),
                                pointer_paths=source.trees[assessed_base])
    selected = [name for name in source.trees[assessed_base] if
                (name.startswith('openapi/') and not name.startswith('openapi/zh/')
                 and name != 'openapi/openapi.json') or name in {
                     REBINDING_PATH, INPUT_CONTEXT_PATH, INPUT_RECEIPTS_PATH}]
    with tempfile.TemporaryDirectory(prefix='canonical-assessed-base-') as folder:
        view = Path(folder)
        for name in selected:
            raw = source.read(assessed_base, name)
            target = view / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        report = assess_canonical_candidate(root, view, root, facts,
            previous_ref=previous_formal_ref,
            source_receipts=source_receipts or root / '.cache/source-reviews.json',
            checked_at=checked_at or datetime.now(timezone.utc))
    report['scope'] = FORMAL_SCOPE
    report.pop('candidate_source_authorization')
    imported = report['canonical_runtime_import']
    imported.update(previous_formal_ref=previous_formal_ref, assessed_base=assessed_base)
    artifact = report['publication_artifact']
    sources = report['source_governance']['sources']
    metadata = {name: {key: strict_json(regular_read(root, 'openapi/upstream/' + name))['info']['x-aisa-source'][key]
                 for key in ('content_hash', 'policy_revision', 'refresh_policy')} for name in sources}
    artifact.update(assessment_scope=ARTIFACT_SCOPE,
                    source_hashes={name: row['source_hash'] for name, row in sources.items()},
                    source_metadata=metadata, baseline_ref=report['baseline_ref'], published_ref=assessed_base)
    receipt = strict_json(regular_read(facts, 'acquisition-receipt.json'))
    validate_formal_assessment(report, receipt)
    return report


def replay_formal_canonical(root, facts, report, *, source_receipts=None):
    """Do not trust a saved PASS: compare a complete reconstruction, typed."""
    imported = report['canonical_runtime_import']
    reproduced = assess_formal_canonical(root, facts,
        previous_formal_ref=imported['previous_formal_ref'], assessed_base=imported['assessed_base'],
        source_receipts=source_receipts,
        checked_at=datetime.fromisoformat(report['source_governance']['checked_at']))
    require(canonical(reproduced) == canonical(report), 'Canonical formal assessment cannot be reproduced')
