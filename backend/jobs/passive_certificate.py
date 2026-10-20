"""Pure date interpretation, not proof of a validated TLS handshake or server identity."""
import re
import ssl
from datetime import UTC, datetime, timedelta

from django.core.exceptions import ValidationError


METHOD = "passive-peer-certificate-dates-v1"
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
GMT_DATE = re.compile(r"([A-Z][a-z]{2}) ( [1-9]|[12][0-9]|3[01]) ([0-9]{2}):([0-9]{2}):([0-9]{2}) ([0-9]{4}) GMT")


def _original_date(value):
    if type(value) is not str or len(value) != 24:
        return None
    match = GMT_DATE.fullmatch(value)
    if match is None or match[1] not in MONTHS:
        return None
    try:
        # Construct first: ssl's time parser alone may normalize impossible calendar dates.
        date = datetime(int(match[6]), MONTHS.index(match[1]) + 1, int(match[2]),
                        int(match[3]), int(match[4]), int(match[5]), tzinfo=UTC)
        canonical = f"{MONTHS[date.month - 1]} {date.day:2d} {date.hour:02d}:{date.minute:02d}:{date.second:02d} {date.year:04d} GMT"
        seconds = (date - datetime(1970, 1, 1, tzinfo=UTC)) // timedelta(seconds=1)
        if canonical != value or ssl.cert_time_to_seconds(value) != seconds:
            return None
    except (ValueError, OverflowError, OSError):
        return None
    return date


def observe_peer_certificate_dates(certificate, *, observed_at):
    """Read only original date fields; absent/unsupported dates stay null, never zero."""
    if type(observed_at) is not datetime or observed_at.tzinfo is None:
        raise ValidationError("An aware nonfuture certificate observation date is required.")
    try:
        if observed_at.utcoffset() is None:
            raise ValueError
        observed_at = observed_at.astimezone(UTC)
    except (ValueError, OverflowError):
        raise ValidationError("An aware nonfuture certificate observation date is required.") from None
    if observed_at > datetime.now(UTC):
        raise ValidationError("An aware nonfuture certificate observation date is required.")
    result = {"method_version": METHOD, "coverage": "one_original_peer_certificate_reported_date_interval_only",
        "interpretation": "reported_dates_not_tls_chain_hostname_revocation_validation_or_server_identity",
        "observed_at": observed_at.isoformat(timespec="microseconds"), "state": "unavailable",
        "not_before": None, "not_after": None, "position": None, "remaining_microseconds": None}
    if type(certificate) is not dict:
        return result
    start, end = (_original_date(certificate.get(key)) for key in ("notBefore", "notAfter"))
    if start is None or end is None or start > end:
        return result
    result.update(state="observed", not_before=start.isoformat(timespec="microseconds"),
        not_after=end.isoformat(timespec="microseconds"),
        position="before_reported_window" if observed_at < start else
            "after_reported_window" if observed_at > end else "within_reported_window",
        remaining_microseconds=str((end - observed_at) // timedelta(microseconds=1)))
    return result
