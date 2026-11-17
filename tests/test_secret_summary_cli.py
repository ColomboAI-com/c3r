"""Public CI summary CLI: synthetic scanner reports, no image/client execution."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / '.github/scripts/secret_summary.py'
IMAGE = 'sha256:' + 'a' * 64


class SecretSummaryCLI(unittest.TestCase):
    def invoke(self, matches: list[dict[str, object]], *, outcome: str = 'success',
               report_image: str = IMAGE, raw_override: str | None = None,
               image_source: str = 'b' * 40):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory, 'report.json'), Path(directory, 'summary.json')
            source.write_text(raw_override if raw_override is not None else json.dumps({
                'SchemaVersion': 2, 'ArtifactType': 'container_image',
                'Metadata': {'ImageID': report_image}, 'Results': [{'Secrets': matches}]}), encoding='utf-8')
            run = subprocess.run([sys.executable, str(SCRIPT), '--input', str(source),
                '--output', str(output), '--image-id', IMAGE, '--source-commit', 'b' * 40,
                '--scanner-outcome', outcome, '--image-source-commit', image_source],
                capture_output=True, text=True, timeout=5)
            text = output.read_text(encoding='utf-8')
            self.assertNotIn('PRIVATE_FIXTURE_MATCH', text + run.stdout + run.stderr)
            return run.returncode, json.loads(text)

    def test_clean_exact_bound_report_passes(self):
        code, summary = self.invoke([])
        self.assertEqual(code, 0)
        self.assertTrue(summary['scan_complete'])
        self.assertEqual(summary['secret_count'], 0)

    def test_even_low_severity_match_fails_without_publishing_match(self):
        code, summary = self.invoke([{'Severity': 'LOW', 'Match': 'PRIVATE_FIXTURE_MATCH'}])
        self.assertEqual(code, 1)
        self.assertEqual(summary['secret_count'], 1)

    def test_failed_scanner_cannot_borrow_clean_report(self):
        code, summary = self.invoke([], outcome='failure')
        self.assertEqual(code, 1)
        self.assertFalse(summary['scan_complete'])
        self.assertIsNone(summary['secret_count'])

    def test_other_image_report_is_not_qualified(self):
        code, summary = self.invoke([], report_image='sha256:' + 'c' * 64)
        self.assertEqual(code, 1)
        self.assertFalse(summary['scan_complete'])

    def test_duplicate_secret_fields_cannot_hide_a_finding(self):
        raw = ('{"SchemaVersion":2,"ArtifactType":"container_image","Metadata":{"ImageID":"' +
            IMAGE + '"},"Results":[{"Secrets":[{"Match":"PRIVATE_FIXTURE_MATCH"}],"Secrets":[]}]}')
        code, summary = self.invoke([], raw_override=raw)
        self.assertEqual(code, 1)
        self.assertFalse(summary['scan_complete'])

    def test_image_revision_label_must_match_the_tested_source(self):
        code, summary = self.invoke([], image_source='c' * 40)
        self.assertEqual(code, 1)
        self.assertFalse(summary['scan_complete'])
