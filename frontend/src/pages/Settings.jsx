import { useEffect, useState } from "react";
import { api } from "../api.js";

// Rates are stored as fractions ("0.09") but shown as percentages ("9").
const toPct = (fraction) => String(Number((Number(fraction) * 100).toFixed(4)));
const toFraction = (percent) => String(Number((Number(percent) / 100).toFixed(6)));

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const TIMEZONES = ["America/New_York", "America/Chicago", "America/Denver", "America/Phoenix", "America/Los_Angeles", "America/Anchorage", "Pacific/Honolulu", "UTC"];

const GROUPS = [
  { title: "Budget", fields: [
    ["weekly_budget", "Weekly budget", "$"],
    ["max_seller_exposure", "Most to spend with one seller per week", "$"],
  ] },
  { title: "Risk thresholds", fields: [
    ["max_bid", "Maximum single bid", "$"],
    ["max_all_in_cost", "Maximum all-in cost per item", "$", "Bid + shipping + tax."],
    ["min_net_profit", "Minimum expected net profit", "$"],
    ["min_roi", "Minimum expected ROI", "%", "100 means you must expect to double your money."],
    ["preferred_roi", "Preferred expected ROI", "%"],
    ["min_id_confidence", "Minimum identification confidence", "%"],
  ] },
  { title: "Bidding", fields: [
    ["min_bid", "Lowest possible bid", "$"],
    ["bid_increment", "Normal bid step", "$"],
  ] },
  { title: "Buying costs", fields: [
    ["purchase_tax_rate", "Sales tax on purchases", "%"],
    ["unknown_first_item_shipping_estimate", "Shipping estimate when a seller's first-item rate is unknown", "$"],
    ["unknown_additional_item_shipping_estimate", "Shipping estimate when a seller's additional-item rate is unknown", "$"],
  ] },
  { title: "Pricing discounts", note: "Preliminary assumptions, to be calibrated from your real sales.", fields: [
    ["undercut_rate", "Undercut the lowest credible comparable by", "%"],
    ["active_only_discount", "Extra discount when only asking prices are known", "%"],
    ["risk_reserve_rate", "Reserve for returns, defects and surprises", "%", "Share of the sale price set aside."],
  ] },
  { title: "Comparable evidence rules", note: "Preliminary assumptions. Stricter values mean more items are skipped.", fields: [
    ["min_credible_comparables", "Fewest credible comparables needed for a valuation", "#"],
    ["min_comparable_match_confidence", "Lowest match a comparable may have", "%", "Below this it is not used."],
    ["buy_comparable_match_confidence", "Match needed for BUY-grade evidence", "%", "Between the two, a comparable supports REVIEW only."],
    ["preferred_comparable_age_days", "Age limit for BUY-grade evidence", "d", "Older ones can lower the price but do not support BUY."],
    ["max_comparable_age_days", "Oldest a comparable may be", "d", "Days since you saw it."],
    ["max_expected_holding_days", "Longest acceptable time to sell", "d", "Slower items are skipped as holding risk."],
  ] },
  { title: "AI identification limits", note: "The app's AI costs. Separate from your inventory budget. The allowance never resets or tops up by itself.", fields: [
    ["ai_pilot_allowance", "Total AI allowance", "$"],
    ["ai_max_cost_per_item", "Most AI cost per item", "$", "Second look and retries included."],
    ["vision_primary_max_output_tokens", "Output limit, first look", "tok", "Includes reasoning tokens; billed as output."],
    ["vision_review_max_output_tokens", "Output limit, second look", "tok"],
    ["vision_max_retries", "Retries after a temporary failure", "#", "0 or 1."],
    ["vision_timeout_seconds", "Give up waiting after", "s"],
    ["vision_image_max_side", "Longest photo side sent", "px", "Larger costs more; smaller may blur label text."],
    ["vision_image_token_multiplier", "Image token multiplier", "×", "Vendor figure; unverified for these models."],
    ["vision_reservation_safety_factor", "Safety margin on cost estimates", "×"],
  ] },
  { title: "Selling costs", fields: [
    ["default_outbound_shipping", "Outbound shipping label you pay", "$", "Used unless the marketplace below sets its own."],
    ["default_packaging_cost", "Packaging per item", "$"],
  ] },
];
const PCT_FIELDS = new Set(GROUPS.flatMap((g) => g.fields).filter((f) => f[2] === "%").map((f) => f[0]));

