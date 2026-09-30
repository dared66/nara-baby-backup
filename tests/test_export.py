import csv
import io
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError

spec = importlib.util.spec_from_file_location('exporter', Path(__file__).resolve().parents[1] / 'nara_export.py')
e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e)


class FakeClient:
    uid = 'user1'

    def get(self, path):
        if path.endswith('familyKeyz'):
            return {'family1': True, 'family2': True}
        if path.endswith('childz'):
            return {'child1': {'name': '=unsafe name'}, 'child2': {'name': 'No history'}}
        return {'unknown_future_field': {'keep': True}}

    def sync(self, family):
        tracks = {'record1': {'childKey': 'child1', 'beginDt': 0, 'note': '=HYPERLINK("example")',
                              'unknown': {'nested': [1, 2]}, 'amount': -3}}
        return {'result': {'trackz': tracks}} if family == 'family1' else {'result': {'data': {'trackz': tracks}}}


class Tests(unittest.TestCase):
    def test_multiple_families_lossless_json_and_safe_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'backup'
            report = e.export(FakeClient(), folder)
            self.assertTrue(report['complete'])
            self.assertEqual([f['activities'] for f in report['families']], [1, 1])
            tracks = json.loads((folder / 'family-01/activities.json').read_text())
            self.assertEqual(tracks, e.tracks_from(FakeClient().sync('family1')))
            with (folder / 'family-01/activities.csv').open(encoding='utf-8-sig', newline='') as f:
                row = next(csv.DictReader(f))
            self.assertTrue(row['note'].startswith("'="))
            self.assertTrue(row['export_child_name'].startswith("'="))
            self.assertEqual(row['amount'], '-3')
            self.assertEqual(row['export_begin_utc'], '1970-01-01T00:00:00+00:00')
            with self.assertRaises(FileExistsError):
                e.export(FakeClient(), folder)

    def test_partial_failure_keeps_other_family_and_raw_response(self):
        class Broken(FakeClient):
            def sync(self, family):
                return {'result': {'unexpected': []}} if family == 'family1' else super().sync(family)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'backup'
            report = e.export(Broken(), folder)
            self.assertFalse(report['complete'])
            self.assertTrue((folder / 'family-01/activity-sync.json').exists())
            self.assertTrue((folder / 'family-02/activities.json').exists())
            self.assertFalse(json.loads((folder / 'export-report.json').read_text())['complete'])

    def test_snapshot_denied_still_exports_history(self):
        class Restricted(FakeClient):
            def get(self, path):
                if path == '/familyz/family1':
                    raise e.ExportError('Access denied')
                return super().get(path)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'backup'
            report = e.export(Restricted(), folder)
            self.assertFalse(report['complete'])
            self.assertTrue((folder / 'family-01/activities.csv').exists())

    def test_profiles_denied_still_exports_history(self):
        class Restricted(FakeClient):
            def get(self, path):
                if path.endswith('childz'):
                    raise e.ExportError('Access denied')
                return super().get(path)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'backup'
            report = e.export(Restricted(), folder)
            self.assertFalse(report['complete'])
            self.assertTrue((folder / 'family-01/activities.csv').exists())

    def test_unknown_and_error_shapes_fail_closed(self):
        for data in [{}, {'error': {}}, {'result': {'error': {}}}, {'result': {'trackz': []}}, {'result': {'trackz': {'id': None}}}]:
            with self.subTest(data=data), self.assertRaises(e.ExportError):
                e.tracks_from(data)
        self.assertEqual(e.tracks_from({'result': {'trackz': None}}), {})

    def test_secrets_not_in_http_error(self):
        class BadOpener:
            def open(self, req, timeout):
                raise HTTPError(req.full_url, 403, 'secret password', {}, io.BytesIO(b'private response'))
        client = e.Client()
        client.opener = BadOpener()
        with self.assertRaises(e.ExportError) as caught:
            client.login('private@example.com', 'secret password')
        self.assertNotIn('secret', str(caught.exception))
        self.assertNotIn('private', str(caught.exception))

    def test_http_cleanup_failure_cannot_expose_raw_error(self):
        class BrokenClose(HTTPError):
            def close(self):
                raise RuntimeError('private cleanup detail')
        class BadOpener:
            def open(self, req, timeout):
                raise BrokenClose(req.full_url, 403, 'secret password', {}, io.BytesIO(b'private response'))
        client = e.Client()
        client.opener = BadOpener()
        with self.assertRaises(e.ExportError) as caught:
            client.login('private@example.invalid', 'secret password')
        self.assertNotIn('private', str(caught.exception))
        self.assertNotIn('secret', str(caught.exception))
        self.assertIn('HTTP 403', str(caught.exception))

    def test_redirects_blocked_and_identifiers_validated(self):
        self.assertIsNone(e.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com'))
        with self.assertRaises(e.ExportError):
            e.key('../other')


if __name__ == '__main__':
    unittest.main()
