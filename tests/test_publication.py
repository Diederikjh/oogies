"""Publication checks cover network addresses without committing real ones."""
import base64
import ipaddress
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from check_publication import file_findings, inspect_bytes, known_patterns


class PublicationTests(unittest.TestCase):
    def test_private_addresses_are_rejected_but_documentation_and_loopback_are_allowed(self):
        for number in (0x0a010203, 0xac100203, 0xc0a8fffe):
            address = str(ipaddress.IPv4Address(number)).encode()
            self.assertTrue(inspect_bytes(b"host=" + address, {}))
        for prefix in (0xfc00, 0xfe80, 0xfec0):
            address = str(ipaddress.IPv6Address((prefix << 112) + 1)).encode()
            self.assertTrue(inspect_bytes(address, {}))
        self.assertEqual(inspect_bytes(b"192.0.2.10 127.0.0.1 ::1 2001:db8::1", {}), [])

    def test_known_values_are_detected_in_encoded_forms_without_reporting_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / '.local').mkdir()
            value = "synthetic-secret-with-%-and-spaces"
            (root / '.local/nvr-credentials.json').write_text(json.dumps(
                {"username":"synthetic-user", "password":value, "verification_code":value + "-full"}))
            patterns = known_patterns(root)
            findings = inspect_bytes(base64.b64encode(value[:16].encode()), patterns)
            self.assertTrue(findings)
            self.assertNotIn(value, json.dumps(findings))

    def test_ignored_files_cannot_be_published_and_archives_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); private = root / '.local'
            private.mkdir(); path = private / 'capture.json'; path.write_text('{}')
            self.assertEqual(file_findings(path, root, {})[0]['kind'], 'private-file')
            archive = root / 'sample.zip'
            with zipfile.ZipFile(archive, 'w') as output:
                output.writestr('example.bin', b'\x00synthetic-private-key\x00')
            findings = file_findings(archive, root, {b'synthetic-private-key':'verification_code'})
            self.assertEqual(findings[0]['kind'], 'archive-private-value')
            self.assertNotIn('synthetic-private-key', json.dumps(findings))
