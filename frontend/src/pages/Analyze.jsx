import { useEffect, useRef, useState } from "react";
import { api, CONSTRAINT_LABELS, orNull, pct, RANK_LABELS, usd } from "../api.js";

const BLANK_ITEM = {
  description: "", category: "", brand: "", model: "", size: "", color: "", material: "",
  era: "", condition: "", defects: "", identifiers: "", seller_transcript: "", manually_confirmed: false,
};
const ATTRIBUTES = [
  ["category", "Category"], ["brand", "Brand"], ["model", "Model / style"], ["size", "Size"],
  ["color", "Color"], ["material", "Material"], ["era", "Era"], ["condition", "Condition"],
  ["defects", "Visible defects"], ["identifiers", "Tags / identifiers"],
];

export default function Analyze({ simulated, goTo, param }) {
  const [sessions, setSessions] = useState(null);
  const [marketplaces, setMarketplaces] = useState({});
  const [defaultMarket, setDefaultMarket] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [item, setItem] = useState(BLANK_ITEM);
  const [items, setItems] = useState([]);
  const [itemId, setItemId] = useState(param ? String(param) : "");
  const [research, setResearch] = useState(null);
  const [priceSource, setPriceSource] = useState(param ? "comparables" : "manual");
  const [price, setPrice] = useState("");
  const [valuationNote, setValuationNote] = useState("");
  const [lowerBound, setLowerBound] = useState(false);
  const [marketplace, setMarketplace] = useState("");
  const [currentBid, setCurrentBid] = useState("");
  const [risk, setRisk] = useState({ authenticity_uncertain: false, suspected_counterfeit: false, condition_unverifiable: false });
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [timing, setTiming] = useState(null);
  const pending = useRef(null);

  useEffect(() => {
    Promise.all([api.get(`/api/sessions?simulated=${simulated}`), api.get("/api/settings"), api.get("/api/items")])
      .then(([all, settings, saved]) => {
        setItems(saved);
        const active = all.filter((s) => s.status === "ACTIVE");
        setSessions(active);
        if (active.length) setSessionId(String(active[0].id));
        setMarketplaces(settings.fee_profiles);
        setDefaultMarket(settings.default_sale_marketplace);
        setMarketplace(settings.default_sale_marketplace);
      })
      .catch((e) => setError(e.message));
  }, [simulated]);

  // Load the saved item and the valuation its comparables support.
  useEffect(() => {
    if (!itemId) {
      setResearch(null);
      return;
    }
    api.get(`/api/items/${itemId}${marketplace ? `?marketplace=${marketplace}` : ""}`)
      .then((data) => {
        setResearch(data);
        setItem((prev) => (prev.loadedFrom === data.id ? prev : { ...Object.fromEntries(Object.keys(BLANK_ITEM).map((k) => [k, data[k]])), loadedFrom: data.id }));
      })
      .catch((e) => setError(e.message));
  }, [itemId, marketplace]);

  function chooseItem(id) {
    setItemId(id);
    setResult(null);
    if (!id) {
      setItem(BLANK_ITEM);
      setPriceSource("manual");
    } else {
      setPriceSource("comparables");
    }
  }

  const setField = (name, value) => setItem((prev) => ({ ...prev, [name]: value }));

  async function calculate(event) {
    event.preventDefault();
    if (pending.current) pending.current.abort();
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true);
    setError("");
    const started = performance.now();
    try {
      const data = await api.post("/api/analyze", {
        session_id: Number(sessionId), item: Object.fromEntries(Object.keys(BLANK_ITEM).map((k) => [k, item[k]])),
        item_id: itemId ? Number(itemId) : null, use_comparables: priceSource === "comparables",
        expected_sale_price: priceSource === "comparables" ? null : orNull(price),
        valuation_note: valuationNote, valuation_is_lower_bound: lowerBound,
        marketplace, current_bid: orNull(currentBid), ...risk,
      }, controller.signal);
      setResult(data);
      setTiming(Math.round(performance.now() - started));
      if (!itemId) {
        // The analysis saved this item; keep working on the same one.
        setItem((prev) => ({ ...prev, loadedFrom: data.item_id }));
        setItemId(String(data.item_id));
        api.get("/api/items").then(setItems).catch(() => {});
      }
    } catch (e) {
      if (e.name !== "AbortError") {
        setError(e.message);
        setResult(null); // never leave a stale recommendation on screen
      }
    } finally {
      if (pending.current === controller) {
        pending.current = null;
        setBusy(false);
      }
    }
  }

  function startNew() {
    setItem(BLANK_ITEM);
    setItemId("");
    setPriceSource("manual");
    setPrice("");
    setValuationNote("");
    setLowerBound(false);
    setCurrentBid("");
    setRisk({ authenticity_uncertain: false, suspected_counterfeit: false, condition_unverifiable: false });
    setResult(null);
    setError("");
  }

  if (sessions === null && !error) return <p>Loading…</p>;
  if (sessions && sessions.length === 0) {
    return (
      <>
        <header className="page-head"><h1>Analyze Item</h1></header>
        <div className="card">
          <p>An item is always analyzed inside a seller session, because shipping and seller limits depend on the seller.</p>
          <button className="primary" onClick={() => goTo("sessions")}>Start a seller session</button>
        </div>
      </>
    );
  }

  return (
    <>
      <header className="page-head">
        <h1>Analyze Item</h1>
        <button onClick={startNew}>Clear for next item</button>
      </header>
      {error && <div className="error">{error}</div>}
      <div className="analyze">
        <form className="card" onSubmit={calculate}>
          <h2>1. Seller and auction</h2>
          <div className="row">
            <label>Seller session
              <select value={sessionId} onChange={(e) => setSessionId(e.target.value)} required>
                {(sessions || []).map((s) => (
                  <option key={s.id} value={s.id}>{s.seller} — next item ships for ${s.next_item_shipping.amount}</option>
                ))}
              </select>
            </label>
            <label>Current bid ($)
              <input inputMode="decimal" value={currentBid} onChange={(e) => setCurrentBid(e.target.value)} placeholder="e.g. 1" />
            </label>
          </div>

          <h2>2. Item</h2>
          <div className="notice">Screenshot upload and AI identification arrive in Milestone 4. For now, describe the item yourself.</div>
          <label>Saved item
            <select value={itemId} onChange={(e) => chooseItem(e.target.value)}>
              <option value="">New item (not saved yet)</option>
              {items.map((i) => <option key={i.id} value={i.id}>#{i.id} {i.description} ({i.comparable_count} comparable{i.comparable_count === 1 ? "" : "s"})</option>)}
            </select>
          </label>
          <label>Description
            <input value={item.description} onChange={(e) => setField("description", e.target.value)} required autoFocus placeholder="e.g. Men's Levi's 501 jeans, 34x32" />
          </label>
          <div className="row three">
            {ATTRIBUTES.map(([name, label]) => (
              <label key={name}>{label}
                <input value={item[name]} onChange={(e) => setField(name, e.target.value)} />
              </label>
            ))}
          </div>
          <label>Seller's spoken description (optional)
            <textarea rows={2} value={item.seller_transcript} onChange={(e) => setField("seller_transcript", e.target.value)} />
          </label>
          <label className="check">
            <input type="checkbox" checked={item.manually_confirmed} onChange={(e) => setField("manually_confirmed", e.target.checked)} />
            I have personally confirmed these details are correct
          </label>

          <h2>3. Resale value</h2>
          <label className="check">
            <input type="radio" name="price-source" checked={priceSource === "comparables"} disabled={!itemId} onChange={() => setPriceSource("comparables")} />
            Calculate it from this item's comparables {!itemId && <span className="muted">(choose or save an item first)</span>}
          </label>
          <label className="check">
            <input type="radio" name="price-source" checked={priceSource === "manual"} onChange={() => setPriceSource("manual")} />
            Type in my own conservative price
          </label>
          {priceSource === "comparables" && research && (
            <div className="notice">
              {research.valuation.ok
                ? <>Conservative expected sale price from {research.valuation.comparables_used.length} comparables: <b>{usd(research.valuation.expected_sale_price)}</b> ({research.valuation.evidence_quality.toLowerCase()} evidence). Recalculated when you press the button.</>
                : <>No valuation yet: {research.valuation.reason}</>}
              {" "}<button type="button" className="link" onClick={() => goTo("research", research.id)}>Open comparables</button>
            </div>
          )}
          <div className="row">
            {priceSource === "manual" ? (
              <label>Conservative expected sale price ($)
                <input inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} placeholder="Leave empty if unknown" />
              </label>
            ) : <div />}
            <label>Where you will resell
              <select value={marketplace} onChange={(e) => setMarketplace(e.target.value)}>
                {Object.entries(marketplaces).map(([key, profile]) => (
                  <option key={key} value={key}>{profile.name}{key === defaultMarket ? " (default)" : ""}</option>
                ))}
              </select>
            </label>
          </div>
          {priceSource === "manual" && <p className="hint">
            Enter what the item should realistically <b>sell</b> for, based on listings you have looked up — not an asking
            price you hope for, and never the auction's starting bid. Leave it empty if you have no evidence; the result will be SKIP.
          </p>}
          <label>Where this price comes from (optional)
            <input value={valuationNote} onChange={(e) => setValuationNote(e.target.value)} placeholder="e.g. lowest of 3 similar Vinted listings, minus 20%" />
          </label>
          <label className="check">
            <input type="checkbox" checked={lowerBound} onChange={(e) => setLowerBound(e.target.checked)} />
            {priceSource === "comparables"
              ? "The comparables include the least valuable version this item could plausibly be"
              : "This price assumes the least valuable version this item could plausibly be"}
          </label>

          <h2>4. Risk checks</h2>
          {[["authenticity_uncertain", "Authenticity is uncertain"],
            ["suspected_counterfeit", "Possibly counterfeit"],
            ["condition_unverifiable", "Condition cannot be verified"]].map(([name, label]) => (
            <label className="check" key={name}>
              <input type="checkbox" checked={risk[name]} onChange={(e) => setRisk((r) => ({ ...r, [name]: e.target.checked }))} />
              {label}
            </label>
          ))}

          <div className="actions">
            <button className="primary big" type="submit" disabled={busy}>{busy ? "Calculating…" : "Calculate maximum bid"}</button>
            {busy && <button type="button" onClick={() => pending.current && pending.current.abort()}>Cancel</button>}
          </div>
        </form>

        <div>
          {result ? <Result r={result} timing={timing} goTo={goTo} /> : (
            <div className="card muted">The maximum bid and BUY / REVIEW / SKIP result will appear here.</div>
          )}
        </div>
      </div>
    </>
  );
}

