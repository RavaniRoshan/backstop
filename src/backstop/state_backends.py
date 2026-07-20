from __future__ import annotations

import asyncio
import threading
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class BudgetBackend(ABC):
    """Pluggable storage for a token budget.

    The default :class:`InMemoryBudgetBackend` keeps state in the current
    process. :class:`RedisBudgetBackend` shares one budget across processes and
    replicas so a team can enforce a single spend cap without a proxy.
    """

    @property
    @abstractmethod
    def total(self) -> int | None: ...

    @property
    @abstractmethod
    def spent(self) -> int: ...

    @property
    @abstractmethod
    def reserved(self) -> int: ...

    @abstractmethod
    def reserve(self, tokens: int) -> bool: ...

    @abstractmethod
    def commit(self, reserved: int, charge: int) -> None: ...

    async def areserve(self, tokens: int) -> bool:
        return await asyncio.to_thread(self.reserve, tokens)

    async def acommit(self, reserved: int, charge: int) -> None:
        await asyncio.to_thread(self.commit, reserved, charge)


class InMemoryBudgetBackend(BudgetBackend):
    def __init__(self, total: int | None) -> None:
        if total is not None and total < 0:
            raise ValueError("total must be >= 0 or None")
        self._total = total
        self._spent = 0
        self._reserved = 0
        self._lock = threading.Lock()

    @property
    def total(self) -> int | None:
        return self._total

    @property
    def spent(self) -> int:
        with self._lock:
            return self._spent

    @property
    def reserved(self) -> int:
        with self._lock:
            return self._reserved

    @property
    def remaining(self) -> int | None:
        if self._total is None:
            return None
        with self._lock:
            return max(0, self._total - self._spent - self._reserved)

    def reserve(self, tokens: int) -> bool:
        if self._total is None:
            return True
        with self._lock:
            if self._spent + self._reserved + tokens > self._total:
                return False
            self._reserved += tokens
            return True

    def commit(self, reserved: int, charge: int) -> None:
        if self._total is None:
            return
        with self._lock:
            self._reserved = max(0, self._reserved - reserved)
            self._spent = min(self._total, self._spent + charge)


_RESERVE_LUA = """
local spent = tonumber(redis.call('HGET', KEYS[1], 'spent')) or 0
local reserved = tonumber(redis.call('HGET', KEYS[1], 'reserved')) or 0
local total = tonumber(redis.call('HGET', KEYS[1], 'total'))
if total == nil then return 1 end
if spent + reserved + tonumber(ARGV[1]) > total then return 0 end
redis.call('HINCRBY', KEYS[1], 'reserved', tonumber(ARGV[1]))
return 1
"""

_COMMIT_LUA = """
local reserved = tonumber(redis.call('HGET', KEYS[1], 'reserved')) or 0
local release = math.min(reserved, tonumber(ARGV[1]))
redis.call('HINCRBY', KEYS[1], 'reserved', -release)
local charge = tonumber(ARGV[2])
if charge > 0 then
  local spent = tonumber(redis.call('HGET', KEYS[1], 'spent')) or 0
  local total = tonumber(redis.call('HGET', KEYS[1], 'total'))
  local new_spent = spent + charge
  if total and new_spent > total then new_spent = total end
  redis.call('HSET', KEYS[1], 'spent', new_spent)
end
return 1
"""


class RedisBudgetBackend(BudgetBackend):
    """Share one budget across processes/replicas via Redis.

    Operations are atomic (Lua scripts) so concurrent ``wrap()`` sessions in
    separate processes still enforce a single cap. The budget key is created on
    first use; ``total=None`` is treated as unlimited (no key is created).
    """

    def __init__(
        self,
        total: int | None,
        *,
        url: str | None = None,
        key: str = "backstop:budget",
        client: Any | None = None,
    ) -> None:
        try:
            import redis  # noqa: F401
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "The 'redis' package is required for a shared Redis budget. "
                "Install it with: pip install backstop[redis]"
            ) from exc

        if client is not None:
            self._client = client
        elif url is not None:
            import redis

            self._client = redis.Redis.from_url(url)
        else:
            import redis

            self._client = redis.Redis()
        self._total = total
        self._key = key
        self._reserve_sha = self._client.script_load(_RESERVE_LUA)
        self._commit_sha = self._client.script_load(_COMMIT_LUA)
        if total is not None:
            self._client.hsetnx(self._key, "total", int(total))

    @property
    def total(self) -> int | None:
        return self._total

    @property
    def spent(self) -> int:
        value = self._client.hget(self._key, "spent")
        return int(value) if value is not None else 0

    @property
    def reserved(self) -> int:
        value = self._client.hget(self._key, "reserved")
        return int(value) if value is not None else 0

    @property
    def remaining(self) -> int | None:
        if self._total is None:
            return None
        return max(0, self._total - self.spent - self.reserved)

    def reserve(self, tokens: int) -> bool:
        if self._total is None:
            return True
        result = self._client.evalsha(self._reserve_sha, 1, self._key, int(tokens))
        return bool(int(result))

    def commit(self, reserved: int, charge: int) -> None:
        self._client.evalsha(self._commit_sha, 1, self._key, int(reserved), int(charge))


def build_backend(
    total: int | None,
    *,
    shared: bool = False,
    redis_url: str | None = None,
    redis_key: str | None = None,
) -> BudgetBackend:
    """Construct the appropriate backend from ergonomic options."""
    if shared or redis_url is not None:
        return RedisBudgetBackend(
            total, url=redis_url, key=redis_key or "backstop:budget"
        )
    return InMemoryBudgetBackend(total)
