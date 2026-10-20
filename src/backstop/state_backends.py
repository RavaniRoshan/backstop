from __future__ import annotations

import asyncio
import threading
from abc import ABC, abstractmethod
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

#: The number of decimal places every amount in this package carries.
MONEY_PLACES = 6

#: How many US dollars one micro-dollar is worth: a million of them to the
#: dollar. The Redis backend stores money in micro-dollars because Lua's
#: ``tonumber`` is a double, and a double cannot represent most decimal
#: fractions of a dollar exactly. Storing integer micro-dollars keeps the
#: arithmetic exact on both sides of the round trip.
MICRO_DOLLARS = 1_000_000


def to_micro_dollars(amount: Decimal | int | float) -> int:
    """Convert a dollar amount to integer micro-dollars.

    The conversion is exact: the amount is quantised to the money precision
    first, then scaled. A float argument is converted through
    :class:`~decimal.Decimal` by its shortest repr, so ``0.1`` becomes
    ``Decimal("0.1")`` rather than the binary double nearest to it.
    """
    if isinstance(amount, float):
        amount = Decimal(repr(amount))
    quantized = Decimal(amount).quantize(
        Decimal(1).scaleb(-MONEY_PLACES), rounding=ROUND_HALF_UP
    )
    return int((quantized * MICRO_DOLLARS).to_integral_value())


def from_micro_dollars(micro: int) -> Decimal:
    """Convert integer micro-dollars back to a dollar amount."""
    return (Decimal(micro) / MICRO_DOLLARS).quantize(
        Decimal(1).scaleb(-MONEY_PLACES), rounding=ROUND_HALF_UP
    )


