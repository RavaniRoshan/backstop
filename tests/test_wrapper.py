import pytest

from backstop import Backstop
from backstop.exceptions import UnsupportedClientError


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

