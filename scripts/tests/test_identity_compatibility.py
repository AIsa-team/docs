"""Actual published EN/ZH identity proofs, real stage/pages and strict surfaces."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from identity_compatibility import (KEY, PublishedHistory, published_history, attach_history,
    metadata, validate_document_identities, canonicalize_localized)
from pull_openapi import stage
from publication_surface import validate_surfaces, publication_hashes
from compose_openapi import METHODS
import runtime_localize_openapi_zh as localization
import runtime_consolidate_openapi as consolidate

REPO = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((Path(__file__).with_name('fixtures') / 'published-locale-identities.json').read_text())
REF = FIXTURE['published_ref']


class PublishedIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'candidate'
        subprocess.run(['git', 'clone', '--shared', '--no-checkout', '-q', str(REPO), str(self.root)], check=True)
        self.history = published_history(self.root, REF)
        providers = {Path(row['proof']['canonical_source_file']).stem for row in FIXTURE['aliases']}
        (self.root / 'facts').mkdir(); (self.root / 'openapi/zh').mkdir(parents=True)
        self.documents = {}
        for provider in sorted(providers):
            original, _ = self.history.read(REF, f'openapi/{provider}.json')
            locale, _ = self.history.read(REF, f'openapi/zh/{provider}.json')
            (self.root / f'openapi/{provider}.json').write_text(json.dumps(original))
            (self.root / f'openapi/zh/{provider}.json').write_text(json.dumps(locale))
            self.documents[provider] = original
            paths = {}
            for row in FIXTURE['aliases']:
                proof = row['proof']
                if proof['canonical_source_file'] == f'openapi/{provider}.json':
                    paths.setdefault(proof['public_path'], {})[proof['method'].lower()] = {
                        'operationId': row['canonical_operation_id'], 'summary': 'Published identity fixture',
                        'x-aisa-validation': 'runtime', 'x-aisa-status': 'enabled',
                        'parameters': [], 'responses': {'200': {'description': 'Success'}},
                    }
            facts = {'openapi': '3.1.0', 'info': {'title': provider, 'version': '1',
                'x-aisa-document': {'facts_hash': 'sha256:fixture-' + provider}},
                'servers': [{'url': 'https://api.aisa.one'}], 'paths': paths}
            (self.root / f'facts/{provider}.json').write_text(json.dumps(facts))
        (self.root / 'openapi/registry.yaml').write_text(yaml.safe_dump({'auto_register': False,
            'providers': {provider: {} for provider in sorted(providers)}}))
        (self.root / 'docs.json').write_text(json.dumps({'navigation': {'languages': [
            {'language': lang, 'tabs': [{'tab': tab, 'groups': []}]}
            for lang, tab in [('en', 'API Reference'), ('zh', 'API 参考')]]}}))

    def write(self, changes):
        for path, text in changes.items():
            path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)

    def compose(self):
        context = {'offline': True, 'published_ref': REF}
        changes, _ = stage(self.root, self.root / 'facts', 'unused', readiness_context=context)
        self.write(changes)
        return changes

    def test_all_27_published_zh_machine_ids_survive_real_stage_and_multiple_rounds(self):
        self.compose()
        self.assertEqual(validate_surfaces(self.root, REF)['providers'], len(self.documents))
        for row in FIXTURE['aliases']:
            proof = row['proof']; provider = Path(proof['canonical_source_file']).stem
            source = json.loads((self.root / f'openapi/{provider}.json').read_text())
            target = json.loads((self.root / f'openapi/zh/{provider}.json').read_text())
            route, method = proof['public_path'], proof['method'].lower()
            # Generated documents use absolute current runtime paths.
            english, chinese = source['paths'][route][method], target['paths'][route][method]
            self.assertEqual(english['operationId'], row['canonical_operation_id'])
            self.assertEqual(chinese['operationId'], proof['operation_id'])
            self.assertEqual(english[KEY], chinese[KEY])
            self.assertEqual(english[KEY], row['metadata'])
            self.assertEqual(english[KEY]['historical_aliases'], [proof])
            self.assertEqual(english[KEY]['canonical_operation_id'], row['canonical_operation_id'])
            page = self.root / f"zh/api-reference/{provider}/{row['canonical_operation_id']}.mdx"
            self.assertIn('x-aisa-operation-id: ' + json.dumps(proof['operation_id']), page.read_text())
        for _ in range(2):
            self.assertEqual(self.compose(), {})
            validate_surfaces(self.root, REF)
        with patch.object(consolidate, 'OPENAPI_DIR', str(self.root / 'openapi')):
            aggregate = consolidate.build_unified_spec()
        operations = [op for item in aggregate['paths'].values() for method, op in item.items() if method in METHODS]
        identities = {op['operationId']: op for op in operations}
        for row in FIXTURE['aliases']:
            self.assertEqual(identities[row['canonical_operation_id']][KEY]['historical_aliases'], [row['proof']])
            self.assertNotIn(row['proof']['operation_id'], identities)
        hashes = publication_hashes(self.root)
        self.assertTrue(all(f'openapi/zh/{provider}.json' in hashes for provider in self.documents))
        # Publishing the derived graph must preserve original immutable proof
        # refs instead of assigning new provenance on every release.
        subprocess.run(['git', 'add', 'openapi'], cwd=self.root, check=True)
        subprocess.run(['git', '-c', 'user.name=Identity Test', '-c', 'user.email=identity@example.invalid',
            '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null', 'commit', '-qm', 'Derived identity fixture'], cwd=self.root, check=True)
        next_ref = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=self.root, text=True).strip()
        next_history = published_history(self.root, next_ref)
        for row in FIXTURE['aliases']:
            self.assertEqual(next_history.aliases[row['canonical_operation_id']], [row['proof']])

    def test_alias_follows_current_routing_and_preserves_existing_page_url(self):
        self.compose()
        row = next(row for row in FIXTURE['aliases'] if row['proof']['canonical_source_file'] == 'openapi/edinet.json')
        proof = row['proof']; old = proof['public_path']; current = old + '/moved'
        path = self.root / 'facts/edinet.json'; facts = json.loads(path.read_text())
        facts['paths'][current] = facts['paths'].pop(old)
        facts['info']['x-aisa-document']['facts_hash'] = 'sha256:moved-fixture'
        path.write_text(json.dumps(facts))
        self.compose()
        source = json.loads((self.root / 'openapi/edinet.json').read_text())
        locale = json.loads((self.root / 'openapi/zh/edinet.json').read_text())
        self.assertNotIn(old, source['paths'])
        self.assertEqual(locale['paths'][current][proof['method'].lower()]['operationId'], proof['operation_id'])
        self.assertEqual(source['paths'][current][proof['method'].lower()][KEY], row['metadata'])
        for language in ('', 'zh/'):
            page = self.root / f"{language}api-reference/edinet/{row['canonical_operation_id']}.mdx"
            self.assertIn(current, page.read_text())
        validate_surfaces(self.root, REF)
        self.assertEqual(self.compose(), {})

    def test_localization_generator_really_keeps_zh_ids_and_validates_wire_equivalence(self):
        for path in (self.root / 'facts').glob('*.json'):
            facts = json.loads(path.read_text())
            for item in facts['paths'].values():
                for operation in item.values():
                    operation['x-aisa-pricing'] = {'model': 'per_request', 'cost_tier': 'low'}
            path.write_text(json.dumps(facts))
        self.compose()
        # Translation uses existing deterministic glossary/identity translation,
        # with no model or paid network calls.
        with patch.multiple(localization, ROOT=self.root, OPENAPI_DIR=self.root/'openapi',
                ZH_OPENAPI_DIR=self.root/'openapi/zh', API_DIR=self.root/'api-reference',
                ZH_API_DIR=self.root/'zh/api-reference'), \
                patch.object(localization, 'load_catalog', return_value={'entries': {}}), \
                patch.object(localization, 'translation', side_effect=lambda catalog, text: text):
            localization.generate(REF)
            first = publication_hashes(self.root)
            localization.generate(REF)
            self.assertEqual(publication_hashes(self.root), first)
            localization.validate(REF)
        validate_surfaces(self.root, REF)
        for row in FIXTURE['aliases']:
            provider = Path(row['proof']['source_file']).stem
            operation = json.loads((self.root/f'openapi/zh/{provider}.json').read_text())['paths'][row['proof']['public_path']][row['proof']['method'].lower()]
            self.assertEqual(operation['operationId'], row['proof']['operation_id'])
            self.assertEqual(operation['x-aisa-pricing'], {'model': 'per_request', 'cost_tier': 'low'})

    def test_forged_source_hash_id_ref_and_shadow_are_rejected(self):
        self.compose()
        provider = next(iter(self.documents)); path = self.root/f'openapi/{provider}.json'
        original = json.loads(path.read_text())
        tagged = next(op for item in original['paths'].values() for op in item.values() if isinstance(op,dict) and KEY in op)
        canonical = tagged['operationId']; proof = tagged[KEY]['historical_aliases'][0]
        for field, replacement in [('source_sha256','0'*64), ('operation_id','invented_alias'),
                ('published_ref','f'*40), ('public_path','/invented'), ('method','DELETE')]:
            with self.subTest(field=field):
                forged = copy.deepcopy(original)
                target = next(op for item in forged['paths'].values() for op in item.values() if isinstance(op,dict) and KEY in op)
                bad = copy.deepcopy(proof); bad[field] = replacement
                target[KEY] = metadata(canonical,[bad])
                with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                    validate_document_identities({provider:forged}, self.history)
        forged = copy.deepcopy(original)
        target = next(op for item in forged['paths'].values() for op in item.values() if isinstance(op, dict) and KEY in op)
        target[KEY]['schema_version'] = True
        from compose_openapi import digest
        target[KEY]['sha256'] = digest({k: v for k, v in target[KEY].items() if k != 'sha256'})
        with self.assertRaisesRegex(ValueError, 'declaration'):
            validate_document_identities({provider: forged}, self.history)
        from identity_compatibility import validate_namespace
        with self.assertRaisesRegex(ValueError, 'shadows canonical'):
            validate_namespace({proof['operation_id']}, {canonical:[proof]})
        with self.assertRaisesRegex(ValueError, 'conflicting owners'):
            validate_namespace(set(), {canonical:[proof], 'another_canonical':[proof]})

    def test_dropping_compatibility_or_altering_zh_request_is_not_language_translation(self):
        self.compose()
        provider = next(iter(self.documents)); source_path = self.root/f'openapi/{provider}.json'
        original_bytes = source_path.read_bytes()
        original = json.loads(source_path.read_text())
        target = next(op for item in original['paths'].values() for op in item.values() if isinstance(op,dict) and KEY in op)
        del target[KEY]
        source_path.write_text(json.dumps(original))
        with self.assertRaisesRegex(ValueError, 'identity disappeared'):
            validate_surfaces(self.root, REF)
        source_path.write_bytes(original_bytes)
        locale = self.root/f'openapi/zh/{provider}.json'; altered=json.loads(locale.read_text())
        target = next(op for item in altered['paths'].values() for op in item.values() if isinstance(op,dict) and KEY in op)
        target['parameters']=[{'name':'unexpected','in':'query','schema':{'type':'string'}}]
        locale.write_text(json.dumps(altered))
        with self.assertRaisesRegex(ValueError, 'protocol changed'):
            validate_surfaces(self.root, REF)


if __name__ == '__main__':
    unittest.main()
