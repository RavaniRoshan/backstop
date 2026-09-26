"""Tests for the ledger's price catalog and cost arithmetic.

The properties under test are the ones the ledger's finance claims rest on: an
exact figure to the sixth decimal place, a total that equals its parts, money
that is never a binary float, a missing price that stays visible, and a
precedence order where no lower tier quietly beats a higher one. The import
tests pin the no-I/O-at-import rule, which is the reason the bundled table is a
literal.
"""
from __future__ import annotations

import decimal
import json
import os
import re
import subprocess
import sys
import textwrap
from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

import backstop.pricing_catalog as pricing_catalog
from backstop.ledger import Attribution, SpendEvent
from backstop.pricing_catalog import (
    BUNDLED_PRICES,
    COST_COMPONENTS,
    PRICE_SOURCES,
    CostBreakdown,
    PriceCatalog,
    PriceEntry,
    compute_cost,
    model_candidates,
)


def make_event(**overrides) -> SpendEvent:
    """Build a valid event; ``overrides`` replaces individual fields."""
    fields = {
        "provider": "anthropic",
        "model": "claude-sonnet-4-5",
        "endpoint": "/v1/messages",
        "priority": "default",
        "outcome": "success",
        "input_tokens": 10_000,
        "output_tokens": 2_000,
        "estimated": False,
        "attribution": Attribution(team="payments"),
    }
    fields.update(overrides)
    return SpendEvent(**fields)


def user_entry(
    model: str,
    provider: str,
    input_rate: str,
    output_rate: str,
    cache_read: str | None = None,
    cache_write: str | None = None,
    effective_from: str = "2026-10-01",
) -> PriceEntry:
    return PriceEntry(
        model=model,
        provider=provider,
        input_per_mtok_usd=Decimal(input_rate),
        output_per_mtok_usd=Decimal(output_rate),
        cache_read_per_mtok_usd=None if cache_read is None else Decimal(cache_read),
        cache_write_per_mtok_usd=None if cache_write is None else Decimal(cache_write),
        effective_from=effective_from,
        source="user",
        confidence="negotiated",
    )


def write_catalog(tmp_path, document, name: str = "prices.json") -> str:
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return str(path)


USER_DOCUMENT = {
    "effective_from": "2026-10-01",
    "entries": [
        {
            "model": "claude-sonnet-4-5",
            "provider": "anthropic",
            "input_per_mtok_usd": "2.10",
            "output_per_mtok_usd": "10.50",
            "cache_read_per_mtok_usd": "0.21",
            "cache_write_per_mtok_usd": "2.63",
        },
        {
            "model": "house-model",
            "provider": "anthropic",
            "input_per_mtok_usd": "1.00",
            "output_per_mtok_usd": "2.00",
        },
    ],
}


# ---------------------------------------------------------------------------
# The bundled table
# ---------------------------------------------------------------------------


def test_the_bundled_table_is_immutable_and_carries_its_own_provenance():
    with pytest.raises(TypeError):
        BUNDLED_PRICES["gpt-4o"] = None  # type: ignore[index]
    for entry in BUNDLED_PRICES.values():
        assert entry.source == "bundled"
        assert entry.confidence == "list"
        assert entry.effective_from == pricing_catalog.BUNDLED_EFFECTIVE_FROM


def test_every_bundled_row_names_its_provider_and_carries_decimals():
    for model, entry in BUNDLED_PRICES.items():
        assert entry.model == model
        assert entry.provider in ("openai", "anthropic")
        assert isinstance(entry.input_per_mtok_usd, Decimal)
        assert isinstance(entry.output_per_mtok_usd, Decimal)
        assert entry.input_per_mtok_usd >= 0
        assert entry.output_per_mtok_usd > 0


def test_the_bundled_table_covers_the_models_this_repo_already_references():
    # Every key in the pre-existing backstop.pricing.DEFAULT_TABLE, which is the
    # set of models the repo already names.
    from backstop.pricing import DEFAULT_TABLE

    missing = sorted(set(DEFAULT_TABLE) - set(BUNDLED_PRICES))
    assert missing == []


def test_a_zero_price_is_never_recorded_where_the_publisher_has_none():
    # gpt-4o publishes no cache-write rate, so the field is absent rather than
    # 0.00: "not priced" and "free" are different claims.
    gpt_4o = BUNDLED_PRICES["gpt-4o"]
    assert gpt_4o.cache_read_per_mtok_usd == Decimal("1.25")
    assert gpt_4o.cache_write_per_mtok_usd is None


def test_importing_the_module_opens_no_socket():
    # In a subprocess, with socket.socket replaced by a subclass that raises on
    # construction and with the two connect entry points replaced outright. A
    # subclass rather than a function because ssl subclasses socket.socket at
    # import time, and a function there breaks the import for the wrong reason.
    script = textwrap.dedent(
        """
        import socket

        class _NoSocket(socket.socket):
            def __init__(self, *args, **kwargs):
                raise AssertionError("a socket was created at import")

        def _refuse(*args, **kwargs):
            raise AssertionError("the network was reached at import")

        socket.socket = _NoSocket
        socket.create_connection = _refuse
        socket.getaddrinfo = _refuse

        import backstop.pricing_catalog as module

        print("ok", len(module.BUNDLED_PRICES))
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.startswith("ok ")
    assert int(completed.stdout.split()[1]) == len(BUNDLED_PRICES)


def test_importing_the_module_reads_no_data_file():
    # The module is loaded from its own path rather than through
    # ``import backstop.pricing_catalog``, because importing the package runs
    # ``backstop/__init__.py``, which imports ``backstop.cost``, which imports
    # the pre-existing ``backstop.pricing`` -- and that one reads
    # ~/.cache/backstop/pricing.json at import. That is a real file read, and
    # it is not this module's. Loading the file directly measures this module's
    # own import cost and nothing else: every path the audit hook records must
    # be a Python source or bytecode file.
    script = textwrap.dedent(
        """
        import importlib.util
        import sys

        opened = []
        sys.addaudithook(
            lambda event, args: opened.append(str(args[0])) if event == "open" else None
        )

        name = "_pricing_catalog_under_test"
        spec = importlib.util.spec_from_file_location(name, sys.argv[1])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)

        print("ok", len(module.BUNDLED_PRICES))
        for path in opened:
            print("OPEN", path)
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script, pricing_catalog.__file__],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    lines = completed.stdout.splitlines()
    assert lines[0].startswith("ok ")
    offenders = [
        line for line in lines[1:] if not line.endswith((".py", ".pyc", ".so", ".pyd"))
    ]
    assert offenders == []


# ---------------------------------------------------------------------------
# PriceEntry validation
# ---------------------------------------------------------------------------


def test_a_price_entry_is_frozen():
    entry = BUNDLED_PRICES["gpt-4o"]
    with pytest.raises(FrozenInstanceError):
        entry.input_per_mtok_usd = Decimal("1")  # type: ignore[misc]


def test_a_price_refuses_a_binary_float():
    with pytest.raises(TypeError, match="input_per_mtok_usd"):
        PriceEntry(
            model="m",
            provider="openai",
            input_per_mtok_usd=2.5,  # type: ignore[arg-type]
            output_per_mtok_usd=Decimal("10"),
            cache_read_per_mtok_usd=None,
            cache_write_per_mtok_usd=None,
            effective_from="2026-10-01",
            source="user",
            confidence="negotiated",
        )


