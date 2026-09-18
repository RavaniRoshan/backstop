from __future__ import annotations

from typing import Any, TypeVar

from ._httpcompat import HTTPX, compat_for
from .config import BackstopConfig
from .exceptions import UnsupportedClientError
from .metrics import metrics_app, start_metrics_server
from .state import BackstopState
from .transports import AsyncBackstopTransport, BackstopTransport

T = TypeVar("T")

_SUPPORTED_OPENAI = frozenset({"OpenAI", "AsyncOpenAI"})
_SUPPORTED_ANTHROPIC = frozenset({"Anthropic", "AsyncAnthropic"})  # fmt: skip

# PLAN 1.4.1 — tested SDK ranges (must match .github/workflows/ci.yml).
# Anything outside these ranges gets a loud warning, never a silent pass.
#
# Floors are the first versions that stop relabelling transport exceptions:
# below openai 2.37 / anthropic 0.98 the SDK's request loop catches any
# exception from the transport — including Backstop's BudgetExceededError —
# and re-raises it as APIConnectionError, making the guardrail invisible to
# user code (bisect 2026-09-18: openai 2.36.0/anthropic 0.97.0 lack the
# guard, openai 2.37.0/anthropic 0.98.0 have it). Ceilings guard future
# majors; openai 3.15.0 and anthropic 1.6.0 are current at writing.
SUPPORTED_OPENAI_RANGE = ">=2.37,<4"
SUPPORTED_ANTHROPIC_RANGE = ">=0.98,<2"


class Backstop:
    @staticmethod
    def wrap(client: T, budget: int | None = 50_000, config: BackstopConfig | None = None) -> T:
        existing = getattr(client, "_backstop_state", None)
        if existing is not None:
            return client

        resolved_config = config or BackstopConfig()
        _warn_if_over_concurrency_ceiling(resolved_config)

        cls = client.__class__
        provider = _detect_provider(cls)
        if not provider:
            raise UnsupportedClientError(
                "Backstop v1 supports openai.OpenAI, openai.AsyncOpenAI, "
                "anthropic.Anthropic, and anthropic.AsyncAnthropic clients only"
            )
        _warn_if_unsupported_sdk_version(provider)

        state = BackstopState.create(budget, config)
        state.provider = provider
        if provider == "anthropic":
            if cls.__name__ == "AsyncAnthropic":
                wrapped_http_client = _build_async_anthropic_http_client(client, state)
            else:
                wrapped_http_client = _build_sync_anthropic_http_client(client, state)
            wrapped = _clone_anthropic_client(client, wrapped_http_client)
        else:
            if cls.__name__ == "AsyncOpenAI":
                wrapped_http_client = _build_async_http_client(client, state)
            else:
                wrapped_http_client = _build_sync_http_client(client, state)
            wrapped = _clone_openai_client(client, wrapped_http_client)

        setattr(wrapped, "_backstop_state", state)
        return wrapped

    start_metrics_server = staticmethod(start_metrics_server)
    metrics_app = staticmethod(metrics_app)

    @staticmethod
    def dashboard_app(**kwargs: Any) -> Any:
        """Mount the built-in dashboard in your own server.

        Lazy import on purpose: ``import backstop`` stays cheap and the
        dashboard's shell, CSS and JS are only loaded when actually used.

        ::

            app = FastAPI()
            app.mount("/", WSGIMiddleware(Backstop.dashboard_app()))
        """
        from .dashboard_app import dashboard_wsgi_app

        return dashboard_wsgi_app(**kwargs)


def _detect_provider(cls: type) -> str:
    module = getattr(cls, "__module__", "")
    name = getattr(cls, "__name__", "")
    if module.startswith("openai") and name in _SUPPORTED_OPENAI:
        return "openai"
    if module.startswith("anthropic") and name in _SUPPORTED_ANTHROPIC:
        return "anthropic"
    return ""


def _warn_if_unsupported_sdk_version(provider: str) -> None:
    """PLAN 1.4.1: warn loudly on untested SDK majors, never fail silently.

    The supported ranges mirror the CI matrix in
    ``.github/workflows/ci.yml``. Wrap still proceeds — the warning names
    the tested range so the user can pin or upgrade deliberately.
    """
    import warnings

    if provider == "openai":
        package, supported = "openai", SUPPORTED_OPENAI_RANGE
    elif provider == "anthropic":
        package, supported = "anthropic", SUPPORTED_ANTHROPIC_RANGE
    else:
        return
    try:
        from importlib.metadata import version

        installed = version(package)
    except Exception:
        return
    if not _version_in_range(installed, supported):
        warnings.warn(
            f"Backstop: {package} {installed} is outside the tested range "
            f"{supported} (see docs/compatibility.md). Wrap proceeds, but "
            "budget enforcement on this SDK version is unverified — pin a "
            "tested version if transport compatibility is critical.",
            stacklevel=3,
        )


def _version_in_range(installed: str, spec: str) -> bool:
    """Minimal ``>=x,<y`` range check on numeric release segments."""
    release: list[int] = []
    for part in installed.split("+")[0].split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        if not digits and release:
            break
        release.append(int(digits) if digits else 0)
    for bound in spec.split(","):
        bound = bound.strip()
        if bound.startswith(">="):
            if _cmp_release(release, _parse_bound(bound[2:])) < 0:
                return False
        elif bound.startswith("<"):
            if _cmp_release(release, _parse_bound(bound[1:])) >= 0:
                return False
    return True


