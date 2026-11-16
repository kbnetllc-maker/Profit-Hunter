"""Application settings and their defaults.

Every operating parameter lives here and is user-configurable. The values
are saved in the database (see ``services/settings_service.py``).

IMPORTANT: marketplace fee profiles, tax rate and shipping estimates below
are PRELIMINARY ASSUMPTIONS, not verified facts. Check each marketplace's
current fee page and your own state's tax rate before relying on them.
"""

from __future__ import annotations

from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FeeProfile(BaseModel):
    """How one resale marketplace charges the seller."""

    model_config = ConfigDict(frozen=True)

    name: str
    # Percentage fee, charged on the fee base (item price, plus buyer-paid
    # shipping when ``fees_apply_to_buyer_shipping`` is true).
    percent_rate: Decimal = Decimal("0")
    fixed_fee: Decimal = Decimal("0")
    # Optional tier: when the fee base is below the threshold, a flat fee
    # replaces the percentage + fixed fee.
    flat_fee_threshold: Decimal | None = None
    flat_fee: Decimal | None = None
    # Separate payment processing, charged on everything the buyer pays.
    processing_rate: Decimal = Decimal("0")
    processing_fixed: Decimal = Decimal("0")
    fees_apply_to_buyer_shipping: bool = False
    # Outbound label cost the SELLER pays on this marketplace. None = use the
    # general default. 0 = the buyer pays for shipping on top of the item price.
    seller_paid_outbound_shipping: Decimal | None = None
    verified: bool = False
    notes: str = ""


def default_fee_profiles() -> dict[str, FeeProfile]:
    note = "Unverified placeholder. Confirm against the marketplace's current fee page."
    return {
        "ebay": FeeProfile(
            name="eBay",
            percent_rate=Decimal("0.136"),
            fixed_fee=Decimal("0.40"),
            fees_apply_to_buyer_shipping=True,
            notes=note,
        ),
        "poshmark": FeeProfile(
            name="Poshmark",
            percent_rate=Decimal("0.20"),
            flat_fee_threshold=Decimal("15.00"),
            flat_fee=Decimal("2.95"),
            notes=note,
        ),
        "mercari": FeeProfile(name="Mercari", percent_rate=Decimal("0.10"), notes=note),
        "depop": FeeProfile(
            name="Depop",
            processing_rate=Decimal("0.033"),
            processing_fixed=Decimal("0.45"),
            notes=note,
        ),
        "vinted": FeeProfile(
            name="Vinted",
            seller_paid_outbound_shipping=Decimal("0"),
            notes=note + " Assumes no seller fees and that the buyer pays shipping, so the "
                         "expected sale price is the ITEM price only.",
        ),
    }


class BidIncrementTier(BaseModel):
    """From ``from_bid`` upward, bids go up in steps of ``increment``."""

    model_config = ConfigDict(frozen=True)
    from_bid: Decimal = Field(ge=0)
    increment: Decimal = Field(gt=0)


