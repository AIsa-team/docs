"""Candidate CI must assess the acquired graph using its producer mode."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


class CandidatePublicationModeTests(unittest.TestCase):
    def test_actual_workflow_selects_canonical_or_facts_and_propagates_errors(self):
        root = Path(__file__).resolve().parents[2]
        workflow = yaml.safe_load((root / '.github/workflows/test-runtime-contracts.yml').read_text())
        step = next(s for s in workflow['jobs']['artifact-contracts']['steps']
                    if s.get('name') == 'Check actual candidate readiness')
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            command = folder / 'python'
            command.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALL_LOG"\n'
                'if [ "$1 $2" = "scripts/runtime_publication.py mode" ]; then\n'
                '  printf "%s\\n" "$TEST_MODE"\n  exit 0\nfi\nexit "$TEST_STATUS"\n')
            command.chmod(0o755)
            for mode, status in (('canonical', 0), ('canonical', 3), ('facts', 0), ('facts', 3), ('invalid', 0)):
                log = folder / 'calls'
                log.write_text('')
                result = subprocess.run(['bash', '-e', '-c', step['run']], capture_output=True, env={
                    **os.environ, 'PATH': str(folder) + os.pathsep + os.environ['PATH'],
                    'CALL_LOG': str(log), 'TEST_MODE': mode, 'TEST_STATUS': str(status),
                    'REVIEWED_BASELINE': 'a' * 40, 'PUBLISHED_REF': 'b' * 40,
                })
                calls = log.read_text()
                with self.subTest(mode=mode, status=status):
                    if mode == 'canonical':
                        self.assertIn('runtime_publication.py assess', calls)
                        self.assertNotIn('check_contract_candidate.py', calls)
                        self.assertEqual(result.returncode, status)
                    elif mode == 'facts':
                        self.assertIn('check_contract_candidate.py', calls)
                        self.assertNotIn('runtime_publication.py assess', calls)
                        self.assertEqual(result.returncode, status)
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertNotIn('--report', calls)
                    self.assertNotIn(' --write', calls)
        self.assertIn('GH_TOKEN', step['env'])


if __name__ == '__main__':
    unittest.main()
