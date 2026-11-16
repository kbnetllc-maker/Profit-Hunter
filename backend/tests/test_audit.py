"""Regression tests for the financial and state audit (see docs/AUDIT.md).

ALL sellers, items, listings and prices are SYNTHETIC.
"""

import itertools
import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as Dec

import pytest
from sqlalchemy import select

from profit_hunter.config import Settings
from profit_hunter.db import init_db, make_engine, make_session_factory
from profit_hunter.db.models import BudgetTransaction, Purchase
from profit_hunter.engine.decision import DecisionInputs, Recommendation, decide
from profit_hunter.engine.ledger import week_start_for
from profit_hunter.engine.max_bid import bid_ladder, check_constraints, max_profitable_bid
from profit_hunter.engine.valuation import ACTIVE, SOLD, Comparable, ValuationPolicy, source_key, value_item
from profit_hunter.services import budget_service as budget, sessions_service as sessions

from .conftest import NOW, constraints, synth_sale, terms
from .test_api import new_session
from .test_comparables_api import TODAY as API_TODAY, add, analyze, new_item
from .test_services import buy, make_session

TODAY = date(2026, 11, 16)
POLICY = ValuationPolicy(undercut_rate=Dec("0.05"), active_only_discount=Dec("0.15"),
                         min_match_confidence=Dec("0.80"), max_age_days=90, min_credible=2)
_ids = itertools.count(1)


def comp(price, status=ACTIVE, match="0.95", age=0, **kw):
    return Comparable(listing_status=status, price=Dec(price), observed_on=TODAY - timedelta(days=age),
                      match_confidence=Dec(match), id=next(_ids), **kw)


def value(comps):
    return value_item(comps, POLICY, identity_confirmed=True, today=TODAY)


# ====================================================== A1 model confidence
def test_a_models_own_confidence_never_unlocks_buy():
    bid = max_profitable_bid(synth_sale("40.00"), terms(), constraints())
    claimed = decide(DecisionInputs(id_confidence=Dec("0.99"), min_id_confidence=Dec("0.90"), max_bid=bid))
    assert claimed.recommendation is Recommendation.SKIP and "not been confirmed by a person" in claimed.reasons[0]
    person = decide(DecisionInputs(id_confidence=None, min_id_confidence=Dec("0.90"), max_bid=bid,
                                   manually_confirmed=True))
    assert person.recommendation is Recommendation.BUY


# ====================================================== A2 evidence tiers
def test_owner_example_lower_asking_price_below_a_completed_sale():
    v = value([comp("30", SOLD), comp("25")])
    assert (v.lowest_credible_price, v.competitive_listing_price, v.expected_sale_price) == (
        Dec("25.00"), Dec("23.75"), Dec("20.19"))
    assert v.asking_price_discount_applied and v.supports_buy


@pytest.mark.parametrize("matches,grade,buy", [(("0.90", "0.90"), 2, True), (("0.89", "0.95"), 1, False),
                                               (("0.80", "0.85"), 0, False)])
def test_match_between_80_and_89_supports_review_only(matches, grade, buy):
    v = value([comp("30", match=matches[0]), comp("34", match=matches[1])])
    assert v.ok and v.expected_sale_price == Dec("24.23")          # the price is the same conservative figure
    assert (v.buy_grade_count, v.supports_buy) == (grade, buy)
    assert any("REVIEW only" in w for w in v.warnings) is (not buy)
    assert not value([comp("30", match="0.79"), comp("34", match="0.79")]).ok   # below 80%: excluded


@pytest.mark.parametrize("age,used,grade", [(60, True, True), (61, True, False), (90, True, False), (91, False, False)])
def test_age_tiers_60_and_90_days(age, used, grade):
    v = value([comp("30"), comp("34"), comp("20", age=age)])
    aged = v.verdicts[2]
    assert (aged.used, aged.buy_grade) == (used, grade)
    # An older comparable may lower the price but never counts toward BUY.
    assert v.lowest_credible_price == (Dec("20.00") if used else Dec("30.00"))
    assert v.buy_grade_count == (3 if grade else 2) and v.supports_buy
    assert any("more than 60 days ago" in w for w in v.warnings) is (used and not grade)
    only_old = value([comp("30", age=70), comp("34", age=70)])
    assert only_old.ok and not only_old.supports_buy


