from copy import deepcopy

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from providers.adapters import _check_schema
from . import competitor_collection as collection
from .competitor_metadata import observe_static_metadata
from .competitor_synthesis import OUTPUT_SCHEMA, validate_interpretations


def comparison():
    before = observe_static_metadata(body=b'<title>Original title</title><meta name="description" content="Original description">',
        body_complete=True, url="https://competitor.example.invalid/", observed_at="2026-01-01T00:00:00.000001+00:00")
    after = observe_static_metadata(body=b'<title>Later title</title><h1>Heading</h1>',
        body_complete=True, url=before["url"], observed_at="2026-01-01T00:00:00.000002+00:00")
    return {"state": "comparable_original_static_metadata", "comparable": True, "body_changed": True,
        "previous": {"evidence": before}, "current": {"evidence": after},
        "metadata_changed": {"title": True, "description": True},
        "count_deltas": {key: after["counts"][key] - before["counts"][key] for key in before["counts"]}}


def notes(**changes):
    return {"interpretations": [{"text": "Unverified interpretation for human review.", "reference": "previous_title", "quote": "Original", **changes}]}


class CompetitorInterpretationTests(SimpleTestCase):
    def test_adapter_subset_schema_fixed_references_exact_quotes_safe_literal_text_and_fresh_objects(self):
        _check_schema(OUTPUT_SCHEMA)
        original = comparison()
        for reference, quote in (("previous_title", "Original"), ("previous_description", "description"),
            ("current_title", "Later title"), ("comparison_state", original["state"]), ("body_changed", "true"),
            ("metadata_changed", collection._encode(original["metadata_changed"]).decode()),
            ("count_deltas", collection._encode(original["count_deltas"]).decode())):
            value = notes(reference=reference, quote=quote, text="<script>literal unverified text</script>")
            result = validate_interpretations(value, original)
            self.assertEqual(result, value)
            result["interpretations"][0]["text"] = "Edited returned text"
            self.assertEqual(value["interpretations"][0]["text"], "<script>literal unverified text</script>")

    def test_closed_shape_strict_types_control_unicode_and_all_byte_character_count_limits(self):
        original = comparison()
        invalid = [None, [], {}, {"interpretations": []}, {"interpretations": {}},
            {**notes(), "approved": True}, {"interpretations": [notes()["interpretations"][0]] * 11},
            {"interpretations": [False]}, {"interpretations": [{**notes()["interpretations"][0], "rank": 1}]}]
        for change in ({"reference": []}, {"reference": "rank_gain"}, {"reference": 1}, {"quote": None}, {"text": True},
            {"text": ""}, {"text": " "}, {"text": " x"}, {"text": "x" * 501}, {"quote": "x" * 301},
            {"text": "line\nbreak"}, {"text": "bidi\u202etest"}, {"text": "surrogate\ud800"}, {"quote": "Original\x00"}):
            invalid.append(notes(**change))
        # Each note respects character bounds; the complete UTF-8 byte limit is independent.
        invalid.append({"interpretations": [notes(text="😀" * 500)["interpretations"][0]] * 5})
        for value in invalid:
            with self.subTest(value=repr(value)), self.assertRaises(ValidationError): validate_interpretations(value, original)

    def test_foreign_or_fabricated_quotes_null_empty_truncation_and_partial_numeric_citations_are_rejected(self):
        original = comparison()
        for reference, quote in (("current_description", "missing"), ("previous_title", "Other title"),
            ("body_changed", "1"), ("count_deltas", '"h1":1'), ("metadata_changed", "null")):
            with self.assertRaises(ValidationError): validate_interpretations(notes(reference=reference, quote=quote), original)
        for state in ("unavailable", "empty", "truncated"):
            source = deepcopy(original)
            if state == "unavailable": source["previous"]["evidence"]["state"] = "unavailable"; source["previous"]["evidence"]["metadata"] = None
            if state == "empty": source["previous"]["evidence"]["metadata"]["title"] = ""
            if state == "truncated": source["previous"]["evidence"]["metadata"]["title_truncated"] = True
            source.update(comparable=False, state="incomparable_unavailable_or_truncated_metadata", metadata_changed=None, count_deltas=None)
            with self.assertRaises(ValidationError): validate_interpretations(notes(), source)
            with self.assertRaises(ValidationError): validate_interpretations(notes(reference="count_deltas", quote="null"), source)
            self.assertEqual(validate_interpretations(notes(reference="comparison_state", quote=source["state"]), source)["interpretations"][0]["quote"], source["state"])
