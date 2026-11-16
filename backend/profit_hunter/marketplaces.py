"""Extension point for automatic comparable lookups.

NO automatic adapter exists in v0.1: comparables are entered by hand. An
adapter may only be added for a marketplace's documented, authorized API.
Scraping and anti-bot circumvention are not permitted.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class FoundListing:
    marketplace: str
    title: str
    source_url: str
    listing_status: str  # ACTIVE | SOLD
    price: Decimal
    shipping_price: Decimal | None
    observed_on: date


class MarketplaceAdapter(Protocol):
    name: str

    async def search(self, query: str) -> list[FoundListing]: ...


class LookupFailed(Exception):
    """A lookup produced no usable result. Never replaced with invented data."""


ADAPTERS: dict[str, MarketplaceAdapter] = {}  # empty on purpose in v0.1


async def lookup(adapter: MarketplaceAdapter, query: str, *, timeout_seconds: float = 8.0) -> list[FoundListing]:
    try:
        return await asyncio.wait_for(adapter.search(query), timeout_seconds)
    except asyncio.TimeoutError:
        raise LookupFailed(f"{adapter.name} did not answer within {timeout_seconds:g} seconds.") from None
    except Exception as exc:
        raise LookupFailed(f"{adapter.name} lookup failed: {exc}") from exc
