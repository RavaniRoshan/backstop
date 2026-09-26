from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, NamedTuple

import httpx

from .config import BackstopConfig, Priority


@dataclass(frozen=True)
class RequestMetadata:
    priority: Priority
    estimated_tokens: int
    endpoint: str
    metadata: dict[str, Any] = field(default_factory=dict)


def request_metadata(request: httpx.Request, config: BackstopConfig) -> RequestMetadata:
    body = _json_body(request)
    endpoint = request.url.path
    return RequestMetadata(
        priority=Priority.from_header(request.headers.get("X-Backstop-Priority")),
        estimated_tokens=estimate_tokens(body, request.content, config, endpoint),
        endpoint=endpoint,
    )


def estimate_tokens(body: Any, raw: bytes, config: BackstopConfig, endpoint: str = "") -> int:
    if body is None:
        return max(1, int(len(raw) / (config.chars_per_token or 4.0)))

    if "/v1/messages" in endpoint and isinstance(body, Mapping):
        return _estimate_anthropic_tokens(body, raw, config)

    prompt_chars = _prompt_chars(body)
    output_tokens = _configured_output_tokens(body, config)
    body_floor = int(len(raw) / (config.chars_per_token or 4.0))

    model = body.get("model", "") if isinstance(body, Mapping) else ""
    if config.token_counter is not None:
        prompt_tokens = config.token_counter(str(body.get("messages", body)), model)
    elif config.auto_token_count:
        # Use tiktoken when available/recognized, else falls back to heuristic.
        prompt_tokens = count_tokens(str(body.get("messages", body)), model)
    else:
        prompt_tokens = int(prompt_chars / config.chars_per_token)

    return max(1, prompt_tokens + output_tokens, body_floor)


def _estimate_anthropic_tokens(body: dict, raw: bytes, config: BackstopConfig) -> int:
    messages = body.get("messages", [])
    prompt_chars = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            prompt_chars += len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    prompt_chars += len(block.get("text", ""))

    system = body.get("system")
    if isinstance(system, str):
        prompt_chars += len(system)
    elif isinstance(system, list):
        for block in system:
            if isinstance(block, dict) and block.get("type") == "text":
                prompt_chars += len(block.get("text", ""))

    output_tokens = body.get("max_tokens", config.default_max_output_tokens)

    prompt_tokens = int(prompt_chars / config.chars_per_token)
    body_floor = int(len(raw) / config.chars_per_token)
    return max(1, prompt_tokens + output_tokens, body_floor)


class TokenUsage(NamedTuple):
    """What a provider reported about one response's token usage, as a split.

    The budget reconciliation only ever wanted the arithmetic total, but a ledger
    bills input and output at different rates, so it needs the parts. This is
    both: :attr:`total` is byte-for-byte what :func:`response_usage_tokens` has
    always returned for the same response, so the reconciliation number cannot
    drift when the split is read too.

    Cache tokens are kept out of :attr:`input_tokens` and in their own fields.
    Anthropic counts ``cache_creation_input_tokens`` and
    ``cache_read_input_tokens`` *in addition to* ``input_tokens``, and a price
    card charges a cached read at a fraction of a fresh input, so folding them
    into one number would both overstate the fresh-token count and lose the
    cheaper rate. :attr:`total` still adds them, because that is what the
    reservation being reconciled was about.

    :attr:`split` says whether the provider reported the parts at all. It is
    ``False`` for the aggregate-only shapes (``total_tokens`` /
    ``total_token_count`` with no input or output beside them, which
    Gemini-style responses use), and it is the flag a caller must not ignore:
    those reports carry no input/output split, so any split derived from them is
    a guess. Note it is ``True`` for a body that published *both* a split and an
    aggregate — OpenAI sends both, and the parts are a measurement. See
    :func:`backstop.transports._record_spend` for what this transport does with
    a missing one rather than inventing it.
    """

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    total: int
    model: str | None
    split: bool


#: The usage field names read off a provider's ``usage`` object, spelled out in
#: :func:`_split_usage` rather than tabulated here, because that function runs on
#: the request path and a table lookup plus a generator expression costs more
#: than the dict reads they replace. The shapes, for the reader: OpenAI reports
#: ``prompt_tokens``/``completion_tokens``, Anthropic reports
#: ``input_tokens``/``output_tokens``, Vertex and Gemini report
#: ``prompt_token_count``/``candidates_token_count``, and every one of them may
#: publish an aggregate ``total_tokens``/``total_token_count`` instead of a split.
#: A new shape is added in :func:`_split_usage` and nowhere else.