def test_a_price_refuses_a_negative_rate():
    with pytest.raises(ValueError, match=">= 0"):
        user_entry("m", "openai", "-0.01", "10")


def test_a_negative_cache_rate_is_refused_too():
    with pytest.raises(ValueError, match="cache_read_per_mtok_usd"):
        user_entry("m", "openai", "1", "2", cache_read="-0.5")


def test_an_input_price_may_not_be_none():
    with pytest.raises(ValueError, match="input_per_mtok_usd"):
        PriceEntry(
            model="m",
            provider="openai",
            input_per_mtok_usd=None,  # type: ignore[arg-type]
            output_per_mtok_usd=Decimal("1"),
            cache_read_per_mtok_usd=None,
            cache_write_per_mtok_usd=None,
            effective_from="2026-10-01",
            source="user",
            confidence="negotiated",
        )


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "sNaN"])
def test_a_price_must_be_finite(bad):
    with pytest.raises(ValueError):
        user_entry("m", "openai", bad, "10")


@pytest.mark.parametrize(
    "effective_from", ["2026-13-01", "2026-02-30", "20261001", "yesterday", ""]
)
def test_an_effective_from_must_be_a_real_iso_date(effective_from):
    with pytest.raises(ValueError, match="effective_from"):
        user_entry("m", "openai", "1", "2", effective_from=effective_from)


def test_an_effective_from_must_be_a_string():
    with pytest.raises(TypeError, match="effective_from"):
        user_entry("m", "openai", "1", "2", effective_from=20261001)  # type: ignore[arg-type]


@pytest.mark.parametrize("field,value", [("source", "internet"), ("confidence", "guess")])
def test_source_and_confidence_come_from_a_closed_set(field, value):
    kwargs = {
        "model": "m",
        "provider": "openai",
        "input_per_mtok_usd": Decimal("1"),
        "output_per_mtok_usd": Decimal("2"),
        "cache_read_per_mtok_usd": None,
        "cache_write_per_mtok_usd": None,
        "effective_from": "2026-10-01",
        "source": "user",
        "confidence": "negotiated",
    }
    kwargs[field] = value
    with pytest.raises(ValueError, match=field):
        PriceEntry(**kwargs)


@pytest.mark.parametrize("field", ["model", "provider"])
def test_a_price_needs_a_non_empty_model_and_provider(field):
    kwargs = {
        "model": "m",
        "provider": "openai",
        "input_per_mtok_usd": Decimal("1"),
        "output_per_mtok_usd": Decimal("2"),
        "cache_read_per_mtok_usd": None,
        "cache_write_per_mtok_usd": None,
        "effective_from": "2026-10-01",
        "source": "user",
        "confidence": "negotiated",
    }
    with pytest.raises((TypeError, ValueError), match=field):
        PriceEntry(**{**kwargs, field: "  "})


# ---------------------------------------------------------------------------
# Model name normalisation, tier by tier
# ---------------------------------------------------------------------------


def test_tier_one_is_the_name_exactly_as_reported():
    assert model_candidates("gpt-4o")[0] == "gpt-4o"
    assert PriceCatalog().resolve("openai", "gpt-4o") is BUNDLED_PRICES["gpt-4o"]


def test_tier_one_wins_over_a_looser_tier():
    # The user priced the exact string the provider reports; the bundled family
    # price would match only after the date stamp is stripped. Exact wins.
    exact = user_entry("gpt-4o-2024-08-06", "openai", "9.99", "9.99")
    catalog = PriceCatalog({"gpt-4o-2024-08-06": exact})
    assert catalog.resolve("openai", "gpt-4o-2024-08-06") is exact


def test_tier_two_strips_an_openai_date_stamp():
    assert model_candidates("gpt-4o-2024-08-06") == ("gpt-4o-2024-08-06", "gpt-4o")
    assert PriceCatalog().resolve("openai", "gpt-4o-2024-08-06") is BUNDLED_PRICES["gpt-4o"]


def test_tier_two_strips_an_anthropic_date_stamp():
    catalog = PriceCatalog(include_bundled=False)
    # "claude-3-5-sonnet" is not a key; its dated snapshot is not a candidate
    # either, so an unpriced Anthropic snapshot proves nothing. Use o1 instead.
    assert model_candidates("o1-2024-12-17") == ("o1-2024-12-17", "o1")
    assert PriceCatalog().resolve("openai", "o1-2024-12-17") is BUNDLED_PRICES["o1"]
    assert catalog.resolve("openai", "o1-2024-12-17") is None


def test_tier_two_strips_a_latest_marker():
    assert model_candidates("gpt-4o-latest") == ("gpt-4o-latest", "gpt-4o")
    assert PriceCatalog().resolve("openai", "gpt-4o-latest") is BUNDLED_PRICES["gpt-4o"]


def test_tier_two_strips_more_than_one_marker():
    assert model_candidates("gpt-4o-latest-2024-08-06") == (
        "gpt-4o-latest-2024-08-06",
        "gpt-4o-latest",
        "gpt-4o",
    )


def test_tier_three_resolves_an_undated_family_name():
    assert model_candidates("claude-3-5-sonnet") == (
        "claude-3-5-sonnet",
        "claude-3-5-sonnet-20241022",
    )
    assert (
        PriceCatalog().resolve("anthropic", "claude-3-5-sonnet")
        is BUNDLED_PRICES["claude-3-5-sonnet-20241022"]
    )


def test_tier_three_resolves_the_dotted_spelling():
    assert model_candidates("claude-3.5-sonnet") == (
        "claude-3.5-sonnet",
        "claude-3-5-sonnet-20241022",
    )
    assert (
        PriceCatalog().resolve("anthropic", "claude-3.5-sonnet")
        is BUNDLED_PRICES["claude-3-5-sonnet-20241022"]
    )


def test_the_three_tiers_compose():
    # "claude-3-5-sonnet-latest" is tier 2 stripping -latest, then tier 3 aliasing
    # the family name onto its launch snapshot.
    assert model_candidates("claude-3-5-sonnet-latest") == (
        "claude-3-5-sonnet-latest",
        "claude-3-5-sonnet",
        "claude-3-5-sonnet-20241022",
    )
    assert (
        PriceCatalog().resolve("anthropic", "claude-3-5-sonnet-latest")
        is BUNDLED_PRICES["claude-3-5-sonnet-20241022"]
    )


def test_an_alias_never_shadows_a_name_that_is_itself_a_key():
    # claude-3-5-sonnet-20241022 is its own alias target, so it is offered once.
    candidates = model_candidates("claude-3-5-sonnet-20241022")
    assert candidates == ("claude-3-5-sonnet-20241022", "claude-3-5-sonnet")
    assert len(set(candidates)) == len(candidates)


def test_a_normalisation_candidate_is_never_offered_twice():
    for name in ("gpt-4o", "gpt-4o-latest", "claude-3.5-haiku", "o1-2024-12-17"):
        candidates = model_candidates(name)
        assert len(set(candidates)) == len(candidates), name


