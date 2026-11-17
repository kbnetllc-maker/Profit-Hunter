"""Comparable research through the web API.

ALL items, listings, links and prices are SYNTHETIC. The example.com links
do not point at real listings.
"""

from datetime import timedelta

from profit_hunter.config import Settings
from profit_hunter.services import valuation_service

from .test_api import new_session

TODAY = valuation_service.today_for(Settings())


def new_item(client, **kw):
    r = client.post("/api/items", json={"description": "SYNTHETIC denim jacket", "manually_confirmed": True, **kw})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def add(client, item_id, price, status="ACTIVE", expect=200, **kw):
    body = {"marketplace": "Vinted", "title": f"SYNTHETIC listing at {price}",
            "source_url": f"https://example.com/synthetic/{price}", "listing_status": status,
            "price": price, "match_confidence_pct": 95, "date_observed": TODAY.isoformat(), **kw}
    r = client.post(f"/api/items/{item_id}/comparables", json=body)
    assert r.status_code == expect, r.text
    return r.json()


def analyze(client, session_id, item_id, **kw):
    body = {"session_id": session_id, "item_id": item_id, "use_comparables": True,
            "item": {"description": "SYNTHETIC denim jacket", "manually_confirmed": True}, **kw}
    r = client.post("/api/analyze", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_comparables_are_stored_with_every_required_field(client):
    item = new_item(client)
    c = add(client, item, "30.00", shipping_price="4.50", condition="good", size="M",
            variation="trucker", decision_reason="same cut and wash")
    assert c == {
        "id": c["id"], "item_id": item, "marketplace": "vinted", "title": "SYNTHETIC listing at 30.00",
        "source_url": "https://example.com/synthetic/30.00", "listing_status": "ACTIVE", "price": "30.00",
        "shipping_price": "4.50", "condition": "good", "size": "M", "variation": "trucker",
        "variation_status": "SAME", "match_confidence_pct": 95, "days_to_sell": None,
        "date_observed": TODAY.isoformat(), "included": True, "decision_reason": "same cut and wash"}
    assert client.get("/api/items").json()[0]["comparable_count"] == 1
    # Unknown shipping and confirmed free shipping stay different.
    assert add(client, item, "31.00")["shipping_price"] is None
    assert add(client, item, "32.00", shipping_price="0")["shipping_price"] == "0.00"


def test_invalid_comparables_are_refused(client):
    item = new_item(client)
    add(client, item, "30", source_url="not a link", expect=422)
    add(client, item, "30", source_url="", expect=422)
    add(client, item, "0", expect=422)
    add(client, item, "30", listing_status="GUESS", expect=422)
    add(client, item, "30", match_confidence_pct=101, expect=422)
    add(client, item, "30", date_observed=(TODAY + timedelta(days=1)).isoformat(), expect=400)
    add(client, item, "30", included=False, expect=400)  # rejection needs a reason
    add(client, 999, "30", expect=404)
    assert client.get(f"/api/items/{item}").json()["comparables"] == []


def test_valuation_updates_as_comparables_are_added_rejected_and_removed(client):
    item = new_item(client)
    v = client.get(f"/api/items/{item}").json()["valuation"]
    assert v["ok"] is False and v["expected_sale_price"] is None

    low = add(client, item, "30.00")
    assert "at least 2" in client.get(f"/api/items/{item}").json()["valuation"]["reason"]
    add(client, item, "34.00")
    page = client.get(f"/api/items/{item}").json()
    v = page["valuation"]
    assert page["price_basis"] == "item price only" and page["marketplace"] == "vinted"
    assert (v["lowest_credible_price"], v["competitive_listing_price"], v["expected_sale_price"]) == (
        "30.00", "28.50", "24.23")
    assert v["asking_price_discount_applied"] is True and v["evidence_quality"] == "WEAK"
    assert v["lowest_comparable_id"] == low["id"] and len(v["steps"]) == 3

    add(client, item, "32.00", "SOLD", days_to_sell=12)
    v = client.get(f"/api/items/{item}").json()["valuation"]
    # The $30 asking price still sets the value, so it keeps the asking-price discount.
    assert v["expected_sale_price"] == "24.23" and v["expected_holding_days"] == 12
    assert v["asking_price_discount_applied"] is True and v["evidence_quality"] == "MODERATE"

    # Reject the lowest listing: the next lowest credible price takes over.
    r = client.put(f"/api/comparables/{low['id']}", json={**low, "included": False, "decision_reason": "torn cuff"})
    assert r.status_code == 200
    v = client.get(f"/api/items/{item}").json()["valuation"]
    assert v["lowest_credible_price"] == "32.00" and v["expected_sale_price"] == "30.40"
    assert v["comparables_excluded"][0]["verdict"] == "Rejected by you: torn cuff"

    assert client.delete(f"/api/comparables/{low['id']}").json() == {"deleted": low["id"]}
    assert len(client.get(f"/api/items/{item}").json()["comparables"]) == 2
    assert client.delete(f"/api/comparables/{low['id']}").status_code == 404


def test_analysis_from_comparables_explains_and_preserves_its_evidence(client):
    sid = new_session(client)["id"]
    item = new_item(client)
    first = add(client, item, "30.00")
    add(client, item, "34.00")
    add(client, item, "1.00", "AUCTION")
    a = analyze(client, sid, item, current_bid="1")

    assert a["recommendation"] == "BUY" and a["authorizes_purchase"] is False and a["item_id"] == item
    assert a["valuation"]["source"] == "Comparables" and a["valuation"]["expected_sale_price"] == "24.23"
    # $24.23 - $0.73 fee (3%) - $0.50 packaging - $1.21 risk reserve = $21.79 net.
    assert a["sale"]["expected_sale_price"] == "24.23" and a["sale"]["net_proceeds"] == "21.79"
    # A $5 bid would cost $10.90 for $10.89 profit: just under 100% ROI. So the maximum is $4.
    assert a["max_bid"]["max_bid"] == "4.00" and a["at_max_bid"]["all_in_cost"] == "9.81"
    assert a["at_max_bid"]["net_profit"] == "11.98"
    assert len(a["valuation"]["comparables_used"]) == 2 and len(a["valuation"]["comparables_excluded"]) == 1
    assert any("asking prices only" in w for w in a["warnings"])
    assert any("Time to sell is unknown" in w for w in a["warnings"])
    assert 0 < float(a["ranking"]["score"]) <= 100

    # The saved analysis keeps the evidence even after the comparable is deleted.
    client.delete(f"/api/comparables/{first['id']}")
    saved = client.get(f"/api/analyses/{a['id']}").json()
    used = saved["valuation"]["comparables_used"]
    assert [c["source_url"] for c in used] == ["https://example.com/synthetic/30.00",
                                               "https://example.com/synthetic/34.00"]
    assert saved["valuation"]["valuation_id"] == 1


def test_analysis_skips_when_comparables_cannot_support_a_valuation(client):
    sid = new_session(client)["id"]
    item = new_item(client)
    add(client, item, "30.00")
    a = analyze(client, sid, item)
    assert a["recommendation"] == "SKIP" and a["sale"] is None and a["max_bid"] is None
    assert any("at least 2" in r for r in a["reasons"])
    # A typed-in price is ignored when comparables were asked for.
    assert analyze(client, sid, item, expected_sale_price="500")["recommendation"] == "SKIP"

    r = client.post("/api/analyze", json={"session_id": sid, "use_comparables": True,
                                          "item": {"description": "SYNTHETIC"}})
    assert r.status_code == 400 and "researched item" in r.json()["detail"]


def test_slow_selling_item_is_skipped_for_holding_risk(client):
    sid = new_session(client)["id"]
    item = new_item(client)
    add(client, item, "40.00", "SOLD", days_to_sell=120)
    add(client, item, "42.00", "SOLD", days_to_sell=20)
    a = analyze(client, sid, item)
    assert a["recommendation"] == "SKIP" and "holding risk" in a["reasons"][0]
    assert a["valuation"]["expected_holding_days"] == 120


def test_unconfirmed_item_needs_lower_bound_comparables_for_review(client):
    sid = new_session(client)["id"]
    item = new_item(client, manually_confirmed=False)
    add(client, item, "60.00", "SOLD", days_to_sell=10)
    add(client, item, "64.00", "SOLD", days_to_sell=10)
    add(client, item, "40.00", "SOLD", days_to_sell=10, variation_status="PLAUSIBLE")
    unsure = {"description": "SYNTHETIC denim jacket", "manually_confirmed": False}
    assert analyze(client, sid, item, item=unsure)["recommendation"] == "SKIP"
    a = analyze(client, sid, item, item=unsure, valuation_is_lower_bound=True)
    assert a["recommendation"] == "REVIEW" and a["valuation"]["lowest_credible_price"] == "40.00"
    confirmed = analyze(client, sid, item)
    assert confirmed["recommendation"] == "BUY" and confirmed["valuation"]["lowest_credible_price"] == "60.00"


def test_opportunities_rank_latest_analysis_per_item_best_first(client):
    sid = new_session(client)["id"]
    weak, strong, bad = new_item(client), new_item(client), new_item(client)
    for price in ("30.00", "34.00"):
        add(client, weak, price)
        add(client, strong, price, "SOLD", days_to_sell=7)
    analyze(client, sid, weak)
    analyze(client, sid, weak)          # re-analysis: only the latest counts
    analyze(client, sid, strong)
    analyze(client, sid, bad)           # SKIP: never listed
    ranked = client.get("/api/opportunities").json()
    assert [r["item_id"] for r in ranked] == [strong, weak]
    assert float(ranked[0]["ranking"]["score"]) > float(ranked[1]["ranking"]["score"])
    assert client.get("/api/opportunities?simulated=true").json() == []
    client.post(f"/api/sessions/{sid}/end")
    assert client.get("/api/opportunities").json() == []


def test_evidence_rules_are_editable_settings(client):
    item = new_item(client)
    add(client, item, "30.00")
    s = client.get("/api/settings").json()
    assert (s["min_credible_comparables"], s["max_comparable_age_days"], s["max_expected_holding_days"],
            s["min_comparable_match_confidence"]) == (2, 90, 90, "0.80")
    s.update(min_credible_comparables=1, undercut_rate="0.10", active_only_discount="0.20")
    assert client.put("/api/settings", json=s).status_code == 200
    v = client.get(f"/api/items/{item}").json()["valuation"]
    assert (v["competitive_listing_price"], v["expected_sale_price"]) == ("27.00", "21.60")
    s["min_credible_comparables"] = 0
    assert client.put("/api/settings", json=s).status_code == 400
    s.update(min_credible_comparables=1, undercut_rate="1")
    assert client.put("/api/settings", json=s).status_code == 400