def response_usage_tokens(response: httpx.Response) -> int | None:
    """Return the total tokens a response consumed, or ``None`` if it said nothing.

    The reconciliation number, unchanged in behaviour: a provider-reported total
    when one is present, otherwise the sum of what it did report, otherwise
    ``None``. :func:`response_usage` is the one parser behind both this and the
    ledger's split read, so a provider shape added for one is honoured by the
    other.
    """
    usage = response_usage(response)
    return None if usage is None else usage.total


def response_usage(response: httpx.Response) -> TokenUsage | None:
    """Return this response's token usage as a split, or ``None`` if it said nothing.

    Reads the JSON body when there is one and falls back to the last ``data:``
    chunk of an SSE body, exactly as :func:`response_usage_tokens` always has.
    The difference is the shape of the answer: the parts, plus the model string
    the provider itself reported, rather than one number.

    Never raises. A body that is not JSON, a ``usage`` that is not an object and
    a response that says nothing at all all read as ``None`` — the honest answer
    being "this provider reported no usage", not a fabricated zero, which is
    what a caller that treats a missing ``usage`` as ``0`` would bill.

    The control flow is deliberately the same as
    :func:`response_usage_tokens` has always been, one-for-one: read the JSON
    body, use its ``usage`` object if it has one, and otherwise fall back to the
    last ``data:`` chunk of an SSE body. Only the shape of the answer differs.
    """
    usage: Mapping[str, Any] | None = None
    model: Any = None
    try:
        payload = response.json()
        if isinstance(payload, dict):
            found = payload.get("usage")
            if isinstance(found, dict):
                usage, model = found, payload.get("model")
    except Exception:
        usage = None

    if usage is not None:
        return _token_usage(usage, model)
    return sse_usage(response.text)


def sse_usage(response_text: str) -> TokenUsage | None:
    """Read the token usage out of SSE *text* — the streaming reconciliation path.

    The text-level twin of :func:`response_usage`, for the caller that has
    accumulated the stream's bytes rather than a :class:`httpx.Response`. Same
    reader, same result: the last ``data:`` chunk that carried a ``usage``
    block, parsed from the bottom up because usage is the last thing a provider
    sends before ``[DONE]``. ``None`` when the stream carried no usage.

    ``model`` is reported only when the chunk carrying the usage also carries it
    at the top level. Anthropic's ``message_start`` chunk names the model
    instead, in a nested ``message`` object, and this deliberately does not go
    looking for it: a reconciliation caller wants a sum, and a stream reader
    that hunted through every chunk for a string would be doing provider-shape
    work on the consume path for a value the request already carried.
    """
    if "data:" not in response_text:
        return None

    lines = response_text.strip().split("\n")
    for line in reversed(lines):
        line = line.strip()
        if not line or line == "data: [DONE]":
            continue
        if line.startswith("data: "):
            try:
                data = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
            usage = data.get("usage")
            if isinstance(usage, dict) and usage:
                return _token_usage(usage, data.get("model"))
    return None


