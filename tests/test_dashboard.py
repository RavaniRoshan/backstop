from __future__ import annotations

from backstop.dashboard import DASHBOARD_JSON, get_dashboard


def test_dashboard_has_required_top_level_keys():
    d = get_dashboard()
    assert d["uid"] == "backstop-overview"
    assert d["title"] == "Backstop Overview"
    assert "panels" in d
    assert len(d["panels"]) >= 6


def test_dashboard_panel_count_is_stable():
    d = DASHBOARD_JSON
    assert len(d["panels"]) == 8


def test_dashboard_panel_ids_unique():
    ids = [p["id"] for p in get_dashboard()["panels"]]
    assert len(ids) == len(set(ids))


def test_dashboard_promql_targets_use_backstop_prefix():
    panel = next(p for p in get_dashboard()["panels"] if p["id"] == 1)
    targets = panel["targets"]
    for t in targets:
        assert "backstop_" in t["expr"]


def test_dashboard_json_is_serializable():
    import json

    d = get_dashboard()
    out = json.dumps(d)
    parsed = json.loads(out)
    assert parsed["uid"] == "backstop-overview"
