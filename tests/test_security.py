import unittest

from peopleops.security import K_MIN, redact, sign, suppress_small_cells, verify_signature

BODY = b'{"action":"candidateHire"}'


class SignatureTests(unittest.TestCase):
    def test_valid_signature_passes(self):
        self.assertTrue(verify_signature("s3cret", BODY, sign("s3cret", BODY)))

    def test_matches_ashby_documented_format(self):
        self.assertRegex(sign("s3cret", BODY), r"^sha256=[0-9a-f]{64}$")

    def test_tampered_body_fails(self):
        self.assertFalse(verify_signature("s3cret", BODY + b" ", sign("s3cret", BODY)))

    def test_wrong_secret_fails(self):
        self.assertFalse(verify_signature("other", BODY, sign("s3cret", BODY)))

    def test_missing_or_malformed_header_fails(self):
        for header in (None, "", "sha256=", "md5=abc", "abc"):
            self.assertFalse(verify_signature("s3cret", BODY, header))

    def test_empty_secret_never_verifies(self):
        self.assertFalse(verify_signature("", BODY, sign("", BODY)))


class RedactionTests(unittest.TestCase):
    def test_pii_is_masked(self):
        out = redact("Mail jane.doe@corp.com or call 415-555-0199, SSN 123-45-6789, I earn $150,000")
        for leaked in ("jane.doe", "415-555", "123-45-6789", "150,000"):
            self.assertNotIn(leaked, out)
        for tag in ("[EMAIL]", "[PHONE]", "[SSN]", "[AMOUNT]"):
            self.assertIn(tag, out)

    def test_money_can_be_kept(self):
        self.assertIn("$750", redact("stipend is $750", money=False))


class KAnonymityTests(unittest.TestCase):
    def test_small_cells_are_hidden(self):
        rows = suppress_small_cells([{"team": "A", "n": 4, "days": 30}, {"team": "B", "n": 5, "days": 31}], hide_keys=("days",))
        self.assertTrue(rows[0]["suppressed"] and rows[0]["n"] is None and rows[0]["days"] is None)
        self.assertFalse(rows[1]["suppressed"])
        self.assertEqual((rows[1]["n"], rows[1]["days"]), (5, 31))

    def test_threshold_is_five(self):
        self.assertEqual(K_MIN, 5)


if __name__ == "__main__":
    unittest.main()
