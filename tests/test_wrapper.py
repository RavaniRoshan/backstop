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

