import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compose_openapi import validate_payment_capabilities


class CapabilityAccessFieldTests(unittest.TestCase):
    def test_access_fields_of_code_owned_operations_are_accepted(self):
        # As AIsa Social and AIsa Ads publish them (Services validatePublicationCapabilities).
        validate_payment_capabilities({"x-aisa-capabilities": {
            "required_scope": "social:draft", "publish_scope": "social:publish",
            "scope_rule": "Drafts need social:draft; scheduling or publishing needs social:publish.",
            "quote": {"supported": False, "reason": "not_quoted"}}})
        validate_payment_capabilities({"x-aisa-capabilities": {
            "capability": "social.public.account.get@1", "required_scope": "social:read", "shape": "entity",
            "mpp": True, "x402": False}})

    def test_access_fields_must_be_text(self):
        with self.assertRaisesRegex(ValueError, "access text"):
            validate_payment_capabilities({"x-aisa-capabilities": {"required_scope": ["social:read"]}})

    def test_unknown_fields_are_still_refused(self):
        with self.assertRaisesRegex(ValueError, "invalid runtime payment capabilities"):
            validate_payment_capabilities({"x-aisa-capabilities": {"mpp": True, "free": True}})


if __name__ == "__main__":
    unittest.main()
