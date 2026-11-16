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
    ["undercut_rate", "Undercut the lowest credible comparable by", "%", "Used from Milestone 3."],
    ["active_only_discount", "Extra discount when only asking prices are known", "%", "Used from Milestone 3."],
    ["risk_reserve_rate", "Reserve for returns, defects and surprises", "%", "Share of the sale price set aside."],
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

  useEffect(() => {
    api.get("/api/settings").then((s) => setForm(toForm(s))).catch((e) => setError(e.message));
  }, []);

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
        <h2>AI model</h2>
        <p className="muted">Screenshot identification arrives in Milestone 4. No AI service is connected and nothing is being charged.</p>
      </section>

      <section className="card">
        <h2>Safety locks</h2>
        <p>Automatic purchasing: <b>disabled</b> · Human approval: <b>required</b></p>
        <p className="hint">These cannot be changed in this version. Profit Hunter never bids or buys for you.</p>
      </section>
    </form>
  );
}
