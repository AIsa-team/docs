import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_contract_revisions import compare, update_state

class RevisionTests(unittest.TestCase):
    def test_grouped_facts_and_consumers_use_per_provider_hashes(self):
        documents = {'group': {'document_hash': 'document', 'catalogs': {'a': {'x-aisa-document': {'facts_hash': 'facts'}}}}, 'legacy': {}}
        runtime = {'providers': [{'id': 'a', 'facts_hash': 'facts'}]}
        website = {'x-aisa-document': {'providers': {'group': {'document_hash': 'document'}}}}
        mcp = {'documentHashes': {'group': 'document'}}
        router = {'provider_document_hashes': {'group': 'document'}}
        self.assertEqual(compare(documents, runtime, website, mcp, router), [])
        runtime['providers'][0]['facts_hash'] = 'changed'
        self.assertEqual(compare(documents, runtime, website, mcp, router), ['group:a:facts_hash_mismatch'])
    def test_only_consecutive_failures_escalate(self):
        first = update_state(['a'], {})
        self.assertEqual(first['consecutive'], {'a': 1})
        self.assertEqual(update_state(['a'], first)['consecutive'], {'a': 2})
        self.assertEqual(update_state([], first)['consecutive'], {})
