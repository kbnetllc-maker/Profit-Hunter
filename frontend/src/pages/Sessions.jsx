import { useCallback, useEffect, useState } from "react";
import { api, orNull, usd } from "../api.js";

const BLANK = { seller_username: "", show_url: "", first_item_shipping: "", additional_item_shipping: "", shipping_cap: "", weekly_bundling: false };

export default function Sessions({ simulated }) {
  const [sessions, setSessions] = useState(null);
  const [form, setForm] = useState(BLANK);
  const [error, setError] = useState("");
  const [showEnded, setShowEnded] = useState(false);

  const load = useCallback(() => {
    api.get(`/api/sessions?simulated=${simulated}`).then(setSessions).catch((e) => setError(e.message));
  }, [simulated]);
  useEffect(load, [load]);

  async function create(event) {
    event.preventDefault();
    setError("");
    try {
      await api.post("/api/sessions", {
        seller_username: form.seller_username, show_url: orNull(form.show_url),
        first_item_shipping: orNull(form.first_item_shipping),
        additional_item_shipping: orNull(form.additional_item_shipping),
        shipping_cap: orNull(form.shipping_cap), weekly_bundling: form.weekly_bundling, simulated,
      });
      setForm(BLANK);
      load();
    } catch (e) {
      setError(e.message);
    }
  }

  const set = (name) => (e) => setForm((f) => ({ ...f, [name]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));
  const active = (sessions || []).filter((s) => s.status === "ACTIVE");
  const ended = (sessions || []).filter((s) => s.status !== "ACTIVE");

  return (
    <>
      <header className="page-head"><h1>Seller Sessions</h1></header>
      {error && <div className="error">{error}</div>}

      <form className="card" onSubmit={create}>
        <h2>Start a session with a seller</h2>
        <div className="row three">
          <label>Seller username
            <input value={form.seller_username} onChange={set("seller_username")} required />
          </label>
          <label className="span-2">Whatnot show link (optional)
            <input value={form.show_url} onChange={set("show_url")} placeholder="https://www.whatnot.com/live/…" />
          </label>
          <label>First item shipping ($)
            <input inputMode="decimal" value={form.first_item_shipping} onChange={set("first_item_shipping")} placeholder="unknown" />
          </label>
          <label>Each additional item ($)
            <input inputMode="decimal" value={form.additional_item_shipping} onChange={set("additional_item_shipping")} placeholder="unknown" />
          </label>
          <label>Shipping cap for the bundle ($)
            <input inputMode="decimal" value={form.shipping_cap} onChange={set("shipping_cap")} placeholder="none / unknown" />
          </label>
        </div>
        <p className="hint">Leave a shipping box empty if you do not know it. A cautious estimate is used and flagged until you fill it in. Enter 0 only if the seller confirmed it is free.</p>
        <label className="check">
          <input type="checkbox" checked={form.weekly_bundling} onChange={set("weekly_bundling")} />
          This seller combines everything I buy this week into one shipment
        </label>
        <div className="actions"><button className="primary" type="submit">Start session</button></div>
      </form>

      {sessions === null ? <p>Loading…</p> : active.length === 0 ? <p className="muted">No active sessions.</p> :
        active.map((s) => <SessionCard key={s.id} s={s} reload={load} />)}

      {ended.length > 0 && (
        <p><button className="link" onClick={() => setShowEnded(!showEnded)}>{showEnded ? "Hide" : "Show"} {ended.length} ended session(s)</button></p>
      )}
      {showEnded && ended.map((s) => <SessionCard key={s.id} s={s} reload={load} />)}
    </>
  );
}

function SessionCard({ s, reload }) {
  const [terms, setTerms] = useState({
    first_item_shipping: s.first_item_shipping ?? "", additional_item_shipping: s.additional_item_shipping ?? "",
    shipping_cap: s.shipping_cap ?? "",
  });
  const [buy, setBuy] = useState({ description: "", winning_bid: "", category: "" });
  const [error, setError] = useState("");
  const isActive = s.status === "ACTIVE";

  async function run(action) {
    setError("");
    try {
      await action();
      reload();
    } catch (e) {
      setError(e.message);
    }
  }

  const saveTerms = (e) => {
    e.preventDefault();
    run(() => api.put(`/api/sessions/${s.id}/shipping`, {
      first_item_shipping: orNull(terms.first_item_shipping),
      additional_item_shipping: orNull(terms.additional_item_shipping), shipping_cap: orNull(terms.shipping_cap),
    }));
  };
  const record = (e) => {
    e.preventDefault();
    run(async () => {
      await api.post(`/api/sessions/${s.id}/purchases`, {
        description: buy.description, winning_bid: buy.winning_bid, category: buy.category || "uncategorized",
      });
      setBuy({ description: "", winning_bid: "", category: "" });
    });
  };

  return (
    <section className={`card ${isActive ? "" : "faded"}`}>
      <div className="page-head">
        <h2>{s.seller} <span className={`tag ${isActive ? "committed" : "canceled"}`}>{s.status}</span>
          {s.weekly_bundling && <span className="tag">weekly bundle</span>}</h2>
        {isActive && (
          <div className="actions">
            {s.bundle_open && <button onClick={() => window.confirm("Close this bundle? The next purchase will start a new shipment and pay first-item shipping again.") && run(() => api.post(`/api/sessions/${s.id}/close-bundle`))}>Close bundle (shipped)</button>}
            <button onClick={() => window.confirm("End this session?") && run(() => api.post(`/api/sessions/${s.id}/end`))}>End session</button>
          </div>
        )}
      </div>
      {s.show_url && <p className="hint"><a href={s.show_url} target="_blank" rel="noreferrer">{s.show_url}</a></p>}
      {error && <div className="error">{error}</div>}

      <div className="mini-stats">
        <div><span>Items</span><b>{s.purchase_count}</b></div>
        <div><span>Winning bids</span><b>{usd(s.winning_bids_total)}</b></div>
        <div><span>Shipping actually paid</span><b>{usd(s.actual_shipping_paid)}</b></div>
        <div><span>Shipping expected (unpaid)</span><b>{usd(s.estimated_shipping_pending)}</b></div>
        <div><span>Next item would add</span><b>{usd(s.next_item_shipping.amount)}{s.next_item_shipping.is_estimate && <span className="tag warn">estimate</span>}</b></div>
        <div><span>Room left with seller</span><b>{usd(s.seller_exposure_remaining)}</b></div>
      </div>
      <p className="hint">{s.next_item_shipping.basis}.</p>

      {isActive && (
        <form className="row four" onSubmit={saveTerms}>
          <label>First item shipping ($)
            <input inputMode="decimal" value={terms.first_item_shipping} placeholder="unknown" onChange={(e) => setTerms({ ...terms, first_item_shipping: e.target.value })} />
          </label>
          <label>Each additional item ($)
            <input inputMode="decimal" value={terms.additional_item_shipping} placeholder="unknown" onChange={(e) => setTerms({ ...terms, additional_item_shipping: e.target.value })} />
          </label>
          <label>Shipping cap ($)
            <input inputMode="decimal" value={terms.shipping_cap} placeholder="none / unknown" onChange={(e) => setTerms({ ...terms, shipping_cap: e.target.value })} />
          </label>
          <div className="actions end"><button type="submit">Save shipping terms</button></div>
        </form>
      )}

      {s.purchases.length > 0 && (
        <table>
          <thead><tr><th>Item</th><th>Status</th><th className="num">Bid</th><th className="num">Shipping</th><th className="num">Tax</th><th className="num">All-in</th><th></th></tr></thead>
          <tbody>
            {s.purchases.map((p) => <PurchaseRow key={p.id} p={p} run={run} />)}
          </tbody>
        </table>
      )}

      {isActive && (
        <form className="row four" onSubmit={record}>
          <label className="span-2">Record an item you won
            <input value={buy.description} onChange={(e) => setBuy({ ...buy, description: e.target.value })} placeholder="Item description" required />
          </label>
          <label>Winning bid ($)
            <input inputMode="decimal" value={buy.winning_bid} onChange={(e) => setBuy({ ...buy, winning_bid: e.target.value })} required />
          </label>
          <div className="actions end"><button type="submit">Record purchase</button></div>
        </form>
      )}
    </section>
  );
}

function PurchaseRow({ p, run }) {
  const [settling, setSettling] = useState(false);
  const [actual, setActual] = useState({ actual_bid: p.bid, actual_shipping: p.shipping, actual_tax: p.tax });

  if (settling) {
    return (
      <tr>
        <td>{p.description}<div className="hint">Enter the amounts from your Whatnot receipt.</div></td>
        <td></td>
        {["actual_bid", "actual_shipping", "actual_tax"].map((k) => (
          <td className="num" key={k}><input className="tiny" inputMode="decimal" value={actual[k]} onChange={(e) => setActual({ ...actual, [k]: e.target.value })} /></td>
        ))}
        <td></td>
        <td className="num">
          <button onClick={() => run(() => api.post(`/api/purchases/${p.id}/settle`, actual)).then(() => setSettling(false))}>Save</button>{" "}
          <button className="link" onClick={() => setSettling(false)}>Back</button>
        </td>
      </tr>
    );
  }
  return (
    <tr className={p.status === "CANCELED" ? "faded" : ""}>
      <td>{p.description}</td>
      <td><span className={`tag ${p.status.toLowerCase()}`}>{p.status}</span></td>
      <td className="num">{usd(p.bid)}</td>
      <td className="num">{usd(p.shipping)}{p.shipping_was_estimate && <span className="tag warn">est.</span>}</td>
      <td className="num">{usd(p.tax)}</td>
      <td className="num">{usd(p.total)}</td>
      <td className="num">
        {p.status === "COMMITTED" && (
          <>
            <button onClick={() => setSettling(true)}>Enter actual charges</button>{" "}
            <button className="link" onClick={() => window.confirm("Cancel this purchase and release its budget?") && run(() => api.post(`/api/purchases/${p.id}/cancel`))}>Cancel</button>
          </>
        )}
      </td>
    </tr>
  );
}