def test_an_unknown_model_stays_unknown_however_it_is_spelled():
    catalog = PriceCatalog()
    for name in ("house-model", "gpt-9-ultra", "gpt-9-ultra-latest", "claude-99"):
        assert catalog.resolve("openai", name) is None, name


def test_the_same_name_on_the_wrong_provider_is_unknown():
    assert PriceCatalog().resolve("anthropic", "gpt-4o") is None
    assert PriceCatalog().resolve("openai", "claude-sonnet-4-5") is None


def test_resolve_refuses_a_non_string_argument():
    with pytest.raises(TypeError, match="provider"):
        PriceCatalog().resolve(None, "gpt-4o")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="model"):
        PriceCatalog().resolve("openai", 4)  # type: ignore[arg-type]


def test_the_hot_path_reuses_one_reduction_and_compiles_nothing_new():
    # compute_cost runs once per request, so the reduction is cached and both
    # patterns are compiled at import rather than per call.
    assert isinstance(pricing_catalog._SNAPSHOT_SUFFIX_RE, re.Pattern)
    first = model_candidates("gpt-4o-2024-08-06")
    assert model_candidates("gpt-4o-2024-08-06") is first

    cache = getattr(re, "_cache", None)
    if cache is None:  # pragma: no cover - re._cache has existed since 3.2
        pytest.skip("re._cache is not available to measure compilation")
    known = set(cache)
    for index in range(50):
        assert compute_cost(make_event(model=f"never-seen-model-{index}"), PriceCatalog()) is None
    assert set(cache) == known


# ---------------------------------------------------------------------------
# The catalog
# ---------------------------------------------------------------------------


def test_a_catalog_key_must_name_the_entry_it_holds():
    with pytest.raises(ValueError, match="does not match"):
        PriceCatalog({"gpt-4o": user_entry("gpt-4o-mini", "openai", "1", "2")})


def test_a_catalog_holds_price_entries():
    with pytest.raises(TypeError, match="PriceEntry"):
        PriceCatalog({"gpt-4o": {"input_per_mtok_usd": "1"}})  # type: ignore[dict-item]


def test_the_bundled_table_can_be_left_out():
    entry = user_entry("house-model", "anthropic", "1.00", "2.00")
    catalog = PriceCatalog({"house-model": entry}, include_bundled=False)
    assert catalog.resolve("openai", "gpt-4o") is None
    assert catalog.resolve("anthropic", "house-model") is entry


# ---------------------------------------------------------------------------
# Precedence
# ---------------------------------------------------------------------------


def test_the_bundled_table_prices_by_default():
    cost = compute_cost(make_event(), PriceCatalog())
    assert cost is not None
    assert cost.price_source == "bundled"


def test_a_user_catalog_file_outranks_the_bundled_table(tmp_path):
    catalog = PriceCatalog.from_file(write_catalog(tmp_path, USER_DOCUMENT))
    cost = compute_cost(make_event(), catalog)
    assert cost is not None
    assert cost.price_source == "user"
    # 10,000 input at the file's 2.10 rather than the bundled 3.00.
    assert cost.input_usd == Decimal("0.021000")


def test_a_per_call_override_outranks_the_user_catalog_file(tmp_path):
    catalog = PriceCatalog.from_file(write_catalog(tmp_path, USER_DOCUMENT))
    overrides = {
        "claude-sonnet-4-5": {
            "effective_from": "2026-11-01",
            "input_per_mtok_usd": "1.00",
            "output_per_mtok_usd": "2.00",
        }
    }
    cost = compute_cost(make_event(), catalog, price_overrides=overrides)
    assert cost is not None
    assert cost.price_source == "override"
    assert cost.input_usd == Decimal("0.010000")


def test_no_lower_tier_beats_a_higher_one(tmp_path):
    """All three tiers priced for one model; each winner is the highest."""
    catalog = PriceCatalog.from_file(write_catalog(tmp_path, USER_DOCUMENT))
    user_cost = compute_cost(make_event(), catalog)
    override_cost = compute_cost(
        make_event(),
        catalog,
        price_overrides={
            "claude-sonnet-4-5": {
                "effective_from": "2026-11-01",
                "input_per_mtok_usd": "1.00",
                "output_per_mtok_usd": "2.00",
            }
        },
    )
    bundled_cost = compute_cost(make_event(), PriceCatalog())

    assert (user_cost.input_usd, override_cost.input_usd, bundled_cost.input_usd) == (
        Decimal("0.021000"),
        Decimal("0.010000"),
        Decimal("0.030000"),
    )
    assert override_cost.input_usd < user_cost.input_usd < bundled_cost.input_usd


def test_the_user_layer_is_searched_across_every_tier_before_the_bundled_one(tmp_path):
    # The file prices the family name, not the dated snapshot the provider
    # reports. The user's layer still wins, because it is the higher one.
    document = {
        "entries": [
            {
                "model": "gpt-4o",
                "provider": "openai",
                "effective_from": "2026-10-01",
                "input_per_mtok_usd": "0.50",
                "output_per_mtok_usd": "1.00",
            }
        ]
    }
    catalog = PriceCatalog.from_file(write_catalog(tmp_path, document))
    cost = compute_cost(make_event(provider="openai", model="gpt-4o-2024-08-06"), catalog)
    assert cost is not None
    assert cost.price_source == "user"
    # 10,000 tokens at the file's 0.50 rather than the bundled 2.50.
    assert cost.input_usd == Decimal("0.005000")


def test_an_override_key_goes_through_the_same_normalisation():
    overrides = {
        "gpt-4o": {
            "effective_from": "2026-11-01",
            "input_per_mtok_usd": "1.00",
            "output_per_mtok_usd": "2.00",
        }
    }
    cost = compute_cost(
        make_event(provider="openai", model="gpt-4o-2024-08-06"),
        PriceCatalog(),
        price_overrides=overrides,
    )
    assert cost is not None
    assert cost.price_source == "override"


def test_an_override_may_be_a_ready_made_entry():
    entry = user_entry("gpt-4o", "openai", "1.00", "2.00", cache_read="0.50")
    cost = compute_cost(
        make_event(provider="openai", model="gpt-4o", cache_read_tokens=1_000_000),
        PriceCatalog(),
        price_overrides={"gpt-4o": entry},
    )
    assert cost is not None
    assert cost.price_source == "override"
    assert cost.cache_read_usd == Decimal("0.500000")


def test_an_override_for_the_wrong_provider_is_refused():
    entry = user_entry("gpt-4o", "anthropic", "1.00", "2.00")
    with pytest.raises(ValueError, match="provider"):
        compute_cost(
            make_event(provider="openai", model="gpt-4o"),
            PriceCatalog(),
            price_overrides={"gpt-4o": entry},
        )


def test_an_override_must_say_when_it_took_effect():
    with pytest.raises(ValueError, match="effective_from"):
        compute_cost(
            make_event(),
            PriceCatalog(),
            price_overrides={
                "claude-sonnet-4-5": {
                    "input_per_mtok_usd": "1.00",
                    "output_per_mtok_usd": "2.00",
                }
            },
        )


