// Talks to the Profit Hunter backend. Money arrives and leaves as strings
// ("12.50"); the browser never does money arithmetic.

async function request(method, path, body, signal) {
  let response;
  try {
    response = await fetch(path, {
      method,
      signal,
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new Error("Cannot reach the Profit Hunter backend. Is it running on port 8000?");
  }
  let data = null;
  try {
    data = await response.json();
  } catch {
    /* empty body */
  }
  if (!response.ok) {
    let detail = data && data.detail;
    if (Array.isArray(detail)) {
      detail = detail.map((d) => `${d.loc.slice(1).join(".")}: ${d.msg}`).join("; ");
    }
    throw new Error(detail || `Request failed (${response.status}).`);
  }
  return data;
}

export const api = {
  get: (path, signal) => request("GET", path, undefined, signal),
  post: (path, body = {}, signal) => request("POST", path, body, signal),
  put: (path, body) => request("PUT", path, body),
};

// "" -> null, otherwise the trimmed text. Used for optional money fields.
export const orNull = (text) => (text === null || text === undefined || String(text).trim() === "" ? null : String(text).trim());

export const usd = (value) => (value === null || value === undefined ? "—" : `$${value}`);

// "1.4449" -> "144%"
export const pct = (fraction) => (fraction === null || fraction === undefined ? "—" : `${Math.round(Number(fraction) * 100)}%`);

export const when = (isoText) => (isoText ? new Date(isoText).toLocaleString() : "—");

export const CONSTRAINT_LABELS = {
  min_net_profit: "Minimum net profit",
  min_roi: "Minimum ROI",
  max_bid: "Maximum single bid",
  max_all_in_cost: "Maximum all-in cost",
  weekly_budget: "Remaining weekly budget",
  seller_exposure: "Seller exposure limit",
};
