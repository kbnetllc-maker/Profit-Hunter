"""API tests. All sellers, items and prices are SYNTHETIC."""


def new_session(client, **kw):
    body = {"seller_username": "synthetic_seller", "first_item_shipping": "5.00",
            "additional_item_shipping": "0.00", **kw}
    r = client.post("/api/sessions", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def analyze(client, session_id, **kw):
    body = {"session_id": session_id, "item": {"description": "SYNTHETIC jacket", "manually_confirmed": True},
            "expected_sale_price": "20.00", **kw}
    r = client.post("/api/analyze", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_settings_round_trip_and_validation(client):
    s = client.get("/api/settings").json()
    assert s["weekly_budget"] == "50.00" and s["timezone"] == "America/Chicago"
    s["weekly_budget"] = "65.00"
    assert client.put("/api/settings", json=s).json()["weekly_budget"] == "65.00"
    assert client.get("/api/dashboard").json()["starting_budget"] == "65.00"
    # Changing the budget mid-week applies to the week already in progress.
    s["weekly_budget"] = "40.00"
    client.put("/api/settings", json=s)
    assert client.get("/api/dashboard").json()["starting_budget"] == "40.00"

    s["auto_purchase_enabled"] = True
    r = client.put("/api/settings", json=s)
    assert r.status_code == 400 and "Automatic purchasing" in r.json()["detail"]
    assert client.get("/api/settings").json()["auto_purchase_enabled"] is False


def test_analyze_gives_full_explanation_and_is_saved(client):
    sid = new_session(client)["id"]
    a = analyze(client, sid, current_bid="1")
    # Vinted default (unverified assumption): $20 - $0.50 packaging - $1.00 risk = $18.50 net.
    assert a["recommendation"] == "BUY" and a["authorizes_purchase"] is False
    assert a["sale"]["net_proceeds"] == "18.50"
    assert a["max_bid"]["max_bid"] == "3.00" and a["max_bid"]["binding_constraints"] == ["min_roi"]
    assert a["at_max_bid"]["all_in_cost"] == "8.72" and a["at_max_bid"]["net_profit"] == "9.78"
    assert a["next_bid"] == "2.00" and a["at_next_bid"]["all_in_cost"] == "7.63"
    assert a["remaining_budget"] == "50.00" and a["shipping"]["amount"] == "5.00"

    saved = client.get(f"/api/analyses/{a['id']}").json()
    assert saved["inputs"]["settings"]["purchase_tax_rate"] == "0.09"  # audit trail
    assert saved["max_bid"]["max_bid"] == "3.00"
    assert len(client.get("/api/analyses").json()) == 1


def test_analyze_skip_cases(client):
    sid = new_session(client)["id"]
    assert analyze(client, sid, expected_sale_price=None)["recommendation"] == "SKIP"
    unconfirmed = {"description": "SYNTHETIC jacket", "manually_confirmed": False}
    assert analyze(client, sid, item=unconfirmed)["recommendation"] == "SKIP"
    assert analyze(client, sid, item=unconfirmed, valuation_is_lower_bound=True)["recommendation"] == "REVIEW"
    assert analyze(client, sid, suspected_counterfeit=True)["recommendation"] == "SKIP"
    assert analyze(client, sid, current_bid="3")["recommendation"] == "SKIP"  # next bid $4 > max $3
    assert analyze(client, sid, marketplace="ebay")["recommendation"] == "SKIP"  # fees leave too little
    assert client.post("/api/analyze", json={"session_id": 999, "item": {"description": "x"}}).status_code == 404


def test_purchase_flow_updates_dashboard_and_blocks_overspending(client):
    sid = new_session(client)["id"]
    p = client.post(f"/api/sessions/{sid}/purchases", json={
        "description": "SYNTHETIC jacket", "winning_bid": "3", "category": "clothing",
        "expected_net_proceeds": "18.50"}).json()
    assert p["total"] == "8.72" and p["status"] == "COMMITTED"

    d = client.get("/api/dashboard").json()
    assert (d["available"], d["pending_commitments"], d["expected_profit"]) == ("41.28", "8.72", "9.78")
    assert d["seller_exposure"] == {"synthetic_seller": "8.72"} and d["purchases_by_category"] == {"clothing": "8.72"}
    assert d["active_sessions"][0]["next_item_shipping"]["amount"] == "0.00"

    # A second $15 win would push this seller past the $25 exposure limit.
    r = client.post(f"/api/sessions/{sid}/purchases", json={"description": "SYNTHETIC coat", "winning_bid": "15"})
    assert r.status_code == 409 and "exposure" in r.json()["detail"]

    settled = client.post(f"/api/purchases/{p['id']}/settle", json={
        "actual_bid": "3", "actual_shipping": "5.25", "actual_tax": "0.74"}).json()
    assert settled["total"] == "8.99" and settled["amounts_are_actual"] is True
    d = client.get("/api/dashboard").json()
    assert (d["available"], d["pending_commitments"], d["actual_spending"]) == ("41.01", "0.00", "8.99")
    assert client.post(f"/api/purchases/{p['id']}/cancel").status_code == 400  # already settled


def test_simulated_and_real_are_separate_in_the_api(client):
    sim = new_session(client, simulated=True)["id"]
    client.post(f"/api/sessions/{sim}/purchases", json={"description": "SYNTHETIC tee", "winning_bid": "2"})
    assert client.get("/api/dashboard").json()["available"] == "50.00"
    assert client.get("/api/dashboard?simulated=true").json()["available"] == "42.37"
    assert client.get("/api/sessions").json() == []
    assert len(client.get("/api/sessions?simulated=true").json()) == 1


def test_session_shipping_terms_bundle_close_and_end(client):
    sid = new_session(client, additional_item_shipping=None)["id"]
    client.post(f"/api/sessions/{sid}/purchases", json={"description": "SYNTHETIC tee", "winning_bid": "1"})
    s = client.get(f"/api/sessions/{sid}").json()
    assert s["next_item_shipping"] == {"amount": "3.00", "is_estimate": True, "basis": s["next_item_shipping"]["basis"]}

    s = client.put(f"/api/sessions/{sid}/shipping", json={
        "first_item_shipping": "5.00", "additional_item_shipping": "1.00", "shipping_cap": "5.50"}).json()
    assert s["next_item_shipping"]["amount"] == "0.50" and s["next_item_shipping"]["is_estimate"] is False

    s = client.post(f"/api/sessions/{sid}/close-bundle").json()
    assert s["bundle_open"] is False and s["next_item_shipping"]["amount"] == "5.00"
    assert client.post(f"/api/sessions/{sid}/close-bundle").status_code == 400

    assert client.post(f"/api/sessions/{sid}/end").json()["status"] == "ENDED"
    r = client.post(f"/api/sessions/{sid}/purchases", json={"description": "x", "winning_bid": "1"})
    assert r.status_code == 400 and "ended" in r.json()["detail"]
