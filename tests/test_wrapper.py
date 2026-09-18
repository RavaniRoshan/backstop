import asyncio

import pytest

from backstop import Backstop
from backstop._httpcompat import compat_for, module_root
from backstop.exceptions import BudgetExceededError, UnsupportedClientError


def test_wrap_rejects_unsupported_client():
    with pytest.raises(UnsupportedClientError):
        Backstop.wrap(object())


def test_wrap_openai_client_when_sdk_installed():
    openai = pytest.importorskip("openai")
    client = openai.OpenAI(api_key="sk-test")
    wrapped = Backstop.wrap(client, budget=None)
    assert wrapped.__class__ is client.__class__
    assert Backstop.wrap(wrapped) is wrapped


def test_wrap_anthropic_client_when_sdk_installed():
    anthropic = pytest.importorskip("anthropic")
    client = anthropic.Anthropic(api_key="sk-ant-test")
    wrapped = Backstop.wrap(client, budget=None)
    assert wrapped.__class__ is client.__class__
    assert Backstop.wrap(wrapped) is wrapped


def test_wrap_async_anthropic_client_when_sdk_installed():
    anthropic = pytest.importorskip("anthropic")
    client = anthropic.AsyncAnthropic(api_key="sk-ant-test")
    wrapped = Backstop.wrap(client, budget=None)
    assert wrapped.__class__ is client.__class__
    assert Backstop.wrap(wrapped) is wrapped


def test_wrap_anthropic_sets_backstop_state():
    anthropic = pytest.importorskip("anthropic")
    client = anthropic.Anthropic(api_key="sk-ant-test")
    wrapped = Backstop.wrap(client, budget=500)
    state = getattr(wrapped, "_backstop_state", None)
    assert state is not None
    assert state.budget.remaining == 500


def test_wrap_anthropic_rejects_invalid():
    with pytest.raises(UnsupportedClientError):
        Backstop.wrap("not-a-client")


def _provider_spec(provider):
    if provider == "openai":
        return {
            "module": "openai",
            "sync_cls": "OpenAI",
            "async_cls": "AsyncOpenAI",
            "call": lambda client: client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "hi"}],
            ),
            "preflight_budget": 1000,
            "base_error": "OpenAIError",
        }
    return {
        "module": "anthropic",
        "sync_cls": "Anthropic",
        "async_cls": "AsyncAnthropic",
        "call": lambda client: client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=10,
            messages=[{"role": "user", "content": "hi"}],
        ),
        "preflight_budget": 1,
        "base_error": "AnthropicError",
    }


def _sentinel_transport(compat, async_mode):
    calls = []

    if async_mode:

        class SentinelTransport(compat.AsyncBaseTransport):
            async def handle_async_request(self, request):
                calls.append(request)
                raise BudgetExceededError("transport raised")

    else:

        class SentinelTransport(compat.BaseTransport):
            def handle_request(self, request):
                calls.append(request)
                raise BudgetExceededError("transport raised")

    return SentinelTransport(), calls


def _make_client(sdk, spec, async_mode, http_client=None):
    kwargs = {"api_key": "sk-test"}
    if http_client is not None:
        kwargs["http_client"] = http_client
    name = spec["async_cls"] if async_mode else spec["sync_cls"]
    return getattr(sdk, name)(**kwargs)


def _close_http(client, async_mode):
    if async_mode:
        asyncio.run(client._client.aclose())
    else:
        client._client.close()


def _invoke(client, spec, async_mode):
    result = spec["call"](client)
    if async_mode:
        asyncio.run(result)


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
@pytest.mark.parametrize("async_mode", [False, True])
def test_budget_error_from_wrapped_transport_propagates(provider, async_mode):
    spec = _provider_spec(provider)
    sdk = pytest.importorskip(spec["module"])
    probe = _make_client(sdk, spec, async_mode)
    compat = compat_for(probe._client)
    expected_root = module_root(probe._client)
    _close_http(probe, async_mode)

    sentinel, calls = _sentinel_transport(compat, async_mode)
    http_cls = compat.AsyncClient if async_mode else compat.Client
    client = _make_client(sdk, spec, async_mode, http_cls(transport=sentinel))
    wrapped = Backstop.wrap(client, budget=1_000_000)
    try:
        assert module_root(wrapped._client) == expected_root
        assert wrapped._client._transport._transport is sentinel
        with pytest.raises(BudgetExceededError, match="transport raised") as excinfo:
            _invoke(wrapped, spec, async_mode)
        assert isinstance(excinfo.value, getattr(sdk, spec["base_error"]))
        assert len(calls) == 1
    finally:
        _close_http(wrapped, async_mode)
        _close_http(client, async_mode)


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
@pytest.mark.parametrize("async_mode", [False, True])
def test_preflight_budget_rejects_before_transport(provider, async_mode):
    spec = _provider_spec(provider)
    sdk = pytest.importorskip(spec["module"])
    probe = _make_client(sdk, spec, async_mode)
    compat = compat_for(probe._client)
    expected_root = module_root(probe._client)
    _close_http(probe, async_mode)

    sentinel, calls = _sentinel_transport(compat, async_mode)
    http_cls = compat.AsyncClient if async_mode else compat.Client
    client = _make_client(sdk, spec, async_mode, http_cls(transport=sentinel))
    wrapped = Backstop.wrap(client, budget=spec["preflight_budget"])
    try:
        assert module_root(wrapped._client) == expected_root
        with pytest.raises(BudgetExceededError, match="exceeds remaining budget"):
            _invoke(wrapped, spec, async_mode)
        assert calls == []
    finally:
        _close_http(wrapped, async_mode)
        _close_http(client, async_mode)


def test_wrap_warns_on_unsupported_sdk_version_but_proceeds():
    """PLAN 1.4.1: untested SDK version warns loudly, wrap still proceeds."""
    from unittest.mock import patch

    openai = pytest.importorskip("openai")
    client = openai.OpenAI(api_key="sk-test")
    try:
        with patch("importlib.metadata.version", return_value="1.0.0"):
            with pytest.warns(UserWarning, match="outside the tested range"):
                wrapped = Backstop.wrap(client, budget=100)
        assert getattr(wrapped, "_backstop_state", None) is not None
        wrapped._client.close()
    finally:
        client._client.close()


def test_wrap_silent_on_supported_sdk_version():
    """PLAN 1.4.1: tested SDK version wraps with no version warning."""
    import warnings

    openai = pytest.importorskip("openai")
    client = openai.OpenAI(api_key="sk-test")
    try:
        with warnings.catch_warnings(record=True) as rec:
            warnings.simplefilter("always")
            wrapped = Backstop.wrap(client, budget=100)
        assert not [w for w in rec if "outside the tested range" in str(w.message)]
        wrapped._client.close()
    finally:
        client._client.close()