class Settings(BaseModel):
    """All user-configurable parameters, with the v0.1 defaults."""

    # --- Budget and risk limits -------------------------------------------
    weekly_budget: Decimal = Decimal("50.00")
    max_bid: Decimal = Decimal("10.00")
    max_all_in_cost: Decimal = Decimal("15.00")
    min_net_profit: Decimal = Decimal("8.00")
    min_roi: Decimal = Decimal("1.00")  # 1.00 = 100%
    preferred_roi: Decimal = Decimal("2.00")  # 2.00 = 200%
    max_seller_exposure: Decimal = Decimal("25.00")
    min_id_confidence: Decimal = Decimal("0.90")

    # Automatic purchasing is not implemented in v0.1 and cannot be enabled.
    auto_purchase_enabled: bool = False
    # A BUY recommendation never authorizes a purchase; a person must approve.
    human_approval_required: bool = True

    # --- Budget week ------------------------------------------------------
    week_start_day: int = Field(default=0, ge=0, le=6)  # 0 = Monday ... 6 = Sunday
    timezone: str = "America/Chicago"

    # --- Bidding ----------------------------------------------------------
    bid_increment: Decimal = Decimal("1.00")
    min_bid: Decimal = Decimal("1.00")
    # Larger bid steps at higher prices, e.g. from $20 up, steps of $2.
    # Empty = ``bid_increment`` applies at every price. The real Whatnot
    # thresholds are not confirmed; fill these in once known.
    bid_increment_tiers: list[BidIncrementTier] = Field(default_factory=list)

    # --- Buying costs -----------------------------------------------------
    purchase_tax_rate: Decimal = Decimal("0.09")
    tax_applies_to_shipping: bool = True
    # Used only when the seller's real shipping terms are unknown.
    unknown_first_item_shipping_estimate: Decimal = Decimal("9.00")
    unknown_additional_item_shipping_estimate: Decimal = Decimal("3.00")

    # --- Pricing assumptions (preliminary; calibrate from real sales) -----
    undercut_rate: Decimal = Decimal("0.05")
    active_only_discount: Decimal = Decimal("0.15")
    risk_reserve_rate: Decimal = Decimal("0.05")

    # --- Comparable evidence rules (preliminary; calibrate from real sales)
    # A comparable below this match confidence is not used.
    min_comparable_match_confidence: Decimal = Decimal("0.80")
    # A comparable observed longer ago than this is not used.
    max_comparable_age_days: int = Field(default=90, ge=1)
    # Fewer credible comparables than this means no valuation (SKIP).
    min_credible_comparables: int = Field(default=2, ge=1)
    # Longer expected time to sell than this is rejected as holding risk.
    max_expected_holding_days: int = Field(default=90, ge=1)

    # --- Selling costs ----------------------------------------------------
    # The expected sale price is the TOTAL the buyer pays (item + shipping),
    # so the outbound shipping label is a cost we pay out of it.
    default_sale_marketplace: str = "vinted"
    default_outbound_shipping: Decimal = Decimal("5.50")
    default_packaging_cost: Decimal = Decimal("0.50")
    fee_profiles: dict[str, FeeProfile] = Field(default_factory=default_fee_profiles)

    @field_validator("auto_purchase_enabled")
    @classmethod
    def _no_auto_purchase(cls, v: bool) -> bool:
        if v:
            raise ValueError("Automatic purchasing is disabled in Profit Hunter v0.1.")
        return v

    @field_validator("human_approval_required")
    @classmethod
    def _approval_required(cls, v: bool) -> bool:
        if not v:
            raise ValueError("Human approval cannot be turned off in Profit Hunter v0.1.")
        return v

    @field_validator("timezone")
    @classmethod
    def _valid_timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except Exception:
            raise ValueError(f"Unknown timezone '{v}'. Use a name like 'America/New_York'.") from None
        return v

    @field_validator(
        "weekly_budget", "max_bid", "max_all_in_cost", "min_net_profit", "min_roi",
        "preferred_roi", "max_seller_exposure", "purchase_tax_rate",
        "unknown_first_item_shipping_estimate", "unknown_additional_item_shipping_estimate",
        "undercut_rate", "active_only_discount", "risk_reserve_rate",
        "default_outbound_shipping", "default_packaging_cost",
    )
    @classmethod
    def _non_negative(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError("must not be negative")
        return v

    @field_validator("bid_increment", "min_bid")
    @classmethod
    def _positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("must be greater than zero")
        return v

    @field_validator("undercut_rate", "active_only_discount", "risk_reserve_rate")
    @classmethod
    def _below_one(cls, v: Decimal) -> Decimal:
        if v >= 1:
            raise ValueError("must be below 1 (0.05 = 5%)")
        return v

    @field_validator("min_id_confidence", "min_comparable_match_confidence")
    @classmethod
    def _fraction(cls, v: Decimal) -> Decimal:
        if not (0 <= v <= 1):
            raise ValueError("must be between 0 and 1 (0.90 = 90%)")
        return v

    def outbound_shipping_for(self, marketplace: str | None = None) -> Decimal:
        own = self.fee_profile(marketplace).seller_paid_outbound_shipping
        return self.default_outbound_shipping if own is None else own

    def increment_tiers(self) -> tuple[tuple[Decimal, Decimal], ...]:
        return tuple((t.from_bid, t.increment) for t in self.bid_increment_tiers)

    def fee_profile(self, marketplace: str | None = None) -> FeeProfile:
        key = (marketplace or self.default_sale_marketplace).lower()
        if key not in self.fee_profiles:
            raise KeyError(f"No fee profile configured for marketplace '{key}'.")
        return self.fee_profiles[key]
