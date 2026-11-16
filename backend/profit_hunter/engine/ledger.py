"""Weekly budget ledger (pure logic).

Rules:
* Available = starting budget - pending commitments - actual spending.
* A commitment holds its capital until it is CANCELED or SETTLED.
* Resale proceeds (projected or realized) are NEVER added to available cash.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from zoneinfo import ZoneInfo

from ..money import ZERO


class TxnKind(str, Enum):
    COMMIT = "COMMIT"      # capital reserved for a purchase
    RELEASE = "RELEASE"    # commitment canceled; capital freed
    SETTLE = "SETTLE"      # commitment became actual spending
    PROCEEDS = "PROCEEDS"  # realized resale proceeds (informational only)


@dataclass(frozen=True)
class LedgerEntry:
    kind: TxnKind
    amount: Decimal
    # For SETTLE: how much of the earlier commitment this settlement closes out.
    commitment_released: Decimal = ZERO


@dataclass(frozen=True)
class WeekSummary:
    starting_budget: Decimal
    pending_commitments: Decimal
    actual_spending: Decimal
    realized_proceeds: Decimal

    @property
    def committed_total(self) -> Decimal:
        """Everything spoken for this week: pending commitments + actual spending."""
        return self.pending_commitments + self.actual_spending

    @property
    def available(self) -> Decimal:
        return self.starting_budget - self.pending_commitments - self.actual_spending

    @property
    def over_budget(self) -> bool:
        return self.available < 0


def summarize(starting_budget: Decimal, entries: list[LedgerEntry]) -> WeekSummary:
    pending = spent = proceeds = ZERO
    for e in entries:
        if e.amount < 0 or e.commitment_released < 0:
            raise ValueError("Ledger amounts must not be negative.")
        if e.kind is TxnKind.COMMIT:
            pending += e.amount
        elif e.kind is TxnKind.RELEASE:
            pending -= e.amount
        elif e.kind is TxnKind.SETTLE:
            pending -= e.commitment_released
            spent += e.amount
        elif e.kind is TxnKind.PROCEEDS:
            proceeds += e.amount  # deliberately does not touch available budget
    if pending < 0:
        raise ValueError("Ledger is inconsistent: more released than was committed.")
    return WeekSummary(starting_budget, pending, spent, proceeds)


def week_start_for(moment: datetime, week_start_day: int, timezone: str) -> date:
    """The local date the budget week containing ``moment`` began.

    ``week_start_day``: 0 = Monday ... 6 = Sunday. ``moment`` must be timezone-aware.
    """
    if moment.tzinfo is None:
        raise ValueError("A timezone-aware datetime is required.")
    local = moment.astimezone(ZoneInfo(timezone)).date()
    return local - timedelta(days=(local.weekday() - week_start_day) % 7)
