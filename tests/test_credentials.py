import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from credentials import load_credentials


class CredentialPolicyTests(unittest.TestCase):
    def test_password_boundaries_preserve_other_fields_and_source_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.json"
            for length in (8, 15, 16, 17, 25):
                with self.subTest(password_length=length):
                    source = {
                        "username": "local-test-user",
                        "password": "Ab9!SyntheticPasswordLong!"[:length],
                        "verification_code": "EncryptionKeyThatExceeds16Characters",
                    }
                    path.write_text(json.dumps(source), encoding="utf-8")
                    original_bytes = path.read_bytes()
                    effective = load_credentials(path)
                    self.assertEqual(effective["password"], source["password"][:16])
                    self.assertEqual(effective["username"], source["username"])
                    self.assertEqual(effective["verification_code"], source["verification_code"])
                    self.assertEqual(path.read_bytes(), original_bytes)

    def test_invalid_credentials_are_rejected_before_protocol_use(self):
        invalid = [
            [],
            {"username": "test", "password": ""},
            {"username": "test", "password": 123},
            {"username": "test\nuser", "password": "dummy-password"},
            {"username": "test", "password": "dummy\npassword"},
            {"username": "test", "password": "dummy-password", "verification_code": 123},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.json"
            for index, value in enumerate(invalid):
                with self.subTest(case=index):
                    path.write_text(json.dumps(value), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        load_credentials(path)


if __name__ == "__main__":
    unittest.main()
