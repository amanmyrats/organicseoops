"""Stored date literal syntax candidates; no verified publishing event or freshness."""
from datetime import UTC, date, datetime
import json
import re

from django.core.exceptions import ValidationError

from .competitor_dates import encode_dates, parse_dates


METHOD = "competitor-date-literal-candidates-v1"
INTERPRETATION = "stored_article_date_literal_syntax_candidates_not_validated_publication_change_age_freshness_cadence_page_identity_whole_site_causality_approval_ai_or_source_authority"
MAX_RESULT_BYTES = 16 * 1024
CALENDAR = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
INSTANT = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])")


def article_date_literal_candidates(evidence):
    original = parse_dates(encode_dates(evidence))
    candidates = None
    if original["declarations"] is not None:
        candidates = []
        observed = datetime.fromisoformat(original["observed_at"])
        for index, declaration in enumerate(original["declarations"]):
            item = {"declaration_index": index, "state": "truncated_literal" if declaration["truncated"] else "unsupported_literal",
                "calendar_date": None, "utc_instant": None, "after_observation": None}
            value = declaration["value"]
            if not declaration["truncated"]:
                # shortcut: finite calendar/known-offset syntax and microseconds only; extend for an evidenced declaration format.
                try:
                    if CALENDAR.fullmatch(value):
                        item.update(state="calendar_literal", calendar_date=date.fromisoformat(value).isoformat())
                    elif INSTANT.fullmatch(value) and not value.endswith("-00:00"):
                        instant = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
                        item.update(state="offset_literal", utc_instant=instant.isoformat(timespec="microseconds"),
                            after_observation=instant > observed)
                except (ValueError, OverflowError):
                    pass
            candidates.append(item)
    result = {"method_version": METHOD, "evidence": original, "candidates": candidates, "interpretation": INTERPRETATION}
    if len(json.dumps(result, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_RESULT_BYTES:
        raise ValidationError("The original date-literal candidate packet exceeds its bounded size.")
    return result
