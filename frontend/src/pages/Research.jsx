import { useCallback, useEffect, useState } from "react";
import { api, orNull, usd } from "../api.js";

const BLANK_ITEM = { description: "", category: "", brand: "", model: "", size: "", condition: "" };
// "Today" comes from the server (your configured timezone), not the browser's clock.
const blankComparable = (today = "") => ({
  marketplace: "", title: "", source_url: "", listing_status: "ACTIVE", price: "", shipping_price: "",
  condition: "", size: "", variation: "", variation_status: "SAME", match_confidence_pct: "",
  days_to_sell: "", date_observed: today, included: true, decision_reason: "",
});
const STATUS_LABEL = { ACTIVE: "For sale (asking price)", SOLD: "Sold (completed sale)", AUCTION: "Auction / starting bid" };
const VARIATION_LABEL = { SAME: "Yes, the same version", PLAUSIBLE: "Not sure — my item could be this version", DIFFERENT: "No, a different version" };
const FILTERS = [["all", "All"], ["used", "Used"], ["excluded", "Not used"], ["SOLD", "Sold"], ["ACTIVE", "For sale"]];

export default function Research({ goTo, param }) {
  const [items, setItems] = useState(null);
  const [itemId, setItemId] = useState(param ? String(param) : "");
  const [page, setPage] = useState(null);
  const [newItem, setNewItem] = useState(BLANK_ITEM);
  const [form, setForm] = useState(blankComparable);
  const [editing, setEditing] = useState(null);
  const [filter, setFilter] = useState("all");
  const [error, setError] = useState("");

  const loadItems = useCallback(() => api.get("/api/items").then((rows) => {
    setItems(rows);
    return rows;
  }), []);
  const loadPage = useCallback((id) => {
    if (!id) return setPage(null);
    return api.get(`/api/items/${id}`).then((data) => {
      setPage(data);
      setForm((f) => (f.date_observed ? f : { ...f, date_observed: data.today }));
    }).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    loadItems().then((rows) => {
      if (!itemId && rows.length) setItemId(String(rows[0].id));
    }).catch((e) => setError(e.message));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    setEditing(null);
    setForm(blankComparable());
    loadPage(itemId);
  }, [itemId, loadPage]);

  async function run(action) {
    setError("");
    try {
      await action();
      await Promise.all([loadPage(itemId), loadItems()]);
      return true;
    } catch (e) {
      setError(e.message);
      return false;
    }
  }

  async function createItem(event) {
    event.preventDefault();
    setError("");
    try {
      const created = await api.post("/api/items", newItem);
      setNewItem(BLANK_ITEM);
      await loadItems();
      setItemId(String(created.id));
    } catch (e) {
      setError(e.message);
    }
  }

  const toBody = (c) => ({
    ...c, price: c.price, shipping_price: orNull(c.shipping_price), days_to_sell: orNull(c.days_to_sell),
    match_confidence_pct: Number(c.match_confidence_pct),
  });

  async function saveComparable(event) {
    event.preventDefault();
    const ok = await run(() => (editing
      ? api.put(`/api/comparables/${editing}`, toBody(form))
      : api.post(`/api/items/${itemId}/comparables`, toBody(form))));
    if (ok) {
      setEditing(null);
      setForm(blankComparable(page.today));
    }
  }

  function startEdit(c) {
    setEditing(c.id);
    setForm({ ...c, shipping_price: c.shipping_price ?? "", days_to_sell: c.days_to_sell ?? "" });
    document.getElementById("comparable-form")?.scrollIntoView({ behavior: "smooth" });
  }

  function toggle(c) {
    if (c.included) {
      const reason = window.prompt("Why should this comparable not be used?");
      if (!reason || !reason.trim()) return;
      run(() => api.put(`/api/comparables/${c.id}`, { ...c, included: false, decision_reason: reason.trim() }));
    } else {
      run(() => api.put(`/api/comparables/${c.id}`, { ...c, included: true, decision_reason: "" }));
    }
  }

  const set = (name) => (e) => setForm((f) => ({ ...f, [name]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));
  const v = page && page.valuation;
  const rows = v ? [...v.comparables_used, ...v.comparables_excluded].sort((a, b) => a.id - b.id) : [];
  const shown = rows.filter((c) => filter === "all" || (filter === "used" && c.used) || (filter === "excluded" && !c.used) || c.listing_status === filter);

  return (
    <>
      <header className="page-head">
        <h1>Comparable Research</h1>
        {page && <button className="primary" onClick={() => goTo("analyze", page.id)}>Analyze this item</button>}
      </header>
      {error && <div className="error">{error}</div>}

      <div className="grid-2">
        <section className="card">
          <h2>Item being researched</h2>
          {items === null ? <p>Loading…</p> : items.length === 0 ? <p className="muted">No items yet. Add one on the right.</p> : (
            <label>Item
              <select value={itemId} onChange={(e) => setItemId(e.target.value)}>
                {items.map((i) => <option key={i.id} value={i.id}>#{i.id} {i.description} ({i.comparable_count} comparable{i.comparable_count === 1 ? "" : "s"})</option>)}
              </select>
            </label>
          )}
          {page && (
            <p className="hint">
              {[page.brand, page.model, page.size, page.condition].filter(Boolean).join(" · ") || "No details entered."}
              {" "}Identity {page.identity.confirmed ? "confirmed by you" : "not confirmed"} (<button type="button" className="link" onClick={() => goTo("identify", page.id)}>photos and confirmation</button>). Valued for resale on <b>{page.marketplace}</b>, comparing <b>{page.price_basis}</b>.
            </p>
          )}
        </section>
        <form className="card" onSubmit={createItem}>
          <h2>Add an item to research</h2>
          <label>Description
            <input value={newItem.description} onChange={(e) => setNewItem({ ...newItem, description: e.target.value })} required placeholder="e.g. Men's Levi's 501 jeans, 34x32" />
          </label>
          <div className="row three">
            {[["brand", "Brand"], ["model", "Model / style"], ["size", "Size"]].map(([name, label]) => (
              <label key={name}>{label}<input value={newItem[name]} onChange={(e) => setNewItem({ ...newItem, [name]: e.target.value })} /></label>
            ))}
          </div>
          <div className="actions"><button type="submit">Add item</button></div>
        </form>
      </div>

      {page && v && (
        <>
          <section className={`card valuation ${v.ok ? "" : "none"}`}>
            <h2>Conservative resale value</h2>
            {v.ok ? (
              <>
                <div className="mini-stats four">
                  <div><span>A. Lowest credible comparable</span><b>{usd(v.lowest_credible_price)}</b></div>
                  <div><span>B. Competitive listing price</span><b>{usd(v.competitive_listing_price)}</b></div>
                  <div><span>C. Conservative expected sale price</span><b className="ok-text">{usd(v.expected_sale_price)}</b></div>
                  <div><span>Evidence</span><b>{v.evidence_quality}</b><span>{v.sold_count} sold · {v.active_count} for sale · {v.buy_grade_count} BUY grade</span></div>
                </div>
                <ul className="checks">{v.steps.map((s) => <li key={s}>{s}</li>)}</ul>
                <ul className="reasons">{v.warnings.map((w) => <li key={w} className="warn-text">⚠ {w}</li>)}</ul>
                <p className="hint">
                  B is the price to <b>list</b> at. C is what to <b>expect</b>; profit is calculated from C, after selling costs, on the Analyze Item page.
                  Expected time to sell: {v.expected_holding_days === null ? "unknown" : `about ${v.expected_holding_days} days (slowest recorded sale)`}.
                </p>
              </>
            ) : (
              <p><b>No valuation.</b> {v.reason} An item without a valuation is always SKIP.</p>
            )}
          </section>

          <section className="card">
            <div className="page-head">
              <h2>Comparables ({rows.length})</h2>
              <div className="segmented light">
                {FILTERS.map(([key, label]) => <button key={key} type="button" className={filter === key ? "on" : ""} onClick={() => setFilter(key)}>{label}</button>)}
              </div>
            </div>
            {shown.length === 0 ? <p className="muted">{rows.length === 0 ? "None yet. Add the listings you find below." : "No comparables match this filter."}</p> : (
              <div className="scroll-x">
                <table>
                  <thead><tr><th>Listing</th><th>Type</th><th className="num">Price</th><th className="num">Shipping</th><th className="num">Match</th><th>Observed</th><th>Used?</th><th></th></tr></thead>
                  <tbody>
                    {shown.map((c) => (
                      <tr key={c.id} className={c.used ? "" : "faded-row"}>
                        <td>
                          <a href={c.source_url} target="_blank" rel="noreferrer">{c.title}</a>
                          {c.id === v.lowest_comparable_id && <span className="tag buy">sets the price</span>}
                          <div className="hint">{[c.marketplace, c.condition, c.size, c.variation].filter(Boolean).join(" · ")}</div>
                          <div className="hint url">{c.source_url}</div>
                        </td>
                        <td><span className={`tag ${c.listing_status === "SOLD" ? "buy" : c.listing_status === "AUCTION" ? "skip" : ""}`}>{c.listing_status === "ACTIVE" ? "FOR SALE" : c.listing_status}</span>
                          {c.days_to_sell !== null && <div className="hint">sold in {c.days_to_sell} d</div>}</td>
                        <td className="num">{usd(c.price)}</td>
                        <td className="num">{c.shipping_price === null ? "unknown" : usd(c.shipping_price)}</td>
                        <td className="num">{c.match_confidence_pct}%</td>
                        <td className="nowrap">{c.date_observed}</td>
                        <td><span className={`tag ${c.used ? "buy" : "skip"}`}>{c.used ? "USED" : "NOT USED"}</span>{c.used && !c.buy_grade && <span className="tag warn">review only</span>}<div className="hint">{c.verdict}</div></td>
                        <td className="num">
                          <button className="link" onClick={() => toggle(c)}>{c.included ? "Reject" : "Restore"}</button>{" "}
                          <button className="link" onClick={() => startEdit(c)}>Edit</button>{" "}
                          <button className="link" onClick={() => window.confirm("Delete this comparable? Use Reject instead to keep it on record.") && run(() => api.delete(`/api/comparables/${c.id}`))}>Delete</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <form className="card" id="comparable-form" onSubmit={saveComparable}>
            <h2>{editing ? "Edit comparable" : "Add a comparable you found"}</h2>
            <p className="hint">Enter only listings you have actually seen, exactly as shown. Automatic lookups are not connected; nothing is fetched for you.</p>
            <div className="row three">
              <label>Marketplace<input value={form.marketplace} onChange={set("marketplace")} required placeholder="e.g. Vinted" /></label>
              <label className="span-2">Listing title<input value={form.title} onChange={set("title")} required /></label>
              <label className="span-2">Link to the listing<input type="url" value={form.source_url} onChange={set("source_url")} required placeholder="https://…" /></label>
              <label>Date you saw it<input type="date" value={form.date_observed} max={page.today} onChange={set("date_observed")} required /></label>
              <label>Listing type
                <select value={form.listing_status} onChange={set("listing_status")}>
                  {Object.entries(STATUS_LABEL).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                </select>
              </label>
              <label>{form.listing_status === "SOLD" ? "Sold price ($)" : "Asking price ($)"}<input inputMode="decimal" value={form.price} onChange={set("price")} required /></label>
              <label>Shipping the buyer pays ($)<input inputMode="decimal" value={form.shipping_price} onChange={set("shipping_price")} placeholder="unknown" /></label>
              <label>Condition<input value={form.condition} onChange={set("condition")} /></label>
              <label>Size<input value={form.size} onChange={set("size")} /></label>
              <label>Version / variation<input value={form.variation} onChange={set("variation")} placeholder="e.g. made in USA, lined" /></label>
              <label>Is it the same version as your item?
                <select value={form.variation_status} onChange={set("variation_status")}>
                  {Object.entries(VARIATION_LABEL).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                </select>
              </label>
              <label>How closely does it match? (0–100%)<input inputMode="numeric" value={form.match_confidence_pct} onChange={set("match_confidence_pct")} required placeholder="e.g. 95" /></label>
              {form.listing_status === "SOLD" && <label>Days it took to sell<input inputMode="numeric" value={form.days_to_sell} onChange={set("days_to_sell")} placeholder="unknown" /></label>}
            </div>
            {form.listing_status === "AUCTION" && <div className="notice">An auction price or starting bid is kept on record but is never used as evidence of value.</div>}
            <label className="check"><input type="checkbox" checked={form.included} onChange={set("included")} /> Use this comparable</label>
            <label>{form.included ? "Why it is a fair comparison (optional)" : "Why it should not be used (required)"}
              <input value={form.decision_reason} onChange={set("decision_reason")} required={!form.included} />
            </label>
            <div className="actions">
              <button className="primary" type="submit">{editing ? "Save changes" : "Add comparable"}</button>
              {editing && <button type="button" onClick={() => { setEditing(null); setForm(blankComparable(page.today)); }}>Cancel edit</button>}
            </div>
          </form>
        </>
      )}
    </>
  );
}