def test_weaker_evidence_can_only_lower_the_value_never_raise_it():
    strong = value([comp("30"), comp("34")])
    for extra in (comp("50", match="0.85"), comp("50", age=75), comp("28", match="0.85"), comp("28", age=75)):
        mixed = value([comp("30"), comp("34"), extra])
        assert mixed.expected_sale_price <= strong.expected_sale_price and mixed.supports_buy


def test_the_same_listing_entered_twice_counts_once():
    assert source_key("https://www.Example.com/item/42/?ref=share#top") == source_key("http://example.com/item/42")
    same = "example.com/item/42"
    v = value([comp("30", source_key=same), comp("30", source_key=same)])
    assert not v.ok and "Only 1 credible" in v.reason
    assert "counted once" in v.verdicts[1].reason
    ok = value([comp("30", source_key=same), comp("30", source_key=same), comp("34", source_key="example.com/9")])
    assert ok.ok and ok.buy_grade_count == 2


def test_possible_cross_posts_are_flagged_as_not_independent():
    v = value([comp("30", label="SYNTHETIC Jacket", source_key="a.example/1"),
               comp("30", label="synthetic jacket ", source_key="b.example/1")])
    assert v.ok and any("not independent evidence" in w for w in v.warnings)
    assert not any("independent" in w for w in value([comp("30", label="A"), comp("34", label="B")]).warnings)


def test_review_grade_comparables_give_review_not_buy_through_the_api(client):
    sid = new_session(client)["id"]
    item = new_item(client)
    add(client, item, "60.00", "SOLD", days_to_sell=10, match_confidence_pct=85)
    add(client, item, "64.00", "SOLD", days_to_sell=10, match_confidence_pct=89)
    a = analyze(client, sid, item)
    assert a["recommendation"] == "REVIEW" and "not strong enough for BUY" in a["reasons"][0]
    assert a["valuation"]["supports_buy"] is False and a["valuation"]["buy_grade_count"] == 0
    assert a["max_bid"]["max_bid"] is not None and a["authorizes_purchase"] is False
    old = (API_TODAY - timedelta(days=75)).isoformat()
    add(client, item, "62.00", "SOLD", days_to_sell=10, match_confidence_pct=95)
    add(client, item, "63.00", "SOLD", days_to_sell=10, match_confidence_pct=95, date_observed=old)
    assert analyze(client, sid, item)["recommendation"] == "REVIEW"      # one BUY-grade, one too old
    add(client, item, "61.00", "SOLD", days_to_sell=10, match_confidence_pct=90)
    b = analyze(client, sid, item)
    assert b["recommendation"] == "BUY" and b["valuation"]["buy_grade_count"] == 2
    assert b["valuation"]["lowest_credible_price"] == "60.00"            # the weaker comparable still sets the floor
    s = client.get("/api/settings").json()
    assert (s["buy_comparable_match_confidence"], s["preferred_comparable_age_days"]) == ("0.90", 60)
    s["buy_comparable_match_confidence"] = "0.70"
    assert client.put("/api/settings", json=s).status_code == 400        # cannot sit below the 80% floor


# ====================================================== A3 bid solver properties
GRID = [(p, s, t, on) for p in ("19.00", "24.23", "33.00", "40.00", "75.50") for s in ("0", "3.00", "9.00")
        for t in ("0", "0.07", "0.0925") for on in (True, False)]


def _max(price, ship, tax, on, **c):
    return max_profitable_bid(synth_sale(price), terms(ship, tax, on), constraints(**c)).max_bid or Dec("0")


@pytest.mark.parametrize("price,ship,tax,on", GRID)
def test_recommended_bid_passes_everything_and_the_next_step_fails(price, ship, tax, on):
    sale, t = synth_sale(price), terms(ship, tax, on)
    for c in (constraints(), constraints(bid_increment=Dec("0.50")),
              constraints(max_bid=Dec("40"), max_all_in_cost=Dec("60"), remaining_budget=Dec("45"),
                          increment_tiers=((Dec("10"), Dec("2")), (Dec("20"), Dec("5"))))):
        best = max_profitable_bid(sale, t, c).max_bid
        ladder = bid_ladder(c, Dec("200"))
        # Independent reference: scan every placeable bid.
        reference = [b for b in ladder if all(ch.passed for ch in check_constraints(b, sale, t, c))]
        assert best == (max(reference) if reference else None)
        if best is not None:
            assert best in ladder                                          # a bid that can actually be placed
            following = ladder[ladder.index(best) + 1]
            assert not all(ch.passed for ch in check_constraints(following, sale, t, c))


