from copy import deepcopy
from hashlib import sha256
import json

from django.test import SimpleTestCase

from .public_analytics_policy import ERROR, MAX_BYTES, parse_public_analytics_policy


def policy():
    return {"version": "public-analytics-policy-v1", "origin": "https://product.example.invalid", "routes": [
        {"path": "", "id": "HOME", "locale": "en", "cta_ids": ["public_trial_cta"], "html_sha256": "a" * 64},
        {"path": "tr/", "id": "HOME", "locale": "tr", "cta_ids": ["public_trial_cta"], "html_sha256": "b" * 64},
    ]}


class PublicAnalyticsPolicyTests(SimpleTestCase):
    def parse(self, value):
        return parse_public_analytics_policy(json.dumps(value).encode())

    def test_bounded_minimized_canonical_policy_is_order_independent_and_does_not_copy_input(self):
        original = policy()
        normalized, digest = self.parse(original)
        self.assertEqual(normalized, original)
        self.assertEqual(digest, sha256(json.dumps(original, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
        reordered = deepcopy(original)
        reordered["routes"].reverse()
        self.assertEqual(self.parse(reordered), (normalized, digest))
        original["routes"][0]["id"] = "SECRET"
        self.assertEqual(normalized["routes"][0]["id"], "HOME")
        self.assertNotRegex(json.dumps(normalized), "reviewer|history|occurred_at|actor|organization|customer|token|visitor")

    def test_schema_origin_bounds_private_paths_locale_identity_and_cta_borrowing_fail_categorically(self):
        bad = [None, [], {}, {**policy(), "version": "old"}, {**policy(), "routes": []}]
        for origin in ["http://product.example.invalid", "https://product.example.invalid/", "https://a:b@product.example.invalid",
                       "https://product.example.invalid?token=private", "https://UPPER.example.invalid", "https://product.example.invalid:443"]:
            bad.append({**policy(), "origin": origin})
        for edit in [{"path": "account/reset"}, {"path": "app/7/9"}, {"path": "preview"}, {"path": "404"},
                     {"path": "tr/account/reset", "locale": "tr"}, {"path": "/"}, {"path": "tr/", "locale": "en"},
                     {"path": "other?token=private"}, {"path": "x" * 129}, {"path": "../../private"},
                     {"id": "PRIVATE/TOKEN"}, {"id": True}, {"locale": "de"}, {"locale": []},
                     {"html_sha256": "invalid"}, {"cta_ids": ["raw?token=private"]}, {"cta_ids": [[]]},
                     {"cta_ids": ["public_trial_cta", "public_trial_cta"]}, {"cta_ids": ["c" + str(i) for i in range(17)]}]:
            value = policy(); value["routes"][0].update(edit); bad.append(value)
        one_locale = policy(); one_locale["routes"][1]["id"] = "OTHER"; bad.append(one_locale)
        borrowed = policy(); borrowed["routes"] += [
            {**borrowed["routes"][0], "path": "pricing", "id": "PRICING"},
            {**borrowed["routes"][1], "path": "tr/pricing", "id": "PRICING"},
        ]; bad.append(borrowed)
        duplicate = policy(); duplicate["routes"].append(deepcopy(duplicate["routes"][0])); bad.append(duplicate)
        mismatched = policy(); mismatched["routes"][1]["cta_ids"] = []; bad.append(mismatched)
        for value in bad:
            with self.subTest(value=value), self.assertRaisesMessage(ValueError, ERROR):
                self.parse(value)

    def test_duplicate_nonfinite_invalid_encoding_oversize_and_extra_personal_fields_never_echo_payloads(self):
        for key in ["reviewer", "history", "email", "visitor_id", "account_id", "organization_id", "project_id", "url", "token"]:
            for position in ("root", "route"):
                value = policy()
                (value if position == "root" else value["routes"][0])[key] = "private-secret-customer-value"
                with self.subTest(key=key, position=position), self.assertRaisesMessage(ValueError, ERROR) as error:
                    self.parse(value)
                self.assertEqual(str(error.exception), ERROR)
        valid = json.dumps(policy()).encode()
        for content in [b"", b"\xff", valid.decode(), b" " * (MAX_BYTES + 1), b"[]", b'{"version":NaN}',
                        valid[:-1] + b',"origin":"https://other.example.invalid"}',
                        valid.replace(b'"id": "HOME"', b'"id": "HOME", "id": "PRIVATE"'),
                        b"[" * 1100 + b"]" * 1100]:
            with self.subTest(content_type=type(content)), self.assertRaisesMessage(ValueError, ERROR) as error:
                parse_public_analytics_policy(content)
            self.assertEqual(str(error.exception), ERROR)