def _parse_bound(text: str) -> list[int]:
    return [int(p) for p in text.strip().split(".") if p.isdigit()]


def _cmp_release(left: list[int], right: list[int]) -> int:
    width = max(len(left), len(right))
    left = left + [0] * (width - len(left))
    right = right + [0] * (width - len(right))
    return (left > right) - (left < right)


_active_wraps = 0


def _warn_if_over_concurrency_ceiling(config: BackstopConfig) -> None:
    global _active_wraps
    _active_wraps += 1
    if config.max_wrap_sessions and _active_wraps > config.max_wrap_sessions:
        import warnings

        warnings.warn(
            f"Backstop: {_active_wraps} active wrap() sessions exceed "
            f"max_wrap_sessions={config.max_wrap_sessions}. Under CPython's GIL, "
            "many concurrent in-process sessions serialize on it — consider fewer "
            "sessions per process or a process per agent.",
            stacklevel=2,
        )


def _clone_openai_client(client: Any, http_client: Any) -> Any:
    if hasattr(client, "with_options"):
        for kwargs in (
            {"http_client": http_client, "max_retries": 0},
        ):
            try:
                return client.with_options(**kwargs)
            except TypeError:
                continue

    kwargs: dict[str, Any] = {"http_client": http_client, "max_retries": 0}
    for attr in (
        "api_key",
        "organization",
        "project",
        "base_url",
        "timeout",
        "default_headers",
        "default_query",
    ):
        if hasattr(client, attr):
            kwargs[attr] = getattr(client, attr)
    try:
        return client.__class__(**kwargs)
    except Exception as exc:
        raise UnsupportedClientError(
            "could not rebuild OpenAI client with a Backstop http_client"
        ) from exc


def _clone_anthropic_client(client: Any, http_client: Any) -> Any:
    if hasattr(client, "copy"):
        for kwargs in (
            {"http_client": http_client, "max_retries": 0},
        ):
            try:
                return client.copy(**kwargs)
            except TypeError:
                continue

    kwargs: dict[str, Any] = {"http_client": http_client, "max_retries": 0}
    for attr in (
        "api_key",
        "base_url",
        "timeout",
        "default_headers",
        "default_query",
    ):
        if hasattr(client, attr):
            kwargs[attr] = getattr(client, attr)
    try:
        return client.__class__(**kwargs)
    except Exception as exc:
        raise UnsupportedClientError(
            "could not rebuild Anthropic client with a Backstop http_client"
        ) from exc


def _build_sync_anthropic_http_client(client: Any, state: BackstopState) -> Any:
    base = getattr(client, "_client", None)
    compat = compat_for(base)
    underlying = _sync_transport_from(base)
    # The Anthropic SDK accepts http_client and max_retries.
    # BackstopTransport handles retries internally; we don't pass max_retries to the HTTP client.
    return compat.Client(
        transport=BackstopTransport(state, underlying, compat=compat),
        timeout=_timeout_from(base, compat),
        base_url=_base_url_from(base),
    )


def _build_async_anthropic_http_client(client: Any, state: BackstopState) -> Any:
    base = getattr(client, "_client", None)
    compat = compat_for(base)
    underlying = _async_transport_from(base)
    # The Anthropic SDK accepts http_client and max_retries.
    # BackstopTransport handles retries internally; we don't pass max_retries to the HTTP client.
    return compat.AsyncClient(
        transport=AsyncBackstopTransport(state, underlying, compat=compat),
        timeout=_timeout_from(base, compat),
        base_url=_base_url_from(base),
    )


def _build_sync_http_client(client: Any, state: BackstopState) -> Any:
    base = getattr(client, "_client", None)
    compat = compat_for(base)
    underlying = _sync_transport_from(base)
    # OpenAI Client accepts max_retries, so we use it for Backstop's retry logic.
    # httpx/httpx2 Client does NOT accept max_retries, so we do not pass it here.
    return compat.Client(
        transport=BackstopTransport(state, underlying, compat=compat),
        timeout=_timeout_from(base, compat),
        base_url=_base_url_from(base),
    )


def _build_async_http_client(client: Any, state: BackstopState) -> Any:
    base = getattr(client, "_client", None)
    compat = compat_for(base)
    underlying = _async_transport_from(base)
    # OpenAI AsyncClient accepts max_retries, so we use it for Backstop's retry logic.
    # httpx/httpx2 AsyncClient does NOT accept max_retries, so we do not pass it here.
    return compat.AsyncClient(
        transport=AsyncBackstopTransport(state, underlying, compat=compat),
        timeout=_timeout_from(base, compat),
        base_url=_base_url_from(base),
    )


def _sync_transport_from(base: Any) -> Any:
    compat = compat_for(base)
    transport = getattr(base, "_transport", None)
    if isinstance(transport, (HTTPX.BaseTransport, compat.BaseTransport)):
        return transport
    return compat.HTTPTransport()


def _async_transport_from(base: Any) -> Any:
    compat = compat_for(base)
    transport = getattr(base, "_transport", None)
    if isinstance(transport, (HTTPX.AsyncBaseTransport, compat.AsyncBaseTransport)):
        return transport
    return compat.AsyncHTTPTransport()


def _timeout_from(base: Any, compat: Any = None) -> Any:
    timeout = getattr(base, "timeout", None)
    mod = compat or HTTPX
    if isinstance(timeout, mod.Timeout):
        return timeout
    return mod.Timeout(60.0)


def _base_url_from(base: Any) -> str:
    base_url = getattr(base, "base_url", None)
    return str(base_url) if base_url is not None else ""