@pytest.mark.parametrize("price,ship,tax,on", GRID)
def test_higher_costs_or_stricter_rules_never_raise_the_bid(price, ship, tax, on):
    base = _max(price, ship, tax, on)
    assert _max(price, str(Dec(ship) + Dec("1.37")), tax, on) <= base           # more shipping
    assert _max(price, ship, str(Dec(tax) + Dec("0.03")), on) <= base           # more tax
    assert _max(str(Dec(price) - Dec("2.11")), ship, tax, on) <= base           # lower sale price
    assert _max(price, ship, tax, on, min_net_profit="9.50") <= base            # stricter profit
    assert _max(price, ship, tax, on, min_roi="1.5") <= base                    # stricter ROI
    assert _max(price, ship, tax, on, remaining_budget="6") <= base             # less budget
    assert _max(price, ship, tax, on, seller_exposure_remaining="4") <= base    # less seller room


# ====================================================== A4/A5 purchases: races and repeats
def test_concurrent_wins_cannot_overspend_the_weekly_budget(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'race.db'}")
    init_db(engine)
    factory = make_session_factory(engine)
    settings = Settings(purchase_tax_rate=Dec("0.07"))
    with factory() as db:
        ids = [make_session(db, f"synthetic_seller_{n}").id for n in range(8)]
    outcomes, start = [], threading.Barrier(8)

    def worker(session_id):
        from profit_hunter.db.models import SellerSession
        with factory() as db:
            session = db.get(SellerSession, session_id)
            start.wait()
            try:
                buy(db, settings, session, "10")          # $16.05 all-in each; only 3 fit in $50
                outcomes.append("ok")
            except budget.BudgetExceeded:
                outcomes.append("refused")

    threads = [threading.Thread(target=worker, args=(i,)) for i in ids]
    [t.start() for t in threads]
    [t.join() for t in threads]
    with factory() as db:
        report = budget.budget_report(db, settings, now=NOW)
    assert sorted(outcomes) == ["ok"] * 3 + ["refused"] * 5
    assert report.available == Dec("1.85") and not report.ledger.over_budget


def test_a_repeated_request_records_the_win_once(client):
    sid = new_session(client)["id"]
    body = {"description": "SYNTHETIC jacket", "winning_bid": "3", "request_id": "synthetic-request-0001"}
    first = client.post(f"/api/sessions/{sid}/purchases", json=body).json()
    again = client.post(f"/api/sessions/{sid}/purchases", json=body).json()
    assert again["id"] == first["id"]
    d = client.get("/api/dashboard").json()
    assert len(d["purchases"]) == 1 and d["pending_commitments"] == "8.72" and d["available"] == "41.28"
    other = client.post(f"/api/sessions/{sid}/purchases", json={**body, "request_id": "synthetic-request-0002"}).json()
    assert other["id"] != first["id"]
    d = client.get("/api/dashboard").json()
    assert len(d["purchases"]) == 2
    # Practice mode has its own ledger even for the same request id pattern.
    sim = new_session(client, simulated=True, seller_username="synthetic_practice")["id"]
    client.post(f"/api/sessions/{sim}/purchases", json={**body, "request_id": "synthetic-request-0003"})
    assert client.get("/api/dashboard").json()["available"] == d["available"] != client.get(
        "/api/dashboard?simulated=true").json()["available"]


