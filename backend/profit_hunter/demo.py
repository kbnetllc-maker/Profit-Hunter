"""Milestone 1 demonstration.

Run:  python -m profit_hunter.demo

Uses a throwaway in-memory database and SYNTHETIC data only. Nothing here
is real market data, and nothing is saved.
"""

from __future__ import annotations

import time
from decimal import Decimal

from .config import Settings
from .db import init_db, make_engine, make_session_factory
from .services import analysis_service, budget_service, sessions_service


def show(title: str, q: analysis_service.BidQuote) -> None:
    print(f"\n--- {title} ---")
    print(f"  Incremental shipping : ${q.shipping.amount:.2f}  ({q.shipping.basis})")
    if q.sale:
        s = q.sale
        print(f"  Expected sale price  : ${s.sale_price:.2f}  (conservative estimate, not an asking price)")
        print(f"  Selling expenses     : ${s.total_expenses:.2f}  (fee {s.marketplace_fee} + processing "
              f"{s.payment_processing} + label {s.outbound_shipping} + packaging {s.packaging} "
              f"+ risk {s.risk_allowance})")
        print(f"  Expected net proceeds: ${s.net_proceeds:.2f}")
    print(f"  Budget left ${q.remaining_budget:.2f} | seller room left ${q.seller_exposure_remaining:.2f}")
    if q.max_bid and q.max_bid.profit_at_max and q.decision.recommendation.value != "SKIP":
        p = q.max_bid.profit_at_max
        print(f"  MAXIMUM BID          : ${q.max_bid.max_bid:.2f}  (limited by {', '.join(q.max_bid.binding_constraints)})")
        print(f"  At that bid          : all-in ${p.acquisition.total:.2f}, profit ${p.net_profit:.2f}, "
              f"ROI {p.roi * 100:.0f}%")
    print(f"  RESULT               : {q.decision.recommendation.value}")
    for line in q.decision.reasons + [f"Warning: {w}" for w in q.decision.warnings]:
        print(f"    - {line}")


def main() -> None:
    engine = make_engine("sqlite://")
    init_db(engine)
    settings = Settings()
    print("PROFIT HUNTER - Milestone 1 demo (SYNTHETIC DATA, simulated purchases)")
    with make_session_factory(engine)() as db:
        seller = sessions_service.get_or_create_seller(db, "synthetic_seller")
        session = sessions_service.open_session(
            db, seller, first_item_shipping=Decimal("5.00"), additional_item_shipping=Decimal("0.00"),
            simulated=True)

        start = time.perf_counter()
        q1 = analysis_service.quote_bid(db, settings, session, expected_sale_price=Decimal("40"),
                                        id_confidence=Decimal("0.95"), current_bid=Decimal("1"))
        ms = (time.perf_counter() - start) * 1000
        show("Item A: $40 expected sale, first item from this seller", q1)
        print(f"  (calculated in {ms:.1f} ms, including database reads)")

        budget_service.commit_purchase(db, settings, session, description="SYNTHETIC item A",
                                       winning_bid=Decimal("5"), category="clothing",
                                       expected_net_proceeds=q1.sale.net_proceeds)
        print("\n>>> Recorded a simulated win of item A at $5.")

        show("Item B: same value, shipping now already paid",
             analysis_service.quote_bid(db, settings, session, expected_sale_price=Decimal("40"),
                                        id_confidence=Decimal("0.95")))
        show("Item C: only $18 expected sale (huge ROI, too little profit)",
             analysis_service.quote_bid(db, settings, session, expected_sale_price=Decimal("18"),
                                        id_confidence=Decimal("0.95")))
        show("Item D: identification only 70% confident",
             analysis_service.quote_bid(db, settings, session, expected_sale_price=Decimal("40"),
                                        id_confidence=Decimal("0.70")))
        show("Item E: no comparable data",
             analysis_service.quote_bid(db, settings, session, expected_sale_price=None,
                                        id_confidence=Decimal("0.95")))

        r = budget_service.budget_report(db, settings, simulated=True)
        print(f"\n=== Simulated budget, week of {r.week_start} ===")
        print(f"  Starting ${r.ledger.starting_budget:.2f} | committed ${r.ledger.pending_commitments:.2f} "
              f"| spent ${r.ledger.actual_spending:.2f} | AVAILABLE ${r.available:.2f}")
        print(f"  Projected resale proceeds ${r.projected_resale_proceeds:.2f} (projection only; not spendable)")
        real = budget_service.budget_report(db, settings, simulated=False)
        print(f"  Real budget untouched by the simulation: ${real.available:.2f} available")


if __name__ == "__main__":
    main()
