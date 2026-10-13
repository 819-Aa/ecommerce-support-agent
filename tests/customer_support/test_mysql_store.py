from customer_support.mysql_store import _created_at_for_display


def test_created_at_for_display_converts_legacy_naive_utc() -> None:
    assert _created_at_for_display("2026-07-21 09:33:07.203970") == "2026-07-21 17:33:07"


def test_created_at_for_display_converts_explicit_utc_offset() -> None:
    assert _created_at_for_display("2026-07-21T09:33:07.203970+00:00") == "2026-07-21 17:33:07"


def test_created_at_for_display_preserves_unknown_value() -> None:
    assert _created_at_for_display("unknown") == "unknown"