def test_actual_charges_above_budget_are_recorded_honestly_then_block_new_purchases(db, settings):
    s = make_session(db)
    p = buy(db, settings, s, "10")
    budget.settle_purchase(db, p, actual_bid=Dec("10"), actual_shipping=Dec("38"), actual_tax=Dec("4.32"), now=NOW)
    report = budget.budget_report(db, settings, now=NOW)
    assert report.ledger.actual_spending == Dec("52.32") and report.ledger.over_budget
    assert report.available == Dec("-2.32")
    with pytest.raises(budget.BudgetExceeded):
        buy(db, settings, make_session(db, "synthetic_other"), "1")
    # The audit trail keeps both the original commitment and the settlement.
    kinds = [(t.kind, t.amount_cents) for t in db.scalars(select(BudgetTransaction).order_by(BudgetTransaction.id))]
    assert kinds == [("COMMIT", 1605), ("SETTLE", 5232)]
    assert db.get(Purchase, p.id).committed_total_cents == 1605            # the estimate is not overwritten


def test_bundle_shipping_is_counted_exactly_once(db, settings):
    s = make_session(db, first_item_shipping=Dec("5.00"), additional_item_shipping=Dec("1.50"), shipping_cap=Dec("7.00"))
    added = []
    for _ in range(4):
        added.append(sessions.next_item_shipping(db, settings, s).amount)
        buy(db, settings, s, "1")
    assert added == [Dec("5.00"), Dec("1.50"), Dec("0.50"), Dec("0.00")]     # capped at $7 in total
    bundle = sessions.get_open_bundle(db, s)
    shares = sessions.allocate_bundle_shipping(db, bundle)
    assert sum(added) == sessions.bundle_shipping_total(bundle) == sum(shares.values()) == Dec("7.00")
    assert sorted(shares.values()) == [Dec("1.75")] * 4                       # cost basis, split evenly


# ====================================================== A6 budget weeks
@pytest.mark.parametrize("utc,expected", [
    (datetime(2026, 3, 9, 4, 59, tzinfo=timezone.utc), date(2026, 3, 2)),    # Sun 23:59 CDT, the day clocks sprang forward
    (datetime(2026, 3, 9, 5, 0, tzinfo=timezone.utc), date(2026, 3, 9)),     # Mon 00:00 CDT
    (datetime(2026, 3, 8, 7, 59, tzinfo=timezone.utc), date(2026, 3, 2)),    # 01:59 CST, just before the jump
    (datetime(2026, 3, 8, 8, 0, tzinfo=timezone.utc), date(2026, 3, 2)),     # 03:00 CDT, just after it
    (datetime(2026, 11, 2, 5, 59, tzinfo=timezone.utc), date(2026, 10, 26)),  # Sun 23:59 CST, the day clocks fell back
    (datetime(2026, 11, 2, 6, 0, tzinfo=timezone.utc), date(2026, 11, 2)),    # Mon 00:00 CST
    (datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc), date(2026, 10, 26)),  # the first 01:30 that night
    (datetime(2026, 11, 1, 7, 30, tzinfo=timezone.utc), date(2026, 10, 26)),  # the second 01:30 that night
])
def test_week_boundaries_in_chicago_across_daylight_saving_changes(utc, expected):
    assert week_start_for(utc, 0, "America/Chicago") == expected


def test_budget_change_applies_to_this_week_only_and_never_rewrites_transactions(client):
    sid = new_session(client)["id"]
    client.post(f"/api/sessions/{sid}/purchases", json={"description": "SYNTHETIC tee", "winning_bid": "3"})
    s = client.get("/api/settings").json()
    s["weekly_budget"] = "30.00"
    assert client.put("/api/settings", json=s).status_code == 200
    d = client.get("/api/dashboard").json()
    assert (d["starting_budget"], d["pending_commitments"], d["available"]) == ("30.00", "8.72", "21.28")


def test_week_boundary_cannot_move_while_this_week_has_purchases(client):
    s = client.get("/api/settings").json()
    other_day = (API_TODAY.weekday() + 3) % 7       # a start day that puts today in a different week
    sid = new_session(client)["id"]
    p = client.post(f"/api/sessions/{sid}/purchases", json={"description": "SYNTHETIC tee", "winning_bid": "3"}).json()
    r = client.put("/api/settings", json={**s, "week_start_day": other_day})
    assert r.status_code == 400 and "begin a new budget week" in r.json()["detail"]
    assert client.get("/api/settings").json()["week_start_day"] == s["week_start_day"]
    assert client.get("/api/dashboard").json()["available"] == "41.28"        # still counted
    client.post(f"/api/purchases/{p['id']}/cancel")
    assert client.put("/api/settings", json={**s, "week_start_day": other_day}).status_code == 200


