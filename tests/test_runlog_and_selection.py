from datetime import UTC, date, datetime

import pytest

from tracker.core.config import SourceConfig, SourcesConfig
from tracker.core.runlog import run_status
from tracker.core.timeutil import dhaka_date
from tracker.orchestrator import select_sources


@pytest.mark.parametrize(
    ("ok", "failed", "expected"),
    [
        ([], [], "ok"),
        (["a"], [], "ok"),
        (["a"], ["b"], "partial"),
        ([], ["b"], "failed"),
    ],
)
def test_run_status(ok: list[str], failed: list[str], expected: str) -> None:
    assert run_status(ok, failed) == expected


CONFIG = SourcesConfig(
    sources={
        "b": SourceConfig(enabled=True),
        "off": SourceConfig(enabled=False),
        "a": SourceConfig(enabled=True),
    }
)


def test_selects_enabled_sources_in_yaml_order() -> None:
    assert select_sources(CONFIG, None) == ["b", "a"]


def test_explicit_selection_can_run_a_disabled_source() -> None:
    assert select_sources(CONFIG, ["off"]) == ["off"]


def test_unknown_source_is_rejected() -> None:
    with pytest.raises(SystemExit, match="nope"):
        select_sources(CONFIG, ["nope"])


def test_dhaka_date_differs_from_utc_date_after_midnight_dhaka() -> None:
    # 19:30 UTC on 23 Nov is 01:30 on 24 Nov in Dhaka (UTC+6).
    assert dhaka_date(datetime(2026, 11, 23, 19, 30, tzinfo=UTC)) == date(2026, 11, 24)
