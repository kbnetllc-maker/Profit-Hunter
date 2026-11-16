"""Shared test fixtures.

ALL DATA IN THESE TESTS IS SYNTHETIC. Sellers, prices, fees and items are
invented to exercise the logic; none of it is real market data.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from profit_hunter.config import FeeProfile, Settings
from profit_hunter.db import init_db, make_engine, make_session_factory
from profit_hunter.engine.max_bid import BidConstraints
from profit_hunter.engine.profit import PurchaseTerms, sale_proceeds

# Monday 16 Nov 2026, 3pm UTC (10am New York): safely inside one budget week.
NOW = datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc)


@pytest.fixture
def db():
    engine = make_engine("sqlite://")  # fresh in-memory database per test
    init_db(engine)
    with make_session_factory(engine)() as session:
        yield session


@pytest.fixture
def settings():
    return Settings()


# Synthetic marketplace: 13.6% + $0.40, like the default (unverified) eBay profile.
SYNTH_PROFILE = FeeProfile(name="Synthetic", percent_rate=Decimal("0.136"), fixed_fee=Decimal("0.40"),
                           fees_apply_to_buyer_shipping=True)


def synth_sale(price: str):
    """Synthetic sale: $5.50 outbound label, $0.50 packaging, 5% risk reserve."""
    return sale_proceeds(Decimal(price), SYNTH_PROFILE, outbound_shipping=Decimal("5.50"),
                         packaging=Decimal("0.50"), risk_reserve_rate=Decimal("0.05"))


def terms(shipping: str = "0", tax: str = "0.07", tax_on_shipping: bool = True):
    return PurchaseTerms(inbound_shipping=Decimal(shipping), tax_rate=Decimal(tax),
                         tax_applies_to_shipping=tax_on_shipping)


def constraints(**overrides):
    base = dict(min_net_profit=Decimal("8"), min_roi=Decimal("1"), max_bid=Decimal("10"),
                max_all_in_cost=Decimal("15"), remaining_budget=Decimal("50"),
                seller_exposure_remaining=Decimal("25"))
    base.update({k: (Decimal(v) if isinstance(v, str) else v) for k, v in overrides.items()})
    return BidConstraints(**base)