def _split_usage(usage: Mapping[str, Any]) -> tuple[int, int, int, int, int | None, bool] | None:
    """Read one provider ``usage`` object.

    Returns ``(input, output, cache_read, cache_write, total, split)``, or
    ``None`` when the object carried no usage at all — which is different from
    carrying zeros. Cache counts come back separate from ``input``, because
    Anthropic publishes them *in addition to* it.

    ``total`` is the provider's own aggregate when it published one, and ``None``
    otherwise so the caller sums the parts rather than mistaking a missing total
    for a measured zero. ``split`` is ``True`` when the parts are a measurement
    rather than the zeros that stand in for an absent split.

    The split is read even when an aggregate is present, because OpenAI publishes
    both and a ledger that billed the aggregate as if it were all input would
    under-price every response. The aggregate still wins for ``total``, which is
    the precedence :func:`response_usage_tokens` has always applied.

    The names are spelled out rather than iterated: this runs on the request path
    for every non-streaming response, and unpacking a generator into
    ``_int_or_zero`` measured half a microsecond more per call than passing the
    three ``get``s as arguments, twice.
    """
    input_tokens = _int_or_zero(
        usage.get("input_tokens"),
        usage.get("prompt_tokens"),
        usage.get("prompt_token_count"),
    )
    output_tokens = _int_or_zero(
        usage.get("output_tokens"),
        usage.get("completion_tokens"),
        usage.get("completion_token_count"),
        usage.get("candidates_token_count"),
    )
    # A cache count is additive, so an unusable one is worth nothing rather than
    # fatal: a body that puts a string where a count belongs costs the cached
    # read its rate and says so by being absent, rather than failing the request
    # that carried it.
    cache_read = usage.get("cache_read_input_tokens")
    cache_write = usage.get("cache_creation_input_tokens")
    # ``bool`` is an ``int``, and a JSON ``true`` read as a token count is a body
    # shape no provider emits. Refusing it here keeps the boolean out of a
    # SpendEvent, which refuses it by name.
    total = usage.get("total_tokens")
    if type(total) is not int or total < 0:
        total = usage.get("total_token_count")
    if type(total) is not int or total < 0:
        total = None
    if input_tokens is None and output_tokens is None:
        if total is None:
            return None
        return (0, 0, 0, 0, total, False)
    return (
        input_tokens or 0,
        output_tokens or 0,
        cache_read if type(cache_read) is int and cache_read >= 0 else 0,
        cache_write if type(cache_write) is int and cache_write >= 0 else 0,
        total,
        True,
    )


def _token_usage(usage: Mapping[str, Any], model: Any) -> TokenUsage | None:
    """Assemble a :class:`TokenUsage` from one already-read ``usage`` object."""
    split = _split_usage(usage)
    if split is None:
        return None
    input_tokens, output_tokens, cache_read, cache_write, reported_total, is_split = split
    if reported_total is not None:
        total = reported_total
    else:
        # The arithmetic total, as it has always been computed: cache counts are
        # added to the fresh input, because that is what the reservation covers.
        total = input_tokens + output_tokens + cache_read + cache_write
    return TokenUsage(
        input_tokens,
        output_tokens,
        cache_read,
        cache_write,
        total,
        model if isinstance(model, str) and model else None,
        is_split,
    )


def _json_body(request: httpx.Request) -> Any:
    if not request.content:
        return None
    content_type = request.headers.get("content-type", "")
    if "json" not in content_type and not request.content.strip().startswith((b"{", b"[")):
        return None
    try:
        return json.loads(request.content.decode("utf-8"))
    except Exception:
        return None


def _prompt_chars(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value)
    if isinstance(value, (int, float, bool)):
        return len(str(value))
    if isinstance(value, Mapping):
        total = 0
        for key, item in value.items():
            if key in {"max_tokens", "max_output_tokens", "stream", "temperature", "top_p"}:
                continue
            if key in {"messages", "input", "prompt", "instructions", "content", "text"}:
                total += _prompt_chars(item)
            elif isinstance(item, (Mapping, Sequence)) and not isinstance(item, (str, bytes, bytearray)):
                total += _prompt_chars(item)
        return total
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return sum(_prompt_chars(item) for item in value)
    return len(str(value))


def _configured_output_tokens(body: Any, config: BackstopConfig) -> int:
    if not isinstance(body, Mapping):
        return config.default_max_output_tokens
    for key in ("max_output_tokens", "max_tokens", "max_completion_tokens"):
        value = body.get(key)
        if isinstance(value, int) and value >= 0:
            return value
    return config.default_max_output_tokens


def count_tokens(text: str, model: str = "gpt-4o") -> int:
    try:
        import tiktoken
    except ImportError:
        return max(1, int(len(text) / 4.0))
    encoding_map = {
        "gpt-4o": "o200k_base",
        "gpt-4o-mini": "o200k_base",
        "gpt-4-turbo": "cl100k_base",
        "gpt-4": "cl100k_base",
        "gpt-3.5-turbo": "cl100k_base",
    }
    encoding_name = encoding_map.get(model, "cl100k_base")
    try:
        enc = tiktoken.get_encoding(encoding_name)
        return len(enc.encode(text))
    except Exception:
        return max(1, int(len(text) / 4.0))


def _int_or_zero(*values: Any) -> int | None:
    for value in values:
        if isinstance(value, int) and value >= 0:
            return value
    return None

