"""Application settings and their defaults.

Every operating parameter lives here and is user-configurable. The values
are saved in the database (see ``services/settings_service.py``).

IMPORTANT: marketplace fee profiles, tax rate and shipping estimates below
are PRELIMINARY ASSUMPTIONS, not verified facts. Check each marketplace's
current fee page and your own state's tax rate before relying on them.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class VisionPrice(BaseModel):
    """A dated, published price for one vision model (US dollars per million tokens)."""

    model_config = ConfigDict(frozen=True)
    model: str
    input_per_million: Decimal = Field(ge=0)
    output_per_million: Decimal = Field(ge=0)  # reasoning tokens are counted in output tokens
    effective_from: date
    verified_on: date | None = None  # when a person or developer last checked the source
    source: str = ""


def default_vision_prices() -> list[VisionPrice]:
    checked = date(2026, 11, 16)
    return [
        VisionPrice(model="gpt-6-luna", input_per_million=Decimal("0.10"), output_per_million=Decimal("0.50"),
                    effective_from=checked, verified_on=checked,
                    source="https://developers.openai.com/api/docs/models/gpt-6-luna (Standard rate)"),
        VisionPrice(model="gpt-6.1-terra", input_per_million=Decimal("1.00"), output_per_million=Decimal("5.00"),
                    effective_from=checked, verified_on=checked,
                    source="https://developers.openai.com/api/docs/models/gpt-6.1-terra (Standard rate)"),
    ]


VISION_PROVIDERS = ("mock", "openai")


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

    # --- AI identification (vision) ---------------------------------------
    # These are the OPERATOR'S AI costs. They are tracked separately and are
    # never part of the inventory purchasing budget above.
    vision_provider: str = "mock"  # "mock" (no network, no cost) or "openai"
    # Live calls need this switch AND an API key in the server environment.
    vision_live_enabled: bool = False
    vision_primary_model: str = "gpt-6-luna"
    vision_review_model: str = "gpt-6.1-terra"  # used only by "Request second look"
    vision_supported_reasoning: list[str] = Field(
        default_factory=lambda: ["none", "low", "medium", "high", "xhigh", "max"])
    vision_primary_reasoning: str = "low"
    vision_review_reasoning: str = "low"
    # Output limits include reasoning tokens; both are billed as output.
    vision_primary_max_output_tokens: int = Field(default=2000, ge=200, le=20000)
    vision_review_max_output_tokens: int = Field(default=1500, ge=200, le=20000)
    vision_timeout_seconds: int = Field(default=60, ge=5, le=300)
    vision_max_retries: int = Field(default=1, ge=0, le=1)
    # Images are scaled down so the longest side is at most this many pixels.
    vision_image_max_side: int = Field(default=1280, ge=256, le=4096)
    # Image tokens = 32px patches x multiplier. UNVERIFIED for the two default
    # models (the vendor's table does not list them), hence the safety factor
    # applied to every cost reservation until real usage has been measured.
    vision_image_token_multiplier: Decimal = Decimal("1.2")
    vision_reservation_safety_factor: Decimal = Decimal("1.5")
    # Total AI allowance for this workspace. Never resets or tops up by itself.
    ai_pilot_allowance: Decimal = Decimal("2.00")
    # Most that one item's analyses may cost in total (second look and retries included).
    ai_max_cost_per_item: Decimal = Decimal("0.02")
    vision_prices: list[VisionPrice] = Field(default_factory=default_vision_prices)

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

    @field_validator("vision_provider")
    @classmethod
    def _known_provider(cls, v: str) -> str:
        if v not in VISION_PROVIDERS:
            raise ValueError(f"must be one of {', '.join(VISION_PROVIDERS)}")
        return v

    @field_validator("vision_image_token_multiplier", "vision_reservation_safety_factor")
    @classmethod
    def _at_least_one(cls, v: Decimal) -> Decimal:
        if v < 1:
            raise ValueError("must be at least 1")
        return v

    @model_validator(mode="after")
    def _reasoning_is_supported(self) -> "Settings":
        for name in ("vision_primary_reasoning", "vision_review_reasoning"):
            if getattr(self, name) not in self.vision_supported_reasoning:
                raise ValueError(f"{name} must be one of {', '.join(self.vision_supported_reasoning)}")
        for name in ("vision_primary_model", "vision_review_model"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        return self

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
        "ai_pilot_allowance", "ai_max_cost_per_item",
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
