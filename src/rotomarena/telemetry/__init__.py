"""Telemetry, breadcrumbs, replays, and reporting package."""

from rotomarena.telemetry.breadcrumbs import (
    BreadcrumbsRecorder,
    MatchTelemetry,
    TurnBreadcrumb,
)
from rotomarena.telemetry.replay_saver import (
    save_battle_raw_json,
    save_battle_replay_html,
)
from rotomarena.telemetry.reporter import generate_match_markdown_report

__all__ = [
    "BreadcrumbsRecorder",
    "MatchTelemetry",
    "TurnBreadcrumb",
    "save_battle_raw_json",
    "save_battle_replay_html",
    "generate_match_markdown_report",
]