class BudgetBackend(ABC):
    """Pluggable storage for a token budget — and, optionally, a dollar one.

    The default :class:`InMemoryBudgetBackend` keeps state in the current
    process. :class:`RedisBudgetBackend` shares one budget across processes and
    replicas so a team can enforce a single spend cap without a proxy.

    A backend may carry a second ceiling, denominated in dollars. It is
    optional in every sense: a backend with no dollar ceiling accepts any
    amount, and a request with no dollar estimate reserves nothing on the
    dollar axis. The two axes are independent — a request is admitted only if
    **both** ceilings would survive it.
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

    @property
    def total_usd(self) -> Decimal | None:
        """The dollar ceiling, or ``None`` when there is none."""
        return None

    @property
    def spent_usd(self) -> Decimal:
        """The dollars spent so far."""
        return Decimal("0.000000")

    @property
    def reserved_usd(self) -> Decimal:
        """The dollars reserved by in-flight requests."""
        return Decimal("0.000000")

    @abstractmethod
    def reserve(self, tokens: int) -> bool: ...

    @abstractmethod
    def commit(self, reserved: int, charge: int) -> None: ...

    # ------------------------------------------------------------------
    # The optional dollar dimension
    # ------------------------------------------------------------------
    #
    # A backend written before dollar ceilings existed implements ``reserve``
    # and ``commit`` and nothing else, and keeps working unchanged: the
    # one-argument methods are still the contract, and the dollar hooks
    # below are additions rather than changes to it.
    #
    # A backend that wants to enforce a dollar ceiling overrides
    # ``reserve_with_usd`` and ``commit_with_usd``. The in-memory and Redis
    # backends do, and both do it *atomically* — the in-memory one under one
    # lock, the Redis one inside one Lua script — so the two ceilings can
    # never be checked against different versions of each other.

    def reserve_with_usd(self, tokens: int, usd: Decimal) -> bool:
        """Reserve against the token ceiling and the dollar ceiling.

        The default calls the one-argument ``reserve``, so a backend
        written before dollar ceilings existed keeps working unchanged, and
        then applies the dollar ceiling itself.

        :raises NotImplementedError: when a dollar ceiling is in force and
            the backend cannot enforce one.
        """
        if usd == 0:
            return self.reserve(tokens)
        raise NotImplementedError(
            f"{type(self).__name__} does not support a dollar ceiling. "
            "Implement reserve_with_usd() to enforce one."
        )

    def commit_with_usd(
        self, reserved: int, charge: int, usd_charge: Decimal
    ) -> None:
        """Settle a reservation on both ceilings."""
        self.commit(reserved, charge)

    async def areserve(self, tokens: int, usd: Decimal = Decimal("0")) -> bool:
        if usd == 0:
            return await asyncio.to_thread(self.reserve, tokens)
        return await asyncio.to_thread(self.reserve_with_usd, tokens, usd)

    async def acommit(
        self, reserved: int, charge: int, usd_charge: Decimal = Decimal("0")
    ) -> None:
        if usd_charge == 0:
            await asyncio.to_thread(self.commit, reserved, charge)
        else:
            await asyncio.to_thread(self.commit_with_usd, reserved, charge, usd_charge)


class InMemoryBudgetBackend(BudgetBackend):
    def __init__(self, total: int | None, total_usd: Decimal | None = None) -> None:
        if total is not None and total < 0:
            raise ValueError("total must be >= 0 or None")
        if total_usd is not None and total_usd < 0:
            raise ValueError("total_usd must be >= 0 or None")
        self._total = total
        self._total_usd = total_usd
        self._spent = 0
        self._reserved = 0
        self._spent_usd = Decimal("0.000000")
        self._reserved_usd = Decimal("0.000000")
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
    def total_usd(self) -> Decimal | None:
        return self._total_usd

    @property
    def spent_usd(self) -> Decimal:
        with self._lock:
            return self._spent_usd

    @property
    def reserved_usd(self) -> Decimal:
        with self._lock:
            return self._reserved_usd

    @property
    def remaining(self) -> int | None:
        if self._total is None:
            return None
        with self._lock:
            return max(0, self._total - self._spent - self._reserved)

    def reserve(self, tokens: int) -> bool:
        """Reserve tokens.

        A budget with no token ceiling reserves nothing: there is no ceiling
        for the reservation to protect, and an unlimited budget has always
        left ``spent`` at zero.
        """
        if self._total is None:
            return True
        with self._lock:
            if self._spent + self._reserved + tokens > self._total:
                return False
            self._reserved += tokens
            return True

    def reserve_with_usd(self, tokens: int, usd: Decimal) -> bool:
        """Reserve against both ceilings, under one lock.

        One lock, so the two ceilings cannot be checked against different
        versions of each other: a request is admitted only if it fits under
        the token ceiling *and* the dollar ceiling, as of the same instant.
        """
        with self._lock:
            if self._total is not None and self._spent + self._reserved + tokens > self._total:
                return False
            if (
                self._total_usd is not None
                and self._spent_usd + self._reserved_usd + usd > self._total_usd
            ):
                return False
            if self._total is not None:
                self._reserved += tokens
            self._reserved_usd += usd
            return True

    async def areserve(self, tokens: int, usd: Decimal = Decimal("0")) -> bool:
        # In-memory state, so there is no I/O to move off the event loop; the base
        # class's to_thread hop would be pure overhead. Mirrors ``acommit``.
        if usd == 0:
            return self.reserve(tokens)
        return self.reserve_with_usd(tokens, usd)

    def commit(self, reserved: int, charge: int) -> None:
        with self._lock:
            if self._total is not None:
                self._reserved = max(0, self._reserved - reserved)
                self._spent = min(self._total, self._spent + charge)

    def commit_with_usd(
        self, reserved: int, charge: int, usd_charge: Decimal
    ) -> None:
        with self._lock:
            if self._total is not None:
                self._reserved = max(0, self._reserved - reserved)
                self._spent = min(self._total, self._spent + charge)
            self._reserved_usd = max(Decimal("0"), self._reserved_usd - usd_charge)
            if self._total_usd is not None:
                self._spent_usd = min(self._total_usd, self._spent_usd + usd_charge)
            else:
                self._spent_usd += usd_charge

    async def acommit(
        self, reserved: int, charge: int, usd_charge: Decimal = Decimal("0")
    ) -> None:
        # This backend is pure in-memory state, so there is no I/O to move off
        # the event loop. The base class's to_thread hop would be pure overhead.
        if usd_charge == 0:
            self.commit(reserved, charge)
        else:
            self.commit_with_usd(reserved, charge, usd_charge)


#: The reserve script. Two ceilings are checked atomically: the token one
#: and, when the caller supplies one, the dollar one. Money is passed in as
#: integer micro-dollars, because Lua's `tonumber` is a double and a double
#: cannot represent most decimal fractions of a dollar exactly.
_RESERVE_LUA = """
local spent = tonumber(redis.call('HGET', KEYS[1], 'spent')) or 0
local reserved = tonumber(redis.call('HGET', KEYS[1], 'reserved')) or 0
local total = tonumber(redis.call('HGET', KEYS[1], 'total'))
local usd = tonumber(ARGV[2]) or 0
if total ~= nil then
  if spent + reserved + tonumber(ARGV[1]) > total then return 0 end
  redis.call('HINCRBY', KEYS[1], 'reserved', tonumber(ARGV[1]))
end
local total_usd = tonumber(redis.call('HGET', KEYS[1], 'total_usd'))
if total_usd ~= nil then
  local spent_usd = tonumber(redis.call('HGET', KEYS[1], 'spent_usd')) or 0
  local reserved_usd = tonumber(redis.call('HGET', KEYS[1], 'reserved_usd')) or 0
  if spent_usd + reserved_usd + usd > total_usd then
    -- Undo the token reservation: the request is not admitted, and the
    -- tokens must not stay held for it.
    if total ~= nil then
      redis.call('HINCRBY', KEYS[1], 'reserved', -tonumber(ARGV[1]))
    end
    return 0
  end
  if usd > 0 then redis.call('HINCRBY', KEYS[1], 'reserved_usd', usd) end