function toForm(s) {
  const form = { ...s };
  PCT_FIELDS.forEach((k) => (form[k] = toPct(s[k])));
  form.fee_profiles = Object.fromEntries(Object.entries(s.fee_profiles).map(([key, p]) => [key, {
    ...p, percent_rate: toPct(p.percent_rate), processing_rate: toPct(p.processing_rate),
    flat_fee_threshold: p.flat_fee_threshold ?? "", flat_fee: p.flat_fee ?? "",
    seller_paid_outbound_shipping: p.seller_paid_outbound_shipping ?? "",
  }]));
  return form;
}

function fromForm(form) {
  const s = { ...form };
  PCT_FIELDS.forEach((k) => (s[k] = toFraction(form[k])));
  const blank = (v) => (String(v).trim() === "" ? null : String(v).trim());
  s.fee_profiles = Object.fromEntries(Object.entries(form.fee_profiles).map(([key, p]) => [key, {
    ...p, percent_rate: toFraction(p.percent_rate), processing_rate: toFraction(p.processing_rate),
    flat_fee_threshold: blank(p.flat_fee_threshold), flat_fee: blank(p.flat_fee),
    seller_paid_outbound_shipping: blank(p.seller_paid_outbound_shipping),
  }]));
  return s;
}

export default function SettingsPage() {
  const [form, setForm] = useState(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [vision, setVision] = useState(null);
  const [usage, setUsage] = useState([]);
  const loadVision = () => Promise.all([api.get("/api/vision/status"), api.get("/api/vision/usage?limit=15")])
    .then(([v, u]) => { setVision(v); setUsage(u); }).catch(() => {});

  useEffect(() => {
    api.get("/api/settings").then((s) => setForm(toForm(s))).catch((e) => setError(e.message));
    loadVision();
  }, []);
  const setPrice = (index, name, value) => set("vision_prices", form.vision_prices.map((p, i) => (i === index ? { ...p, [name]: value } : p)));
  const resolve = (id, billed) => api.post(`/api/vision/usage/${id}/resolve`, { billed }).then(loadVision).catch((e) => setError(e.message));
  const money4 = (v) => (v === null || v === undefined ? "—" : `$${Number(v).toFixed(4)}`);

  const set = (name, value) => {
    setSaved(false);
    setForm((f) => ({ ...f, [name]: value }));
  };
  const setProfile = (key, name, value) => {
    setSaved(false);
    setForm((f) => ({ ...f, fee_profiles: { ...f.fee_profiles, [key]: { ...f.fee_profiles[key], [name]: value } } }));
  };
  const setTier = (index, name, value) => set("bid_increment_tiers", form.bid_increment_tiers.map((t, i) => (i === index ? { ...t, [name]: value } : t)));

  async function save(event) {
    event.preventDefault();
    setError("");
    try {
      const s = await api.put("/api/settings", fromForm(form));
      setForm(toForm(s));
      setSaved(true);
      loadVision();
    } catch (e) {
      setError(e.message);
    }
  }

  if (!form) return error ? <div className="error">{error}</div> : <p>Loading…</p>;
  const timezones = TIMEZONES.includes(form.timezone) ? TIMEZONES : [form.timezone, ...TIMEZONES];

  return (
    <form onSubmit={save}>
      <header className="page-head sticky">
        <h1>Settings</h1>
        <div className="actions">
          {saved && <span className="ok-text">Saved ✓</span>}
          <button className="primary" type="submit">Save settings</button>
        </div>
      </header>
      {error && <div className="error">{error}</div>}

      {GROUPS.map((group) => (
        <section className="card" key={group.title}>
          <h2>{group.title}</h2>
          {group.note && <p className="hint">{group.note}</p>}
          <div className="settings-grid">
            {group.fields.map(([name, label, unit, help]) => (
              <label key={name}>{label}
                <span className="unit-input"><input inputMode="decimal" value={form[name]} onChange={(e) => set(name, e.target.value)} required /><i>{unit}</i></span>
                {help && <small className="hint">{help}</small>}
              </label>
            ))}
            {group.title === "Budget" && (
              <>
                <label>Budget week starts on
                  <select value={form.week_start_day} onChange={(e) => set("week_start_day", Number(e.target.value))}>
                    {DAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
                  </select>
                </label>
                <label>Timezone
                  <select value={form.timezone} onChange={(e) => set("timezone", e.target.value)}>
                    {timezones.map((z) => <option key={z}>{z}</option>)}
                  </select>
                </label>
              </>
            )}
            {group.title === "Buying costs" && (
              <label className="check">
                <input type="checkbox" checked={form.tax_applies_to_shipping} onChange={(e) => set("tax_applies_to_shipping", e.target.checked)} />
                Sales tax is also charged on shipping
              </label>
            )}
          </div>
          {group.title === "Bidding" && (
            <>
              <h3>Larger bid steps at higher prices</h3>
              <p className="hint">Add a row once you know where Whatnot's bid steps get bigger. With none, the normal step applies at every price.</p>
              {form.bid_increment_tiers.map((tier, i) => (
                <div className="row four" key={i}>
                  <label>From a bid of ($)<input inputMode="decimal" value={tier.from_bid} onChange={(e) => setTier(i, "from_bid", e.target.value)} required /></label>
                  <label>Bids go up by ($)<input inputMode="decimal" value={tier.increment} onChange={(e) => setTier(i, "increment", e.target.value)} required /></label>
                  <div className="actions end"><button type="button" onClick={() => set("bid_increment_tiers", form.bid_increment_tiers.filter((_, j) => j !== i))}>Remove</button></div>
                </div>
              ))}
              <button type="button" onClick={() => set("bid_increment_tiers", [...form.bid_increment_tiers, { from_bid: "", increment: "" }])}>Add a step</button>
            </>
          )}
        </section>
      ))}

      <section className="card">
        <h2>Marketplace fees</h2>
        <p className="hint warn-text">⚠ These figures are unverified placeholders. Check each marketplace's current fee page, correct them, then tick "Verified".</p>
        <label>Where you normally resell
          <select value={form.default_sale_marketplace} onChange={(e) => set("default_sale_marketplace", e.target.value)}>
            {Object.entries(form.fee_profiles).map(([key, p]) => <option key={key} value={key}>{p.name}</option>)}
          </select>
        </label>
        <div className="scroll-x">
          <table className="fees">
            <thead><tr>
              <th>Marketplace</th><th>Fee %</th><th>Fixed fee $</th><th>Flat fee $ …</th><th>… for sales under $</th>
              <th>Processing %</th><th>Processing fixed $</th><th>Outbound shipping you pay $</th><th>Fee on buyer's shipping</th><th>Verified</th>
            </tr></thead>
            <tbody>
              {Object.entries(form.fee_profiles).map(([key, p]) => (
                <tr key={key}>
                  <td>{p.name}</td>
                  {["percent_rate", "fixed_fee", "flat_fee", "flat_fee_threshold", "processing_rate", "processing_fixed", "seller_paid_outbound_shipping"].map((name) => (
                    <td key={name}><input className="tiny" inputMode="decimal" value={p[name]} placeholder={name === "seller_paid_outbound_shipping" ? "default" : name.startsWith("flat") ? "none" : ""}
                      onChange={(e) => setProfile(key, name, e.target.value)} required={!name.startsWith("flat") && name !== "seller_paid_outbound_shipping"} /></td>
                  ))}
                  <td><input type="checkbox" checked={p.fees_apply_to_buyer_shipping} onChange={(e) => setProfile(key, "fees_apply_to_buyer_shipping", e.target.checked)} /></td>
                  <td><input type="checkbox" checked={p.verified} onChange={(e) => setProfile(key, "verified", e.target.checked)} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="hint">"Outbound shipping you pay": enter 0 where the buyer pays for shipping (the Vinted assumption). Leave empty to use the general label cost above.</p>
      </section>

      <section className="card">
        <h2>AI identification</h2>
        {vision && (
          <p className="hint">
            Now: <b>{vision.mode === "mock" ? "mock mode (no real identification, no cost)" : vision.ready ? "LIVE — photos are sent to OpenAI" : `live selected but not ready: ${vision.not_ready_reason}`}</b>.
            {" "}API key on the server: {vision.api_key_present ? "found" : "not set"}. Used {money4(vision.used)} of {money4(vision.allowance)}.
          </p>
        )}
        <div className="settings-grid">
          <label>Provider
            <select value={form.vision_provider} onChange={(e) => set("vision_provider", e.target.value)}>
              <option value="mock">Mock (practice, nothing is sent)</option>
              <option value="openai">OpenAI (real, paid)</option>
            </select>
          </label>
          <label>First-look model<input value={form.vision_primary_model} onChange={(e) => set("vision_primary_model", e.target.value)} required /></label>
          <label>Second-look model<input value={form.vision_review_model} onChange={(e) => set("vision_review_model", e.target.value)} required /></label>
          {[["vision_primary_reasoning", "Reasoning effort, first look"], ["vision_review_reasoning", "Reasoning effort, second look"]].map(([name, label]) => (
            <label key={name}>{label}
              <select value={form[name]} onChange={(e) => set(name, e.target.value)}>
                {form.vision_supported_reasoning.map((r) => <option key={r}>{r}</option>)}
              </select>
            </label>
          ))}
        </div>
        <label className="check">
          <input type="checkbox" checked={form.vision_live_enabled}
            onChange={(e) => (!e.target.checked || window.confirm("Allow real, paid requests to OpenAI? Photos you analyze will be sent to OpenAI and charged to the API account whose key is set on the server.")) && set("vision_live_enabled", e.target.checked)} />
          Allow live, paid AI requests (also needs the OpenAI provider above and an API key set on the server)
        </label>
        <p className="hint">The API key is never entered here or stored in the database. It is read from the OPENAI_API_KEY environment variable on the computer running the backend.</p>

        <h3>Published prices used for cost limits</h3>
        <div className="scroll-x">
          <table className="fees">
            <thead><tr><th>Model</th><th>Input $ / 1M tokens</th><th>Output $ / 1M tokens</th><th>In effect from</th><th>Last checked</th><th></th></tr></thead>
            <tbody>
              {form.vision_prices.map((p, i) => (
                <tr key={i}>
                  <td><input value={p.model} onChange={(e) => setPrice(i, "model", e.target.value)} required /></td>
                  <td><input className="tiny" inputMode="decimal" value={p.input_per_million} onChange={(e) => setPrice(i, "input_per_million", e.target.value)} required /></td>
                  <td><input className="tiny" inputMode="decimal" value={p.output_per_million} onChange={(e) => setPrice(i, "output_per_million", e.target.value)} required /></td>
                  <td><input type="date" value={p.effective_from} onChange={(e) => setPrice(i, "effective_from", e.target.value)} required /></td>
                  <td><input type="date" value={p.verified_on || ""} onChange={(e) => setPrice(i, "verified_on", e.target.value || null)} /></td>
                  <td><button type="button" className="link" onClick={() => set("vision_prices", form.vision_prices.filter((_, j) => j !== i))}>Remove</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <button type="button" onClick={() => set("vision_prices", [...form.vision_prices, { model: "", input_per_million: "", output_per_million: "", effective_from: new Date().toISOString().slice(0, 10), verified_on: null, source: "" }])}>Add a price</button>
        <p className="hint">A model with no price cannot be used live, because its cost could not be limited. When a price changes, add a new row with its start date instead of editing the old one.</p>

        <h3>Recent AI requests</h3>
        {usage.length === 0 ? <p className="muted">None yet.</p> : (
          <div className="scroll-x">
            <table>
              <thead><tr><th>When</th><th>Item</th><th>Model</th><th>Result</th><th className="num">Tokens in / out</th><th className="num">Set aside</th><th className="num">Actual</th><th className="num">Counted</th><th></th></tr></thead>
              <tbody>
                {usage.map((u) => (
                  <tr key={u.id}>
                    <td>{new Date(u.created_at).toLocaleString()}</td><td>#{u.item_id}</td>
                    <td>{u.model}{!u.is_live && <span className="tag warn">mock</span>}{u.is_second_look && <span className="tag">2nd look</span>}{u.is_retry && <span className="tag">retry</span>}{u.cache_hit && <span className="tag">reused</span>}</td>
                    <td>{u.outcome || u.state}{u.state === "UNRESOLVED" && <span className="tag skip">billing uncertain</span>}</td>
                    <td className="num">{u.input_tokens ?? "—"} / {u.output_tokens ?? "—"}</td>
                    <td className="num">{money4(u.reserved_cost)}</td><td className="num">{money4(u.actual_cost)}</td><td className="num">{money4(u.charged_cost)}</td>
                    <td className="num">{u.state === "UNRESOLVED" && (<>
                      <button type="button" className="link" onClick={() => window.confirm("Mark as billed? Check your OpenAI usage page first.") && resolve(u.id, true)}>It was billed</button>{" "}
                      <button type="button" className="link" onClick={() => window.confirm("Mark as NOT billed? Check your OpenAI usage page first.") && resolve(u.id, false)}>Not billed</button></>)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card">
        <h2>Safety locks</h2>
        <p>Automatic purchasing: <b>disabled</b> · Human approval: <b>required</b></p>
        <p className="hint">These cannot be changed in this version. Profit Hunter never bids or buys for you.</p>
      </section>
    </form>
  );
}