# ====================================================== A7 stale recommendations
def test_saved_recommendations_are_flagged_stale_but_never_rewritten(client):
    sid = new_session(client)["id"]
    item = new_item(client)
    first = add(client, item, "60.00", "SOLD", days_to_sell=10)
    add(client, item, "64.00", "SOLD", days_to_sell=10)
    a = analyze(client, sid, item)
    assert a["recommendation"] == "BUY" and a["stale"] is False and a["stale_reasons"] == []

    def state():
        return client.get(f"/api/analyses/{a['id']}").json()

    client.put(f"/api/comparables/{first['id']}", json={**first, "price": "20.00"})
    assert state()["stale_reasons"] == ["The comparables have changed."]
    assert state()["valuation"]["lowest_credible_price"] == "60.00"          # the snapshot itself is untouched
    client.put(f"/api/comparables/{first['id']}", json=first)
    assert state()["stale"] is False

    s = client.get("/api/settings").json()
    client.put("/api/settings", json={**s, "min_net_profit": "12.00"})
    assert state()["stale_reasons"] == ["Financial settings have changed."]
    client.put("/api/settings", json={**s, "vision_timeout_seconds": 30, "ai_pilot_allowance": "1.00"})
    assert state()["stale"] is False                                        # AI settings are not financial inputs

    p = client.post(f"/api/sessions/{sid}/purchases", json={"description": "SYNTHETIC other", "winning_bid": "2"}).json()
    assert state()["stale_reasons"] == ["The budget, seller room or shipping for the next item has changed."]
    assert state()["recommendation"] == "BUY" and state()["max_bid"]["max_bid"] == a["max_bid"]["max_bid"]
    listed = client.get("/api/opportunities").json()
    assert [(o["id"], o["stale"]) for o in listed] == [(a["id"], True)]
    client.post(f"/api/purchases/{p['id']}/cancel")
    assert state()["stale"] is False
    client.post(f"/api/sessions/{sid}/end")
    assert state()["stale_reasons"] == ["The seller session has ended."]


# ====================================================== A8 database upgrade
def test_older_database_is_upgraded_in_place_without_losing_rows(tmp_path):
    path = tmp_path / "older.db"
    engine = make_engine(f"sqlite:///{path}")
    init_db(engine)
    with make_session_factory(engine)() as db:
        buy(db, Settings(), make_session(db), "3")
    engine.dispose()
    # Turn it back into a pre-upgrade database: no request_id column, no Milestone 4 tables.
    raw = sqlite3.connect(path)
    raw.executescript("""DROP INDEX ux_purchases_request_id; ALTER TABLE purchases DROP COLUMN request_id;
                         DROP TABLE identity_confirmations; DROP TABLE ai_usage; DROP TABLE identifications;
                         DROP TABLE item_images;""")
    raw.commit()
    before = raw.execute("SELECT id, description, committed_total_cents FROM purchases").fetchall()
    raw.close()

    engine = make_engine(f"sqlite:///{path}")
    init_db(engine)
    init_db(engine)          # running it again changes nothing
    raw = sqlite3.connect(path)
    assert raw.execute("SELECT id, description, committed_total_cents FROM purchases").fetchall() == before
    assert raw.execute("SELECT request_id FROM purchases").fetchall() == [(None,)]
    tables = {r[0] for r in raw.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"item_images", "identifications", "ai_usage", "identity_confirmations"} <= tables
    assert raw.execute("SELECT COUNT(*) FROM budget_transactions").fetchone() == (1,)
    raw.close()
    with make_session_factory(engine)() as db:   # and the upgraded database works
        s = sessions.open_session(db, sessions.get_or_create_seller(db, "synthetic_seller"),
                                  first_item_shipping=Dec("5"), additional_item_shipping=Dec("0"))
        p = budget.commit_purchase(db, Settings(), s, description="SYNTHETIC", winning_bid=Dec("1"), request_id="abcdefgh")
        assert budget.commit_purchase(db, Settings(), s, description="SYNTHETIC", winning_bid=Dec("1"),
                                      request_id="abcdefgh").id == p.id