end
return 1
"""

_COMMIT_LUA = """
local reserved = tonumber(redis.call('HGET', KEYS[1], 'reserved')) or 0
local total = tonumber(redis.call('HGET', KEYS[1], 'total'))
if total ~= nil then
  local release = math.min(reserved, tonumber(ARGV[1]))
  redis.call('HINCRBY', KEYS[1], 'reserved', -release)
end
local usd_charge = tonumber(ARGV[3]) or 0
if usd_charge > 0 then
  local reserved_usd = tonumber(redis.call('HGET', KEYS[1], 'reserved_usd')) or 0
  local release_usd = math.min(reserved_usd, usd_charge)
  redis.call('HINCRBY', KEYS[1], 'reserved_usd', -release_usd)
end
local charge = tonumber(ARGV[2])
if charge > 0 and total ~= nil then
  local spent = tonumber(redis.call('HGET', KEYS[1], 'spent')) or 0
  local new_spent = spent + charge
  if total and new_spent > total then new_spent = total end
  redis.call('HSET', KEYS[1], 'spent', new_spent)
end
if usd_charge > 0 then
  local spent_usd = tonumber(redis.call('HGET', KEYS[1], 'spent_usd')) or 0
  local total_usd = tonumber(redis.call('HGET', KEYS[1], 'total_usd'))
  local new_spent_usd = spent_usd + usd_charge
  if total_usd and new_spent_usd > total_usd then new_spent_usd = total_usd end
  redis.call('HSET', KEYS[1], 'spent_usd', new_spent_usd)
end
return 1
"""


class RedisBudgetBackend(BudgetBackend):
    """Share one budget across processes/replicas via Redis.

    Operations are atomic (Lua scripts) so concurrent ``wrap()`` sessions in
    separate processes still enforce a single cap. The budget key is created on
    first use; ``total=None`` is treated as unlimited (no key is created).

    A dollar ceiling is stored in the same key, in integer micro-dollars, and
    checked by the same script — so a request is admitted only if it fits
    under *both* ceilings, and the two cannot be interleaved into a state
    where each was checked against a different version of the other.
    """

    def __init__(
        self,
        total: int | None,
        *,
        total_usd: Decimal | None = None,
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
        self._total_usd = total_usd
        self._key = key
        self._reserve_sha = self._client.script_load(_RESERVE_LUA)
        self._commit_sha = self._client.script_load(_COMMIT_LUA)
        if total is not None:
            self._client.hsetnx(self._key, "total", int(total))
        if total_usd is not None:
            self._client.hsetnx(self._key, "total_usd", to_micro_dollars(total_usd))

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
    def total_usd(self) -> Decimal | None:
        return self._total_usd

    @property
    def spent_usd(self) -> Decimal:
        value = self._client.hget(self._key, "spent_usd")
        return from_micro_dollars(int(value)) if value is not None else Decimal("0.000000")

    @property
    def reserved_usd(self) -> Decimal:
        value = self._client.hget(self._key, "reserved_usd")
        return from_micro_dollars(int(value)) if value is not None else Decimal("0.000000")

    @property
    def remaining(self) -> int | None:
        if self._total is None:
            return None
        return max(0, self._total - self.spent - self.reserved)

    def reserve(self, tokens: int) -> bool:
        if self._total is None:
            return True
        return self.reserve_with_usd(tokens, Decimal("0"))

    def reserve_with_usd(self, tokens: int, usd: Decimal) -> bool:
        """Reserve against both ceilings, in one script.

        The check and the reservation are one Lua script, so two ceilings
        are always checked against the same state.
        """
        result = self._client.evalsha(
            self._reserve_sha, 1, self._key, int(tokens), to_micro_dollars(usd)
        )
        return bool(int(result))

    def commit(self, reserved: int, charge: int) -> None:
        self.commit_with_usd(reserved, charge, Decimal("0"))

    def commit_with_usd(
        self, reserved: int, charge: int, usd_charge: Decimal
    ) -> None:
        self._client.evalsha(
            self._commit_sha,
            1,
            self._key,
            int(reserved),
            int(charge),
            to_micro_dollars(usd_charge),
        )


def build_backend(
    total: int | None,
    *,
    shared: bool = False,
    redis_url: str | None = None,
    redis_key: str | None = None,
    total_usd: Decimal | None = None,
) -> BudgetBackend:
    """Construct the appropriate backend from ergonomic options."""
    if shared or redis_url is not None:
        return RedisBudgetBackend(
            total,
            total_usd=total_usd,
            url=redis_url,
            key=redis_key or "backstop:budget",
        )
    return InMemoryBudgetBackend(total, total_usd=total_usd)
