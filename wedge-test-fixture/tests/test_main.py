"""Tests for the example module run by ``wedge run``."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from main import apply_discount, create_item, format_item


def test_create_item_basic():
    item = create_item("widget", 9.99, qty=3)
    assert item["name"] == "widget"
    assert item["price"] == 9.99
    assert item["qty"] == 3
    assert item["total"] == 29.97


def test_create_item_default_qty():
    item = create_item("gizmo", 5.0)
    assert item["qty"] == 1
    assert item["total"] == 5.0


def test_apply_discount():
    item = create_item("widget", 10.0, qty=2)  # total = 20.0
    discounted = apply_discount(item, 25)
    assert discounted["total"] == 15.0


def test_apply_discount_zero_and_full():
    item = create_item("widget", 10.0)
    assert apply_discount(item, 0)["total"] == 10.0
    assert apply_discount(item, 100)["total"] == 0.0


def test_apply_discount_invalid():
    import pytest
    with pytest.raises(ValueError):
        apply_discount(create_item("x", 1.0), 150)


def test_format_item():
    item = create_item("widget", 9.99, qty=2)
    assert format_item(item) == "widget: 2 x $9.99 = $19.98"
