import unittest

from util.redact import redact_token, redact_email, redact_dict


class RedactToken(unittest.TestCase):
    def test_long_token_keeps_4_and_4(self):
        self.assertEqual(redact_token("abcd12345678wxyz"), "abcd********wxyz")

    def test_exactly_8_fully_masked(self):
        self.assertEqual(redact_token("abcd1234"), "********")

    def test_shorter_than_8_fully_masked(self):
        self.assertEqual(redact_token("abc"), "***")
        self.assertEqual(redact_token("a"), "*")

    def test_none_and_empty(self):
        self.assertEqual(redact_token(None), "")
        self.assertEqual(redact_token(""), "")


class RedactEmail(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(redact_email("alice@example.com"), "a***e@example.com")

    def test_short_local_fully_masked(self):
        self.assertEqual(redact_email("ab@x.io"), "**@x.io")
        self.assertEqual(redact_email("a@x.io"), "*@x.io")

    def test_no_at_fully_masked(self):
        self.assertEqual(redact_email("notanemail"), "**********")

    def test_none_and_empty(self):
        self.assertEqual(redact_email(None), "")
        self.assertEqual(redact_email(""), "")


class RedactDict(unittest.TestCase):
    def test_masks_specified_keys_email_vs_token(self):
        out = redact_dict(
            {"token": "abcd12345678wxyz", "email": "alice@example.com",
             "keep": "visible"},
            ["token", "email"],
        )
        self.assertEqual(out["token"], "abcd********wxyz")
        self.assertEqual(out["email"], "a***e@example.com")
        self.assertEqual(out["keep"], "visible")

    def test_missing_and_none_keys_skipped(self):
        out = redact_dict({"a": None}, ["a", "absent"])
        self.assertEqual(out, {"a": None})

    def test_non_dict_passthrough(self):
        self.assertEqual(redact_dict(None, ["x"]), None)


if __name__ == "__main__":
    unittest.main()