def test_an_override_with_a_stray_key_names_it():
    with pytest.raises(ValueError, match="input_per_mtoks"):
        compute_cost(
            make_event(),
            PriceCatalog(),
            price_overrides={
                "claude-sonnet-4-5": {
                    "effective_from": "2026-11-01",
                    "input_per_mtok_usd": "1.00",
                    "output_per_mtok_usd": "2.00",
                    "input_per_mtoks": "1.00",
                }
            },
        )


def test_compute_cost_refuses_a_thing_that_is_not_a_catalog():
    with pytest.raises(TypeError, match="PriceCatalog"):
        compute_cost(make_event(), {"gpt-4o": BUNDLED_PRICES["gpt-4o"]})  # type: ignore[arg-type]


def test_compute_cost_refuses_overrides_that_are_not_a_mapping():
    with pytest.raises(TypeError, match="price_overrides"):
        compute_cost(
            make_event(),
            PriceCatalog(),
            price_overrides=[("gpt-4o", 1)],  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# compute_cost: exactness
# ---------------------------------------------------------------------------


def test_a_known_model_and_known_usage_price_to_the_sixth_decimal_place():
    # claude-sonnet-4-5: 3.00 in, 15.00 out, 0.30 cache read, 3.75 cache write.
    # 10,000 * 3.00 = 0.030000; 2,000 * 15.00 = 0.030000;
    # 50,000 * 0.30 = 0.015000; 4,000 * 3.75 = 0.015000.
    cost = compute_cost(
        make_event(
            input_tokens=10_000,
            output_tokens=2_000,
            cache_read_tokens=50_000,
            cache_write_tokens=4_000,
        ),
        PriceCatalog(),
    )
    assert cost is not None
    assert cost.input_usd == Decimal("0.030000")
    assert cost.output_usd == Decimal("0.030000")
    assert cost.cache_read_usd == Decimal("0.015000")
    assert cost.cache_write_usd == Decimal("0.015000")
    assert cost.total_usd == Decimal("0.090000")
    assert cost.currency == "USD"
    assert cost.estimated_tokens is False
    assert cost.priced_components == frozenset(COST_COMPONENTS)


def test_a_second_known_model_agrees_with_its_own_arithmetic():
    # gpt-4o: 2.50 in, 10.00 out, 1.25 cache read, no published cache-write rate.
    # 1,234 * 2.50 = 0.003085; 567 * 10.00 = 0.005670; 8,000 * 1.25 = 0.010000.
    cost = compute_cost(
        make_event(
            provider="openai",
            model="gpt-4o",
            input_tokens=1_234,
            output_tokens=567,
            cache_read_tokens=8_000,
            cache_write_tokens=900,
        ),
        PriceCatalog(),
    )
    assert cost is not None
    assert cost.input_usd == Decimal("0.003085")
    assert cost.output_usd == Decimal("0.005670")
    assert cost.cache_read_usd == Decimal("0.010000")
    assert cost.cache_write_usd == Decimal("0.000000")
    assert cost.total_usd == Decimal("0.018755")


def test_the_total_is_the_sum_of_its_components():
    cost = compute_cost(
        make_event(
            input_tokens=9_999,
            output_tokens=1_001,
            cache_read_tokens=123_456,
            cache_write_tokens=7,
        ),
        PriceCatalog(),
    )
    assert cost is not None
    assert cost.total_usd == (
        cost.input_usd + cost.output_usd + cost.cache_read_usd + cost.cache_write_usd
    )


def test_every_amount_carries_exactly_six_decimal_places():
    cost = compute_cost(
        make_event(input_tokens=7, output_tokens=11, cache_read_tokens=13, cache_write_tokens=3),
        PriceCatalog(),
    )
    assert cost is not None
    for name in ("input_usd", "output_usd", "cache_read_usd", "cache_write_usd", "total_usd"):
        amount = getattr(cost, name)
        assert amount.as_tuple().exponent == -6, name


def test_half_a_microscopic_amount_rounds_up_and_not_to_even():
    # gpt-5.5's cache read is 0.50 per Mtok, so one token is 0.0000005 exactly.
    # ROUND_HALF_UP makes that 0.000001; ROUND_HALF_EVEN would make it 0.000000.
    cost = compute_cost(
        make_event(
            provider="openai",
            model="gpt-5.5",
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=1,
        ),
        PriceCatalog(),
    )
    assert cost is not None
    assert cost.cache_read_usd == Decimal("0.000001")
    assert cost.total_usd == Decimal("0.000001")


def test_an_amount_below_the_half_rounds_to_nothing():
    # gpt-4.1-mini's input is 0.40 per Mtok, so one token is 0.0000004.
    cost = compute_cost(
        make_event(provider="openai", model="gpt-4.1-mini", input_tokens=1, output_tokens=0),
        PriceCatalog(),
    )
    assert cost is not None
    assert cost.input_usd == Decimal("0.000000")


def test_a_request_with_no_tokens_costs_nothing():
    cost = compute_cost(
        make_event(input_tokens=0, output_tokens=0, cache_read_tokens=0, cache_write_tokens=0),
        PriceCatalog(),
    )
    assert cost is not None
    assert cost.total_usd == Decimal("0.000000")
    assert cost.priced_components == frozenset(COST_COMPONENTS)


def test_an_estimated_event_says_so_on_the_breakdown():
    cost = compute_cost(make_event(estimated=True), PriceCatalog())
    assert cost is not None
    assert cost.estimated_tokens is True


def test_pricing_the_same_inputs_twice_gives_the_same_breakdown():
    catalog = PriceCatalog()
    event = make_event(cache_read_tokens=1_234)
    assert compute_cost(event, catalog) == compute_cost(event, catalog)


def test_compute_cost_never_mutates_its_inputs():
    catalog = PriceCatalog()
    event = make_event()
    before_event = event.to_dict()
    before_prices = dict(BUNDLED_PRICES)
    compute_cost(event, catalog)
    assert event.to_dict() == before_event
    assert dict(BUNDLED_PRICES) == before_prices


# ---------------------------------------------------------------------------
# compute_cost: independence from the ambient decimal context
# ---------------------------------------------------------------------------
#
# A ``decimal`` context is PROCESS-GLOBAL. A host application that tightens
# ``prec`` — which accounting code does, to keep a float-heavy report tidy —
# used to void every cost this module computes: the request still returned 200,
# ``state.ledger_errors`` climbed once per event, and the ledger stayed empty.
# These tests install a hostile context and assert the exact figure, because a
# cost that is merely *approximately* right under a hostile context is the
# failure, not a smaller version of it.

#: The event both hostile-context tests price: four components, six decimal
#: places, and a total that needs more significant digits than ``prec=6`` allows.
#: claude-sonnet-4-5: 3.00 in, 15.00 out, 0.30 cache read, 3.75 cache write.
HOSTILE_CONTEXT_EVENT = {
    "input_tokens": 1_234_567,
    "output_tokens": 89_012,
    "cache_read_tokens": 400_000,
    "cache_write_tokens": 7_777,
}
# 1,234,567 * 3.00 = 3.703701; 89,012 * 15.00 = 1.335180;
# 400,000 * 0.30 = 0.120000; 7,777 * 3.75 = 0.02916375 -> 0.029164.
HOSTILE_CONTEXT_TOTAL = Decimal("5.188045")


def _hostile_event() -> SpendEvent:
    return make_event(**HOSTILE_CONTEXT_EVENT)


def test_a_tight_process_prec_does_not_change_or_break_a_cost(monkeypatch):
    """The reproduction: ``prec=6`` set by a host app before Backstop loads.

    Under the old arithmetic the divide and the quantise both ran at six
    significant digits, so ``quantize`` raised ``InvalidOperation`` on every
    event. The figure has to come out identical to the default context's, not
    merely be close to it.
    """
    context = decimal.getcontext()
    assert compute_cost(_hostile_event(), PriceCatalog()).total_usd == HOSTILE_CONTEXT_TOTAL
    monkeypatch.setattr(context, "prec", 6)

    cost = compute_cost(_hostile_event(), PriceCatalog())
    assert cost is not None
    assert cost.total_usd == HOSTILE_CONTEXT_TOTAL
    assert cost.input_usd == Decimal("3.703701")
    assert cost.output_usd == Decimal("1.335180")
    assert cost.cache_read_usd == Decimal("0.120000")
    assert cost.cache_write_usd == Decimal("0.029164")
    # The invariant, checked the way a caller would have to under a hostile
    # context: with the ledger's own context, because the sum below is itself
    # decimal arithmetic and would otherwise round at six digits.
    with decimal.localcontext(pricing_catalog.LEDGER_CONTEXT):
        assert cost.total_usd == (
            cost.input_usd + cost.output_usd + cost.cache_read_usd + cost.cache_write_usd
        )


def test_a_hostile_rounding_and_trap_set_does_not_change_a_cost(monkeypatch):
    """The other half of the same bug: a context that rounds the wrong way.

    ``ROUND_UP`` with ``Inexact`` and ``Rounded`` trapped would make every
    divide an exception under the old arithmetic, and a silent round-up without
    the traps. Neither may reach the ledger's money.
    """
    context = decimal.getcontext()
    monkeypatch.setattr(context, "prec", 2)
    monkeypatch.setattr(context, "rounding", decimal.ROUND_UP)
    monkeypatch.setitem(context.traps, decimal.Inexact, True)
    monkeypatch.setitem(context.traps, decimal.Rounded, True)
    monkeypatch.setattr(context, "Emax", 9)
    monkeypatch.setattr(context, "Emin", -9)

    cost = compute_cost(_hostile_event(), PriceCatalog())
    assert cost is not None
    assert cost.total_usd == HOSTILE_CONTEXT_TOTAL
    assert str(cost.total_usd) == "5.188045", "the rounding mode the host chose is not ours"


def test_the_ledger_context_is_the_28_digit_default_named_in_full():
    """The guarantee is unconditional, so the context cannot be a ``DefaultContext``.

    ``Context(...)`` copies every field it is not given from
    :data:`decimal.DefaultContext`, so a context that named only ``prec`` would
    still be reachable by a host that tightened the default's traps. Every field
    that can change a result is therefore written down.
    """
    context = pricing_catalog.LEDGER_CONTEXT
    assert context.prec == pricing_catalog.MONEY_PRECISION == 28
    assert context.rounding == decimal.ROUND_HALF_UP
    assert context.Emin == -999_999
    assert context.Emax == 999_999
    assert context.clamp == 0
    trapped = {signal for signal, on in context.traps.items() if on}
    assert trapped == {decimal.InvalidOperation, decimal.DivisionByZero, decimal.Overflow}


def test_pricing_leaves_the_ambient_context_exactly_as_it_found_it(monkeypatch):
    """The arithmetic is context-local, so a host's context survives a call.

    Setting a thread context and forgetting to put it back is how a library
    corrupts the process it was imported into; ``localcontext`` is the
    discipline that prevents it, and a priced event must not be the thing that
    changes a host's rounding mode.
    """
    context = decimal.getcontext()
    monkeypatch.setattr(context, "prec", 9)
    monkeypatch.setattr(context, "rounding", decimal.ROUND_DOWN)

    compute_cost(_hostile_event(), PriceCatalog())

    assert context.prec == 9
    assert context.rounding == decimal.ROUND_DOWN


# ---------------------------------------------------------------------------
# compute_cost: missing prices stay visible
# ---------------------------------------------------------------------------


def test_an_unknown_model_is_unpriced_rather_than_guessed():
    assert compute_cost(make_event(model="house-model"), PriceCatalog()) is None


def test_an_unknown_model_is_unpriced_however_it_is_spelled():
    for name in ("house-model", "house-model-2026-01-01", "house-model-latest", "house.model"):
        assert compute_cost(make_event(model=name), PriceCatalog()) is None, name


def test_a_known_model_on_an_unknown_provider_is_unpriced():
    event = make_event(provider="mistral", model="claude-sonnet-4-5")
    assert compute_cost(event, PriceCatalog()) is None


def test_an_empty_override_mapping_changes_nothing():
    assert compute_cost(make_event(), PriceCatalog(), price_overrides={}) == compute_cost(
        make_event(), PriceCatalog()
    )


# ---------------------------------------------------------------------------
# Cache component coverage
# ---------------------------------------------------------------------------


def test_a_component_with_no_published_rate_costs_zero_and_says_so():
    # gpt-4o publishes a cache-read rate but no cache-write rate, and this event
    # has cache-write tokens. They are charged zero and the breakdown records
    # that the price for them was never known, so an export can report the gap
    # instead of presenting a zero as a measurement.
    cost = compute_cost(
        make_event(
            provider="openai",
            model="gpt-4o",
            cache_read_tokens=1_000,
            cache_write_tokens=1_000,
        ),
        PriceCatalog(),
    )
    assert cost is not None
    assert cost.cache_write_usd == Decimal("0.000000")
    assert "cache_write" not in cost.priced_components
    assert cost.priced_components == frozenset({"input", "output", "cache_read"})


def test_coverage_describes_the_price_record_not_the_request():
    # gpt-4o publishes a cache-read rate, so a request's cache-read amount
    # moves with its token count while its coverage stays put.
    with_tokens = compute_cost(
        make_event(provider="openai", model="gpt-4o", cache_read_tokens=1_000_000),
        PriceCatalog(),
    )
    without = compute_cost(
        make_event(provider="openai", model="gpt-4o", cache_read_tokens=0), PriceCatalog()
    )
    assert with_tokens is not None and without is not None
    assert with_tokens.priced_components == without.priced_components
    assert with_tokens.cache_read_usd > without.cache_read_usd


def test_a_model_with_no_cache_prices_at_all_prices_only_input_and_output():
    # The Claude 3 generation is no longer on Anthropic's rate card, so its
    # prompt-cache rates are recorded as unpriced rather than carried forward.
    cost = compute_cost(
        make_event(
            model="claude-3-haiku-20240307",
            cache_read_tokens=1_000,
            cache_write_tokens=1_000,
        ),
        PriceCatalog(),
    )
    assert cost is not None
    assert cost.priced_components == frozenset({"input", "output"})
    assert cost.cache_read_usd == Decimal("0.000000")
    assert cost.cache_write_usd == Decimal("0.000000")
    assert cost.total_usd == cost.input_usd + cost.output_usd


def test_priced_components_is_accepted_as_a_plain_set():
    cost = compute_cost(make_event(), PriceCatalog())
    assert cost is not None
    assert CostBreakdown(
        input_usd=cost.input_usd,
        output_usd=cost.output_usd,
        cache_read_usd=cost.cache_read_usd,
        cache_write_usd=cost.cache_write_usd,
        total_usd=cost.total_usd,
        currency="USD",
        price_source="bundled",
        estimated_tokens=False,
        priced_components={"input", "output"},
    ).priced_components == frozenset({"input", "output"})


# ---------------------------------------------------------------------------
# CostBreakdown validation
# ---------------------------------------------------------------------------


def test_a_breakdown_is_frozen():
    cost = compute_cost(make_event(), PriceCatalog())
    assert cost is not None
    with pytest.raises(FrozenInstanceError):
        cost.total_usd = Decimal("1")  # type: ignore[misc]


def test_a_breakdown_refuses_a_binary_float():
    with pytest.raises(TypeError, match="input_usd"):
        CostBreakdown(
            input_usd=0.03,  # type: ignore[arg-type]
            output_usd=Decimal("0.03"),
            cache_read_usd=Decimal("0.01"),
            cache_write_usd=Decimal("0.01"),
            total_usd=Decimal("0.08"),
            currency="USD",
            price_source="bundled",
            estimated_tokens=False,
            priced_components=frozenset(COST_COMPONENTS),
        )


def test_a_breakdown_refuses_an_amount_that_is_not_written_to_six_places():
    with pytest.raises(ValueError, match="6 decimal places"):
        CostBreakdown(
            input_usd=Decimal("0.0300001"),
            output_usd=Decimal("0.03"),
            cache_read_usd=Decimal("0.01"),
            cache_write_usd=Decimal("0.01"),
            total_usd=Decimal("0.08"),
            currency="USD",
            price_source="bundled",
            estimated_tokens=False,
            priced_components=frozenset(COST_COMPONENTS),
        )


def test_a_breakdown_refuses_an_amount_written_coarser_than_six_places():
    # Coarser is a different wire form, not the same one: a line that says 0.03
    # would not compare equal to the 0.030000 this module writes.
    with pytest.raises(ValueError, match="6 decimal places"):
        CostBreakdown(
            input_usd=Decimal("0.03"),
            output_usd=Decimal("0.030000"),
            cache_read_usd=Decimal("0.010000"),
            cache_write_usd=Decimal("0.010000"),
            total_usd=Decimal("0.060000"),
            currency="USD",
            price_source="bundled",
            estimated_tokens=False,
            priced_components=frozenset(COST_COMPONENTS),
        )


def test_a_breakdown_refuses_a_negative_amount():
    with pytest.raises(ValueError, match=">= 0"):
        CostBreakdown(
            input_usd=Decimal("-0.030000"),
            output_usd=Decimal("0.030000"),
            cache_read_usd=Decimal("0.010000"),
            cache_write_usd=Decimal("0.010000"),
            total_usd=Decimal("0.080000"),
            currency="USD",
            price_source="bundled",
            estimated_tokens=False,
            priced_components=frozenset(COST_COMPONENTS),
        )


def test_a_breakdown_is_denominated_in_usd_only():
    kwargs = {
        "input_usd": Decimal("0.030000"),
        "output_usd": Decimal("0.030000"),
        "cache_read_usd": Decimal("0.010000"),
        "cache_write_usd": Decimal("0.010000"),
        "total_usd": Decimal("0.080000"),
        "currency": "USD",
        "price_source": "bundled",
        "estimated_tokens": False,
        "priced_components": frozenset(COST_COMPONENTS),
    }
    with pytest.raises(ValueError, match="currency"):
        CostBreakdown(**{**kwargs, "currency": "EUR"})


def test_a_breakdown_names_its_price_source_from_a_closed_set():
    assert PRICE_SOURCES == ("override", "user", "bundled")
    kwargs = {
        "input_usd": Decimal("0.030000"),
        "output_usd": Decimal("0.030000"),
        "cache_read_usd": Decimal("0.010000"),
        "cache_write_usd": Decimal("0.010000"),
        "total_usd": Decimal("0.080000"),
        "currency": "USD",
        "price_source": "bundled",
        "estimated_tokens": False,
        "priced_components": frozenset(COST_COMPONENTS),
    }
    with pytest.raises(ValueError, match="price_source"):
        CostBreakdown(**{**kwargs, "price_source": "list"})


def test_a_breakdown_refuses_a_component_that_is_not_a_component():
    kwargs = {
        "input_usd": Decimal("0.030000"),
        "output_usd": Decimal("0.030000"),
        "cache_read_usd": Decimal("0.010000"),
        "cache_write_usd": Decimal("0.010000"),
        "total_usd": Decimal("0.080000"),
        "currency": "USD",
        "price_source": "bundled",
        "estimated_tokens": False,
        "priced_components": frozenset(COST_COMPONENTS),
    }
    with pytest.raises(ValueError, match="cache_eviction"):
        CostBreakdown(**{**kwargs, "priced_components": frozenset({"input", "cache_eviction"})})


def test_a_breakdown_refuses_an_estimated_flag_that_is_not_a_bool():
    with pytest.raises(TypeError, match="estimated_tokens"):
        CostBreakdown(
            input_usd=Decimal("0.030000"),
            output_usd=Decimal("0.030000"),
            cache_read_usd=Decimal("0.010000"),
            cache_write_usd=Decimal("0.010000"),
            total_usd=Decimal("0.080000"),
            currency="USD",
            price_source="bundled",
            estimated_tokens="no",  # type: ignore[arg-type]
            priced_components=frozenset(COST_COMPONENTS),
        )


# ---------------------------------------------------------------------------
# The wire form
# ---------------------------------------------------------------------------


def test_every_amount_on_the_wire_is_a_string():
    cost = compute_cost(
        make_event(
            provider="openai",
            model="gpt-4o",
            input_tokens=1_234,
            output_tokens=567,
            cache_read_tokens=8_000,
        ),
        PriceCatalog(),
    )
    assert cost is not None
    wire = cost.to_dict()
    for name in ("input_usd", "output_usd", "cache_read_usd", "cache_write_usd", "total_usd"):
        assert isinstance(wire[name], str), name
    assert not any(isinstance(value, float) for value in wire.values())
    assert wire["total_usd"] == "0.018755"


def test_the_wire_form_says_money_in_quotes():
    # make_event() sends 10,000 input and 2,000 output to claude-sonnet-4-5 at
    # 3.00 and 15.00, with no cached tokens: 0.030000 + 0.030000.
    cost = compute_cost(make_event(), PriceCatalog())
    assert cost is not None
    line = json.dumps(cost.to_dict(), separators=(", ", ": "))
    assert '"total_usd": "0.060000"' in line
    assert '"total_usd": 0.06' not in line


def test_priced_components_travel_as_a_list_in_component_order():
    cost = compute_cost(make_event(provider="openai", model="gpt-4o"), PriceCatalog())
    assert cost is not None
    assert cost.to_dict()["priced_components"] == ["input", "output", "cache_read"]
    assert json.loads(json.dumps(cost.to_dict()))["priced_components"] == [
        "input",
        "output",
        "cache_read",
    ]


def test_a_breakdown_round_trips_through_its_own_wire_form():
    cost = compute_cost(make_event(), PriceCatalog())
    assert cost is not None
    assert CostBreakdown.from_dict(cost.to_dict()) == cost


def test_a_breakdown_round_trips_surviving_a_json_line():
    cost = compute_cost(make_event(), PriceCatalog())
    assert cost is not None
    reloaded = CostBreakdown.from_dict(json.loads(json.dumps(cost.to_dict())))
    assert reloaded == cost
    assert reloaded.to_dict() == cost.to_dict()


def test_from_dict_refuses_an_amount_that_arrived_as_a_json_number():
    cost = compute_cost(make_event(), PriceCatalog())
    assert cost is not None
    wire = cost.to_dict()
    wire["total_usd"] = 0.09
    with pytest.raises(TypeError, match="total_usd"):
        CostBreakdown.from_dict(wire)


@pytest.mark.parametrize("amount", [1, 1.5, True, None])
def test_from_dict_refuses_every_non_string_amount(amount):
    cost = compute_cost(make_event(), PriceCatalog())
    assert cost is not None
    wire = cost.to_dict()
    wire["input_usd"] = amount
    with pytest.raises(TypeError, match="input_usd"):
        CostBreakdown.from_dict(wire)


def test_from_dict_refuses_a_missing_field():
    cost = compute_cost(make_event(), PriceCatalog())
    assert cost is not None
    wire = cost.to_dict()
    del wire["cache_read_usd"]
    with pytest.raises(ValueError, match="cache_read_usd"):
        CostBreakdown.from_dict(wire)


def test_from_dict_refuses_an_undeclared_field():
    cost = compute_cost(make_event(), PriceCatalog())
    assert cost is not None
    wire = cost.to_dict()
    wire["cache_eviction_usd"] = "0.000000"
    with pytest.raises(ValueError, match="cache_eviction_usd"):
        CostBreakdown.from_dict(wire)


def test_from_dict_refuses_a_payload_that_is_not_a_mapping():
    with pytest.raises(TypeError, match="mapping"):
        CostBreakdown.from_dict("0.09")


def test_from_dict_refuses_a_repeated_component():
    cost = compute_cost(make_event(), PriceCatalog())
    assert cost is not None
    wire = cost.to_dict()
    wire["priced_components"] = ["input", "input"]
    with pytest.raises(ValueError, match="more than once"):
        CostBreakdown.from_dict(wire)


# ---------------------------------------------------------------------------
# A priced event round trips through SpendEvent
# ---------------------------------------------------------------------------


def test_a_priced_event_round_trips_through_its_wire_form_and_a_json_line():
    cost = compute_cost(
        make_event(
            provider="openai",
            model="gpt-4o",
            input_tokens=1_234,
            output_tokens=567,
            cache_read_tokens=8_000,
        ),
        PriceCatalog(),
    )
    assert cost is not None
    priced = SpendEvent(
        provider="openai",
        model="gpt-4o",
        endpoint="/v1/chat/completions",
        priority="default",
        outcome="success",
        input_tokens=1_234,
        output_tokens=567,
        cache_read_tokens=8_000,
        estimated=False,
        attribution=Attribution(team="payments"),
        cost=cost,
    )
    payload = priced.to_dict()
    assert SpendEvent.from_dict(payload) == priced
    assert SpendEvent.from_dict(json.loads(json.dumps(payload))) == priced
    line = json.dumps(payload)
    assert '"total_usd": "0.018755"' in line


def test_a_priced_event_keeps_its_breakdown_type_through_a_json_line():
    cost = compute_cost(make_event(), PriceCatalog())
    assert cost is not None
    payload = make_event(cost=cost).to_dict()
    reloaded = SpendEvent.from_dict(json.loads(json.dumps(payload)))
    assert reloaded.cost == cost
    assert type(reloaded.cost) is CostBreakdown
    assert isinstance(reloaded.cost.input_usd, Decimal)


# ---------------------------------------------------------------------------
# User catalog files
# ---------------------------------------------------------------------------


def test_a_user_catalog_file_loads(tmp_path):
    catalog = PriceCatalog.from_file(write_catalog(tmp_path, USER_DOCUMENT))
    entry = catalog.resolve("anthropic", "claude-sonnet-4-5")
    assert entry is not None
    assert entry.input_per_mtok_usd == Decimal("2.10")
    assert entry.output_per_mtok_usd == Decimal("10.50")
    assert entry.cache_read_per_mtok_usd == Decimal("0.21")
    assert entry.cache_write_per_mtok_usd == Decimal("2.63")
    assert entry.source == "user"
    assert entry.confidence == "negotiated"
    assert entry.effective_from == "2026-10-01"


def test_a_user_catalog_file_still_carries_the_bundled_table(tmp_path):
    catalog = PriceCatalog.from_file(write_catalog(tmp_path, USER_DOCUMENT))
    assert catalog.resolve("openai", "gpt-4o") is BUNDLED_PRICES["gpt-4o"]


def test_a_user_catalog_file_may_replace_the_bundled_table(tmp_path):
    catalog = PriceCatalog.from_file(
        write_catalog(tmp_path, USER_DOCUMENT), include_bundled=False
    )
    assert catalog.resolve("openai", "gpt-4o") is None
    assert catalog.resolve("anthropic", "claude-sonnet-4-5") is not None


def test_an_entry_inherits_the_file_level_effective_from(tmp_path):
    catalog = PriceCatalog.from_file(write_catalog(tmp_path, USER_DOCUMENT))
    entry = catalog.resolve("anthropic", "house-model")
    assert entry is not None
    assert entry.effective_from == "2026-10-01"


def test_an_entry_may_override_the_file_level_effective_from(tmp_path):
    document = {
        "effective_from": "2026-10-01",
        "entries": [
            {
                "model": "house-model",
                "provider": "anthropic",
                "effective_from": "2025-06-30",
                "input_per_mtok_usd": "1.00",
                "output_per_mtok_usd": "2.00",
            }
        ],
    }
    catalog = PriceCatalog.from_file(write_catalog(tmp_path, document))
    entry = catalog.resolve("anthropic", "house-model")
    assert entry is not None
    assert entry.effective_from == "2025-06-30"


def test_an_absent_cache_rate_is_recorded_as_unpriced_not_as_zero(tmp_path):
    catalog = PriceCatalog.from_file(write_catalog(tmp_path, USER_DOCUMENT))
    entry = catalog.resolve("anthropic", "house-model")
    assert entry is not None
    assert entry.cache_read_per_mtok_usd is None
    assert entry.cache_write_per_mtok_usd is None


def test_an_explicit_null_cache_rate_is_the_same_as_absent(tmp_path):
    document = {
        "entries": [
            {
                "model": "house-model",
                "provider": "anthropic",
                "effective_from": "2026-10-01",
                "input_per_mtok_usd": "1.00",
                "output_per_mtok_usd": "2.00",
                "cache_read_per_mtok_usd": None,
                "cache_write_per_mtok_usd": None,
            }
        ]
    }
    catalog = PriceCatalog.from_file(write_catalog(tmp_path, document))
    entry = catalog.resolve("anthropic", "house-model")
    assert entry is not None
    assert entry.cache_read_per_mtok_usd is None


def test_a_json_number_rate_is_read_through_its_shortest_repr(tmp_path):
    document = {
        "entries": [
            {
                "model": "house-model",
                "provider": "anthropic",
                "effective_from": "2026-10-01",
                "input_per_mtok_usd": 2.10,
                "output_per_mtok_usd": 0.1,
            }
        ]
    }
    catalog = PriceCatalog.from_file(write_catalog(tmp_path, document))
    entry = catalog.resolve("anthropic", "house-model")
    assert entry is not None
    assert entry.input_per_mtok_usd == Decimal("2.1")
    assert entry.output_per_mtok_usd == Decimal("0.1")


def test_a_file_that_prices_a_model_twice_is_refused(tmp_path):
    document = {
        "effective_from": "2026-10-01",
        "entries": [
            {
                "model": "house-model",
                "provider": "anthropic",
                "input_per_mtok_usd": "1.00",
                "output_per_mtok_usd": "2.00",
            },
            {
                "model": "house-model",
                "provider": "anthropic",
                "input_per_mtok_usd": "3.00",
                "output_per_mtok_usd": "4.00",
            },
        ],
    }
    with pytest.raises(ValueError, match="duplicate"):
        PriceCatalog.from_file(write_catalog(tmp_path, document))


def test_a_missing_file_says_so(tmp_path):
    with pytest.raises(FileNotFoundError):
        PriceCatalog.from_file(str(tmp_path / "absent.json"))


def test_a_file_path_may_be_a_pathlike(tmp_path):
    write_catalog(tmp_path, USER_DOCUMENT)
    catalog = PriceCatalog.from_file(tmp_path / "prices.json")
    assert catalog.resolve("anthropic", "house-model") is not None


INVALID_DOCUMENTS = [
    # (document, the substring the error must name)
    ([], "JSON object"),
    ("not a catalog", "JSON object"),
    ({"entries": [], "currency": "USD"}, "currency"),
    ({"effective_from": "2026-10-01"}, "entries"),
    ({"entries": {}}, "must be a list"),
    ({"entries": ["gpt-4o"]}, "must be a JSON object"),
    (
        {
            "entries": [
                {
                    "model": "gpt-4o",
                    "provider": "openai",
                    "input_per_mtok_usd": "1.00",
                    "output_per_mtok_usd": "2.00",
                    "discout": "50%",
                }
            ]
        },
        "discout",
    ),
    ({"entries": [{"provider": "openai"}]}, "model"),
    ({"entries": [{"model": "gpt-4o"}]}, "provider"),
    ({"entries": [{"model": "  ", "provider": "openai"}]}, "model"),
    (
        {
            "entries": [
                {
                    "model": "gpt-4o",
                    "provider": "openai",
                    "output_per_mtok_usd": "2.00",
                    "effective_from": "2026-10-01",
                }
            ]
        },
        "input_per_mtok_usd",
    ),
    (
        {
            "entries": [
                {
                    "model": "gpt-4o",
                    "provider": "openai",
                    "input_per_mtok_usd": "-1.00",
                    "output_per_mtok_usd": "2.00",
                    "effective_from": "2026-10-01",
                }
            ]
        },
        ">= 0",
    ),
    (
        {
            "entries": [
                {
                    "model": "gpt-4o",
                    "provider": "openai",
                    "input_per_mtok_usd": "free",
                    "output_per_mtok_usd": "2.00",
                    "effective_from": "2026-10-01",
                }
            ]
        },
        "not a decimal",
    ),
    (
        {
            "entries": [
                {
                    "model": "gpt-4o",
                    "provider": "openai",
                    "input_per_mtok_usd": True,
                    "output_per_mtok_usd": "2.00",
                    "effective_from": "2026-10-01",
                }
            ]
        },
        "input_per_mtok_usd",
    ),
    (
        {
            "entries": [
                {
                    "model": "gpt-4o",
                    "provider": "openai",
                    "input_per_mtok_usd": "1.00",
                    "output_per_mtok_usd": "2.00",
                }
            ]
        },
        "effective_from",
    ),
    (
        {
            "entries": [
                {
                    "model": "gpt-4o",
                    "provider": "openai",
                    "input_per_mtok_usd": "1.00",
                    "output_per_mtok_usd": "2.00",
                    "effective_from": "2026-13-01",
                }
            ]
        },
        "effective_from",
    ),
    (
        {
            "effective_from": "yesterday",
            "entries": [
                {
                    "model": "gpt-4o",
                    "provider": "openai",
                    "input_per_mtok_usd": "1.00",
                    "output_per_mtok_usd": "2.00",
                }
            ],
        },
        "effective_from",
    ),
]


@pytest.mark.parametrize(
    "document,expected", INVALID_DOCUMENTS, ids=[repr(doc)[:48] for doc, _ in INVALID_DOCUMENTS]
)
def test_an_invalid_catalog_file_names_the_offending_key(tmp_path, document, expected):
    with pytest.raises((TypeError, ValueError), match=expected):
        PriceCatalog.from_file(write_catalog(tmp_path, document))


def test_a_catalog_file_that_is_not_json_names_the_file(tmp_path):
    path = tmp_path / "prices.json"
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        PriceCatalog.from_file(str(path))


def test_a_catalog_file_error_names_the_file_and_the_entry(tmp_path):
    document = {
        "effective_from": "2026-10-01",
        "entries": [
            {
                "model": "gpt-4o",
                "provider": "openai",
                "input_per_mtok_usd": "1.00",
                "output_per_mtok_usd": "2.00",
            },
            {
                "model": "gpt-4o-mini",
                "provider": "openai",
                "output_per_mtok_usd": "2.00",
            },
        ],
    }
    with pytest.raises(ValueError) as excinfo:
        PriceCatalog.from_file(write_catalog(tmp_path, document))
    message = str(excinfo.value)
    assert "prices.json" in message
    assert "entry 1" in message
    assert "gpt-4o-mini" in message
    assert "input_per_mtok_usd" in message


def test_an_empty_catalog_file_is_a_catalog_with_no_user_prices(tmp_path):
    catalog = PriceCatalog.from_file(write_catalog(tmp_path, {"entries": []}))
    assert catalog.resolve("openai", "gpt-4o") is BUNDLED_PRICES["gpt-4o"]


# ---------------------------------------------------------------------------
# The public surface
# ---------------------------------------------------------------------------


def test_the_module_exports_exactly_the_four_names_the_catalog_task_names():
    assert pricing_catalog.__all__ == [
        "CostBreakdown",
        "PriceCatalog",
        "PriceEntry",
        "compute_cost",
    ]


def test_the_ledger_package_re_exports_the_price_catalog():
    import backstop.ledger as package

    for name in ("PriceEntry", "PriceCatalog", "CostBreakdown", "compute_cost"):
        assert getattr(package, name) is getattr(pricing_catalog, name), name
        assert name in package.__all__, name


def test_the_ledger_package_still_exports_its_own_names():
    import backstop.ledger as package

    for name in ("Attribution", "SpendEvent", "TenantBudget", "with_attribution"):
        assert name in package.__all__, name
    assert os.path.basename(package.__file__ or "") == "__init__.py"