function Result({ r, timing, goTo }) {
  const val = r.valuation;
  const fromComps = val.source === "Comparables";
  const rec = r.recommendation;
  const showMax = rec !== "SKIP" && r.max_bid && r.max_bid.max_bid;
  return (
    <>
      <div className={`verdict ${rec.toLowerCase()}`}>
        <div>
          <div className="verdict-word">{rec}</div>
          <div className="verdict-sub">{r.item.description}</div>
        </div>
        {showMax && (
          <div className="verdict-max">
            <div className="verdict-sub">Do not bid above</div>
            <div className="verdict-amount">{usd(r.max_bid.max_bid)}</div>
          </div>
        )}
      </div>
      <div className="card">
        <ul className="reasons">
          {r.reasons.map((text) => <li key={text}>{text}</li>)}
          {r.warnings.map((text) => <li key={text} className="warn-text">⚠ {text}</li>)}
        </ul>
        {rec === "BUY" && <p className="hint">A BUY result is advice. It does not place a bid or authorize a purchase.</p>}
      </div>

      {r.at_max_bid && rec !== "SKIP" && (
        <div className="card">
          <h2>Expected outcome</h2>
          <table>
            <thead><tr><th></th>{r.at_next_bid && <th className="num">At next bid ({usd(r.next_bid)})</th>}<th className="num">At maximum bid ({usd(r.max_bid.max_bid)})</th></tr></thead>
            <tbody>
              {[["Bid", "bid", usd], ["Shipping added by this item", "inbound_shipping", usd], ["Purchase tax", "purchase_tax", usd],
                ["All-in cost", "all_in_cost", usd], ["Expected net profit", "net_profit", usd], ["Expected ROI", "roi", pct],
                ["Profit margin", "profit_margin", pct]].map(([label, key, fmt]) => (
                <tr key={key} className={key === "net_profit" || key === "all_in_cost" ? "strong" : ""}>
                  <td>{label}</td>
                  {r.at_next_bid && <td className="num">{fmt(r.at_next_bid[key])}</td>}
                  <td className="num">{fmt(r.at_max_bid[key])}</td>
                </tr>
              ))}
              <tr><td>Resale multiple (sale price ÷ cost)</td>
                {r.at_next_bid && <td className="num">{r.at_next_bid.gross_resale_multiple}×</td>}
                <td className="num">{r.at_max_bid.gross_resale_multiple}×</td></tr>
            </tbody>
          </table>
          <p className="hint">These are estimates, not realized profit. Preferred ROI is {pct(r.preferred_roi)} or more.</p>
        </div>
      )}

      {r.sale && (
        <div className="card">
          <h2>Resale estimate <span className="muted">({r.sale.marketplace})</span></h2>
          <table><tbody>
            <tr><td>Conservative expected sale price</td><td className="num">{usd(r.sale.expected_sale_price)}</td></tr>
            <tr><td>− Marketplace fee</td><td className="num">{usd(r.sale.marketplace_fee)}</td></tr>
            <tr><td>− Payment processing</td><td className="num">{usd(r.sale.payment_processing)}</td></tr>
            <tr><td>− Outbound shipping you pay</td><td className="num">{usd(r.sale.outbound_shipping)}</td></tr>
            <tr><td>− Packaging</td><td className="num">{usd(r.sale.packaging)}</td></tr>
            <tr><td>− Risk reserve (returns, defects)</td><td className="num">{usd(r.sale.risk_allowance)}</td></tr>
            <tr className="strong"><td>Expected net proceeds</td><td className="num">{usd(r.sale.net_proceeds)}</td></tr>
          </tbody></table>
          {!r.sale.fee_profile_verified && <p className="hint warn-text">⚠ The {r.sale.marketplace} fee figures are unverified placeholders. Check them in Settings.</p>}
          <p className="hint">Price source: {val.source}{val.note ? ` — ${val.note}` : ""}.{!fromComps && " No comparables support this price; it is your own estimate."}</p>
        </div>
      )}

      {fromComps && (
        <div className="card">
          <h2>Price evidence {val.evidence_quality && <span className="tag">{val.evidence_quality}</span>}</h2>
          {val.ok ? <ul className="checks">{val.steps.map((s) => <li key={s}>{s}</li>)}</ul> : <p className="warn-text">{val.reason}</p>}
          {val.ok && <p className="hint">List at {usd(val.competitive_listing_price)}; expect {usd(val.expected_sale_price)}. Expected time to sell: {val.expected_holding_days === null ? "unknown" : `about ${val.expected_holding_days} days`}.</p>}
          {[["Comparables used", val.comparables_used], ["Comparables not used", val.comparables_excluded]].map(([title, list]) => list.length > 0 && (
            <div key={title}>
              <h3>{title} ({list.length})</h3>
              <table><tbody>
                {list.map((c) => (
                  <tr key={c.id}>
                    <td><a href={c.source_url} target="_blank" rel="noreferrer">{c.title}</a>
                      <div className="hint">{c.marketplace} · {c.listing_status === "ACTIVE" ? "asking price" : c.listing_status === "SOLD" ? "sold" : "auction"} · seen {c.date_observed} · {c.match_confidence_pct}% match — {c.verdict}</div></td>
                    <td className="num">{usd(c.price)}</td>
                  </tr>
                ))}
              </tbody></table>
            </div>
          ))}
          <p className="hint"><button className="link" onClick={() => goTo("research", r.item_id)}>Open this item's comparables</button></p>
        </div>
      )}

      {r.ranking && (
        <div className="card">
          <h2>Opportunity score <span className="muted">{r.ranking.score} / 100</span></h2>
          <table><tbody>
            {Object.entries(r.ranking.components).map(([name, c]) => (
              <tr key={name}><td>{RANK_LABELS[name] || name}</td><td className="num">{c.points} / {c.out_of}</td></tr>
            ))}
          </tbody></table>
          <p className="hint">Scored at the maximum bid. For comparing opportunities only; the weights are preliminary.</p>
        </div>
      )}

      {r.max_bid && (
        <div className="card">
          <h2>What limits the bid</h2>
          <table>
            <thead><tr><th>Rule</th><th className="num">Highest bid it allows</th></tr></thead>
            <tbody>
              {Object.entries(r.max_bid.individual_ceilings).map(([name, ceiling]) => (
                <tr key={name} className={r.max_bid.binding_constraints.includes(name) ? "strong" : ""}>
                  <td>{CONSTRAINT_LABELS[name] || name}{r.max_bid.binding_constraints.includes(name) && <span className="tag warn">limiting</span>}</td>
                  <td className="num">{ceiling === null ? "none" : name !== "max_bid" && Number(ceiling) > Number(r.max_bid.individual_ceilings.max_bid) ? `more than ${usd(r.max_bid.individual_ceilings.max_bid)}` : usd(ceiling)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {r.max_bid.checks.length > 0 && (
            <ul className="checks">
              {r.max_bid.checks.map((c) => <li key={c.name}>{c.passed ? "✓" : "✗"} {c.explanation}</li>)}
            </ul>
          )}
        </div>
      )}

      <div className="card">
        <h2>Inputs used</h2>
        <table><tbody>
          <tr><td>Identification</td><td>{r.identification.evidence}</td></tr>
          <tr><td>Shipping for this item</td><td>{usd(r.shipping.amount)} — {r.shipping.basis}{r.shipping.is_estimate && <span className="tag warn">estimate</span>}</td></tr>
          <tr><td>Purchase tax rate</td><td>{pct(r.purchase_tax_rate)}</td></tr>
          <tr><td>Remaining weekly budget</td><td>{usd(r.remaining_budget)}</td></tr>
          <tr><td>Room left with {r.session.seller}</td><td>{usd(r.seller_exposure_remaining)}</td></tr>
        </tbody></table>
        <p className="hint">Saved as analysis #{r.id}{timing !== null ? ` · answered in ${timing} ms` : ""}</p>
      </div>

      {rec !== "SKIP" && <RecordWin r={r} />}
    </>
  );
}

function RecordWin({ r }) {
  const [bid, setBid] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const overMax = bid !== "" && r.max_bid && Number(bid) > Number(r.max_bid.max_bid);

  async function record(event) {
    event.preventDefault();
    setError("");
    try {
      const p = await api.post(`/api/sessions/${r.session.id}/purchases`, {
        description: r.item.description, winning_bid: bid, category: r.item.category || "uncategorized",
        expected_net_proceeds: r.sale ? r.sale.net_proceeds : null,
      });
      setMessage(`Recorded. All-in cost ${usd(p.total)} is now reserved from your budget.`);
    } catch (e) {
      setError(e.message);
    }
  }

  if (message) return <div className="card ok">{message}</div>;
  return (
    <form className="card" onSubmit={record}>
      <h2>Did you win it?</h2>
      <p className="hint">Only fill this in after you have personally bid and won on Whatnot.</p>
      <div className="row">
        <label>Winning bid ($)
          <input inputMode="decimal" value={bid} onChange={(e) => setBid(e.target.value)} required />
        </label>
        <div className="actions end"><button type="submit">Record my win</button></div>
      </div>
      {overMax && <p className="warn-text">⚠ This is above the maximum bid of {usd(r.max_bid.max_bid)}. It no longer meets your profit rules.</p>}
      {error && <div className="error">{error}</div>}
    </form>
  );
}
