import { useEffect, useState } from "react";
import { api, usd, when } from "../api.js";

export default function Dashboard({ simulated, goTo }) {
  const [data, setData] = useState(null);
  const [history, setHistory] = useState([]);
  const [ranked, setRanked] = useState([]);
  const [error, setError] = useState("");

  useEffect(() => {
    const q = `?simulated=${simulated}`;
    Promise.all([api.get(`/api/dashboard${q}`), api.get(`/api/analyses${q}&limit=8`), api.get(`/api/opportunities${q}`)])
      .then(([d, h, o]) => {
        setData(d);
        setHistory(h);
        setRanked(o);
      })
      .catch((e) => setError(e.message));
  }, [simulated]);

  if (error) return <div className="error">{error}</div>;
  if (!data) return <p>Loading…</p>;

  const usedPct = Math.min(100, Math.max(0, (Number(data.committed_total) / Number(data.starting_budget || 1)) * 100));
  const sellers = Object.entries(data.seller_exposure);
  const categories = Object.entries(data.purchases_by_category);
  const live = data.purchases.filter((p) => p.status !== "CANCELED");

  return (
    <>
      <header className="page-head">
        <h1>Dashboard</h1>
        <span className="muted">Budget week starting {data.week_start} ({data.timezone})</span>
      </header>

      <section className="cards">
        <div className={`card stat ${data.over_budget ? "bad" : ""}`}>
          <div className="stat-label">Budget remaining</div>
          <div className="stat-value">{usd(data.available)}</div>
          <div className="bar"><div style={{ width: `${usedPct}%` }} /></div>
          <div className="muted">of {usd(data.starting_budget)} weekly budget</div>
        </div>
        <div className="card stat">
          <div className="stat-label">Capital committed</div>
          <div className="stat-value">{usd(data.committed_total)}</div>
          <div className="muted">{usd(data.pending_commitments)} pending · {usd(data.actual_spending)} paid</div>
        </div>
        <div className="card stat">
          <div className="stat-label">Purchases this week</div>
          <div className="stat-value">{live.length}</div>
          <div className="muted">{data.active_sessions.length} active seller session(s)</div>
        </div>
        <div className="card stat">
          <div className="stat-label">Expected profit</div>
          <div className="stat-value">{usd(data.expected_profit)}</div>
          <div className="muted">Estimate only. Not cash, never added to budget.</div>
        </div>
        <div className="card stat">
          <div className="stat-label">Realized profit</div>
          <div className="stat-value">—</div>
          <div className="muted">Tracked once Inventory is built.</div>
        </div>
      </section>

      {data.over_budget && <div className="error">Actual charges have exceeded this week's budget. New purchases are blocked.</div>}

      <div className="grid-2">
        <section className="card">
          <h2>Seller exposure <span className="muted">(limit {usd(data.max_seller_exposure)} each)</span></h2>
          {sellers.length === 0 ? <p className="muted">No purchases yet this week.</p> : (
            <table><tbody>
              {sellers.map(([name, amount]) => (
                <tr key={name}><td>{name}</td><td className="num">{usd(amount)}</td></tr>
              ))}
            </tbody></table>
          )}
          {categories.length > 0 && (
            <>
              <h3>By category</h3>
              <table><tbody>
                {categories.map(([name, amount]) => (
                  <tr key={name}><td>{name}</td><td className="num">{usd(amount)}</td></tr>
                ))}
              </tbody></table>
            </>
          )}
        </section>

        <section className="card">
          <h2>Active seller sessions</h2>
          {data.active_sessions.length === 0 ? (
            <p className="muted">None. <button className="link" onClick={() => goTo("sessions")}>Start a seller session</button></p>
          ) : (
            <table>
              <thead><tr><th>Seller</th><th className="num">Items</th><th className="num">Next item shipping</th><th className="num">Room left</th></tr></thead>
              <tbody>
                {data.active_sessions.map((s) => (
                  <tr key={s.id}>
                    <td>{s.seller}</td>
                    <td className="num">{s.purchase_count}</td>
                    <td className="num">{usd(s.next_item_shipping.amount)}{s.next_item_shipping.is_estimate && <span className="tag warn">estimate</span>}</td>
                    <td className="num">{usd(s.seller_exposure_remaining)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>

      <section className="card">
        <h2>Purchases this week</h2>
        {data.purchases.length === 0 ? <p className="muted">Nothing recorded.</p> : (
          <table>
            <thead><tr><th>Item</th><th>Seller</th><th>Status</th><th className="num">Bid</th><th className="num">Shipping</th><th className="num">Tax</th><th className="num">All-in</th><th className="num">Expected net proceeds</th></tr></thead>
            <tbody>
              {data.purchases.map((p) => (
                <tr key={p.id} className={p.status === "CANCELED" ? "faded" : ""}>
                  <td>{p.description}</td><td>{p.seller}</td>
                  <td><span className={`tag ${p.status.toLowerCase()}`}>{p.status}</span></td>
                  <td className="num">{usd(p.bid)}</td>
                  <td className="num">{usd(p.shipping)}{p.shipping_was_estimate && <span className="tag warn">est.</span>}</td>
                  <td className="num">{usd(p.tax)}</td><td className="num">{usd(p.total)}</td>
                  <td className="num">{usd(p.expected_net_proceeds)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {ranked.length > 0 && (
        <section className="card">
          <h2>Ranked opportunities <span className="muted">(this week, active sessions)</span></h2>
          <table>
            <thead><tr><th className="num">Score</th><th>Item</th><th>Seller</th><th>Result</th><th>Evidence</th><th className="num">Max bid</th><th className="num">Profit at max bid</th></tr></thead>
            <tbody>
              {ranked.map((a) => (
                <tr key={a.id}>
                  <td className="num"><b>{a.ranking.score}</b></td>
                  <td><button className="link" onClick={() => goTo("research", a.item_id)}>{a.item.description}</button></td>
                  <td>{a.session.seller}</td>
                  <td><span className={`tag ${a.recommendation.toLowerCase()}`}>{a.recommendation}</span></td>
                  <td>{a.valuation.evidence_quality || "your own estimate"}</td>
                  <td className="num">{usd(a.max_bid.max_bid)}</td>
                  <td className="num">{usd(a.at_max_bid.net_profit)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="hint">Scores weigh profit, ROI, evidence, capital, identification, resale speed, shipping and category concentration. They reflect the budget at the time of each analysis and never authorize a purchase.</p>
        </section>
      )}

      <section className="card">
        <h2>Recent analyses</h2>
        {history.length === 0 ? (
          <p className="muted">None yet. <button className="link" onClick={() => goTo("analyze")}>Analyze an item</button></p>
        ) : (
          <table>
            <thead><tr><th>When</th><th>Item</th><th>Seller</th><th>Result</th><th className="num">Max bid</th></tr></thead>
            <tbody>
              {history.map((a) => (
                <tr key={a.id}>
                  <td>{when(a.created_at)}</td><td>{a.item.description}</td><td>{a.session.seller}</td>
                  <td><span className={`tag ${a.recommendation.toLowerCase()}`}>{a.recommendation}</span></td>
                  <td className="num">{a.recommendation === "SKIP" ? "—" : usd(a.max_bid && a.max_bid.max_bid)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}
