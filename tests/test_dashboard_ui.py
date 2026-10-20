"""Structural assertions over the exact bytes the dashboard serves.

These are cheap and CI-safe: they read the shipped strings, not a browser. The
browser-level verification lives in ``scripts/dashboard_audit.py``, which is a
development harness and not a test dependency.

Assertions for a feature that has not landed yet carry ``@pending("Task N")``:
an xfail that keeps CI green and flips to a pass when the task lands. Every
task removes the marker for its own assertions.
"""
from __future__ import annotations

import pytest

from backstop.dashboard_ui import APP_CSS, APP_JS, PAGE_HTML


def js() -> str:
    return APP_JS


def css() -> str:
    return APP_CSS


def page() -> str:
    return PAGE_HTML


def pending(task: str):
    """Mark an assertion whose feature lands in a later task."""
    return pytest.mark.xfail(reason="lands in " + task, strict=False)


def test_the_page_loads_no_external_origin():
    assert "http://" not in page()
    assert "https://" not in page()
    assert "@import" not in css()


def test_the_removed_compact_formatter_is_not_used():
    assert "function compact(" not in js()
    assert "compact(" not in js()


def test_the_axis_uses_a_nice_scale_not_max_over_four():
    assert "function niceScale(" in js()
    assert "maxV / 4" not in js()


def test_one_formatter_per_quantity():
    for name in ("count(", "axis(", "rate(", "usd(", "ms(", "dur(", "pct("):
        assert "function " + name in js()
    assert "function compact(" not in js()
    assert "compact(" not in js()


def test_the_traffic_chart_has_no_ad_hoc_formatter():
    assert "yFormat: function" not in js()


def test_nice_scale_produces_round_steps():
    # The scale must land on 1/2/5/10 x 10^n.
    assert "step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10" in js()


def test_the_refresh_control_can_be_turned_off():
    assert '<option value="0">off</option>' in page()


def test_the_window_control_exists():
    assert 'id="window"' in page()


def test_the_window_control_offers_ranges():
    assert 'id="window"' in page()
    for label in ("1m", "5m", "15m", "all"):
        assert ">%s</option>" % label in page()


def test_the_connection_state_has_a_text_label():
    assert 'id="conn-label"' in page()


def test_the_updated_element_is_not_a_live_region():
    # Continuous aria-live announcements are a WCAG 2.2.2 / screen-reader bug:
    # the text changes every second, so the region must not be live.
    assert 'id="updated" role="status"' not in page()
    assert 'aria-live="polite"' in page()


def test_the_axis_is_wall_clock_not_relative():
    assert "function absoluteTimes(" in js()
    assert "rel(" not in js()


def test_the_refresh_can_be_paused():
    assert '<option value="0">off</option>' in page()
    assert "paused" in js()


def test_the_live_region_is_only_written_on_a_transition():
    assert "function announce(" in js()


def test_every_tile_has_a_status_token_slot():
    assert page().count('data-slot="status"') == 7


def test_the_dead_provider_column_is_gone():
    assert "<th>Provider</th>" not in page()
    assert "row.provider" not in js()


def test_tiles_carry_a_status_token():
    assert "STATUS_TOKEN" in js()


def test_panels_do_not_stretch_to_the_tallest():
    assert "align-items: start" in css()


def test_the_sparkline_fills_the_tile():
    assert ".tile .spark" in css()
    assert "flex: 1" in css()


def test_the_sessions_table_has_no_dead_provider_column():
    assert "<th>Provider</th>" not in page()


def test_tables_have_keyboard_row_navigation():
    assert "function tableKeyNav(" in js()
    for key in ("ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "Home", "End"):
        assert '"%s"' % key in js()


def test_tiles_show_a_change_against_the_previous_window():
    assert "function delta(" in js()
    assert "vs prev" in js()


def test_enforcement_events_are_annotated_on_the_chart():
    assert "function eventMarks(" in js()
    assert "spec.marks" in js()


def test_warnings_are_a_compact_strip():
    assert 'id="attention"' in page()


@pending("Task 6")
def test_tiles_are_drillable():
    assert 'role="button"' in page()
    assert 'tabindex="0"' in page()
    assert "function applyFilter(" in js()


@pending("Task 6")
def test_the_active_filter_is_visible_and_dismissable():
    assert 'id="filter-chip"' in page()
    assert "clearFilter" in js()


@pending("Task 7")
def test_canvases_declare_a_text_alternative():
    assert 'role="img"' in page()
    assert "aria-label" in js()


@pending("Task 7")
def test_the_tooltip_can_be_dismissed_with_escape():
    assert '"Escape"' in js()


@pending("Task 7")
def test_charts_have_a_text_alternative():
    assert "function chartSummary(" in js()
    assert "function renderChartTable(" in js()


@pending("Task 7")
def test_the_tooltip_is_dismissible_and_hoverable():
    assert '"Escape"' in js()
    assert "pointer-events: auto" in css()


@pending("Task 7")
def test_the_chart_can_be_read_as_a_table():
    assert "chart-toggle" in page()


@pending("Task 8")
def test_no_data_is_distinct_from_zero():
    assert "NO DATA" in js()
    assert "nothing blocked yet" in js()


@pending("Task 8")
def test_a_sparkline_without_points_draws_a_baseline():
    assert "no data" in js()
