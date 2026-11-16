import { useCallback, useEffect, useRef, useState } from "react";
import { api, usd } from "../api.js";

const STATUS = {
  ready_for_review: ["Ready for human review", "review"],
  more_evidence_needed: ["More evidence needed", "skip"],
  unable_to_identify: ["Unable to identify", "skip"],
  failed: ["Identification failed", "skip"],
};
const BASIS = {
  observed: ["seen in photo", "buy"], inferred: ["guess", "warn"],
  user_supplied: ["seller's claim, not verified", "warn"], unknown: ["unknown", ""],
};
// Model field -> the item detail it can fill in.
const FIELD_ROWS = [
  ["category", "Category", "category"], ["brand", "Brand", "brand"], ["style", "Model / style", "model"],
  ["size", "Size", "size"], ["color", "Color", "color"], ["pattern", "Pattern", null], ["material", "Material", "material"],
];
const DETAILS = ["description", "category", "brand", "model", "size", "color", "material", "era", "condition", "defects", "identifiers", "seller_transcript"];
const EXTRA_INPUTS = [["era", "Era"], ["condition", "Condition"], ["defects", "Visible defects"], ["identifiers", "Tags / label text"]];
const ROLES = [["garment", "Whole garment"], ["label", "Label or tag"], ["detail", "Detail"]];
const SOURCE = { image_1: "photo 1", image_2: "photo 2", image_3: "photo 3", seller_text: "seller text" };
const cost = (v) => (v === null || v === undefined ? "—" : `$${Number(v).toFixed(4)}`);
const clamp = (n) => Math.min(1, Math.max(0, n));

function CropBox({ image, onCrop }) {
  const box = useRef(null);
  const [drag, setDrag] = useState(null);
  const at = (e) => {
    const r = box.current.getBoundingClientRect();
    return { x: clamp((e.clientX - r.left) / r.width), y: clamp((e.clientY - r.top) / r.height) };
  };
  const rect = (d) => ({ x: Math.min(d.a.x, d.b.x), y: Math.min(d.a.y, d.b.y), w: Math.abs(d.a.x - d.b.x), h: Math.abs(d.a.y - d.b.y) });
  const shown = drag ? rect(drag) : image.crop;
  return (
    <div className="cropbox" ref={box} title="Drag to select the part to analyze"
      onPointerDown={(e) => { e.preventDefault(); box.current.setPointerCapture(e.pointerId); const p = at(e); setDrag({ a: p, b: p }); }}
      onPointerMove={(e) => drag && setDrag({ ...drag, b: at(e) })}
      onPointerUp={() => { if (drag) { const r = rect(drag); setDrag(null); if (r.w >= 0.05 && r.h >= 0.05) onCrop(r); } }}>
      <img src={image.url} alt={`${image.role} photo`} draggable={false} />
      {shown && <div className="crop-rect" style={{ left: `${shown.x * 100}%`, top: `${shown.y * 100}%`, width: `${shown.w * 100}%`, height: `${shown.h * 100}%` }} />}
    </div>
  );
}

export default function Identify({ goTo, param }) {
  const [items, setItems] = useState(null);
  const [itemId, setItemId] = useState(param ? String(param) : "");
  const [item, setItem] = useState(null);
  const [form, setForm] = useState(null);
  const [images, setImages] = useState([]);
  const [status, setStatus] = useState(null);
  const [estimate, setEstimate] = useState(null);
  const [first, setFirst] = useState(null);
  const [second, setSecond] = useState(null);
  const [offer, setOffer] = useState(null); // second-look estimate awaiting consent
  const [newName, setNewName] = useState("");
  const [uploadRole, setUploadRole] = useState("garment");
  const [busy, setBusy] = useState("");
  const [checked, setChecked] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef(null);
  const fileInput = useRef(null);

  const fail = (e) => e.name !== "AbortError" && setError(e.message);
  const loadStatus = useCallback(() => api.get("/api/vision/status").then(setStatus).catch(fail), []);
  const loadItems = useCallback(() => api.get("/api/items").then((rows) => { setItems(rows); return rows; }), []);

  const loadItem = useCallback(async (id, { keepForm = false } = {}) => {
    if (!id) return;
    const [it, imgs, history] = await Promise.all([
      api.get(`/api/items/${id}`), api.get(`/api/items/${id}/images`), api.get(`/api/items/${id}/identifications`)]);
    setItem(it);
    setImages(imgs);
    if (!keepForm) setForm(Object.fromEntries(DETAILS.map((k) => [k, it[k]])));
    const primary = history.find((h) => h.kind === "PRIMARY");
    setFirst(primary || null);
    setSecond((primary && history.find((h) => h.kind === "SECOND_LOOK" && h.parent_id === primary.id)) || null);
    setChecked(false);
    setOffer(null);
  }, []);

  useEffect(() => {
    loadStatus();
    loadItems().then((rows) => { if (!itemId && rows.length) setItemId(String(rows[0].id)); }).catch(fail);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setError(""); setItem(null); setFirst(null); setSecond(null); loadItem(itemId).catch(fail); }, [itemId, loadItem]);

  const sellerText = form ? form.seller_transcript : "";
  const imageIds = images.map((i) => i.id);
  useEffect(() => {
    setEstimate(null);
    if (!itemId || imageIds.length === 0 || !status || !status.ready) return;
    const timer = setTimeout(() => {
      api.post(`/api/items/${itemId}/identify/estimate`, { image_ids: imageIds, seller_text: sellerText }).then(setEstimate).catch(() => {});
    }, 400);
    return () => clearTimeout(timer);
  }, [itemId, imageIds.join(","), JSON.stringify(images.map((i) => [i.crop, i.role])), sellerText, status && status.ready]); // eslint-disable-line react-hooks/exhaustive-deps

  async function act(label, fn) {
    setError("");
    setBusy(label);
    try { await fn(); } catch (e) { fail(e); } finally { setBusy(""); }
  }

  const createItem = (e) => { e.preventDefault(); act("item", async () => {
    const created = await api.post("/api/items", { description: newName });
    setNewName("");
    await loadItems();
    setItemId(String(created.id));
  }); };

  const upload = (file) => file && act("upload", async () => {
    const data = new FormData();
    data.append("file", file);
    data.append("role", uploadRole);
    await api.upload(`/api/items/${itemId}/images`, data);
    if (fileInput.current) fileInput.current.value = "";
    await loadItem(itemId, { keepForm: true });
  });
  const changeImage = (img, change) => act("image", async () => {
    await api.put(`/api/images/${img.id}`, { role: img.role, crop: img.crop, ...change });
    await loadItem(itemId, { keepForm: true });
  });
  const removeImage = (img) => window.confirm("Delete this photo permanently?") && act("image", async () => {
    await api.delete(`/api/images/${img.id}`);
    await loadItem(itemId, { keepForm: true });
  });

  const analyze = () => act("analyze", async () => {
    const controller = new AbortController();
    pending.current = controller;
    try {
      const r = await api.post(`/api/items/${itemId}/identify`, { image_ids: imageIds, seller_text: sellerText }, controller.signal);
      setFirst(r);
      setSecond(null);
      setOffer(null);
      if (r.ok) prefill(r.result);
    } finally {
      pending.current = null;
      loadStatus();
    }
  });

  // Fill EMPTY boxes only, and only from what was seen or stated. Never overwrite what you typed.
  function prefill(result) {
    setForm((f) => {
      const next = { ...f };
      for (const [name, , target] of FIELD_ROWS) {
        const s = result.fields[name];
        if (target && !next[target].trim() && s.value && !s.disputed && s.basis !== "inferred") next[target] = s.value;
      }
      return next;
    });
  }

  const askSecondLook = () => act("estimate", async () => setOffer(await api.get(`/api/identifications/${first.id}/second-look/estimate`)));
  const sendSecondLook = () => act("second", async () => {
    try {
      setSecond(await api.post(`/api/identifications/${first.id}/second-look`, { accepted_max_cost_micros: offer.max_cost_micros }));
      setOffer(null);
    } finally { loadStatus(); }
  });

  const dirty = item && form && DETAILS.some((k) => (form[k] || "") !== (item[k] || ""));
  const save = () => act("save", async () => {
    await api.put(`/api/items/${itemId}`, { ...form, manually_confirmed: false });
    await Promise.all([loadItem(itemId), loadItems()]);
  });
  const confirm = () => act("confirm", async () => {
    await api.post(`/api/items/${itemId}/confirm-identity`, { fingerprint: item.identity.fingerprint, identification_id: first && first.ok ? first.id : null });
    await loadItem(itemId);
  });
  const withdraw = () => act("confirm", async () => { await api.post(`/api/items/${itemId}/unconfirm-identity`); await loadItem(itemId); });

  const set = (name) => (e) => setForm((f) => ({ ...f, [name]: e.target.value }));
  const badge = status && (status.simulated_billing ? ["MOCK — test mode with pretend charges", "warn"]
    : status.mode === "mock" ? ["MOCK — no real identification, no cost", "warn"]
    : status.ready ? ["LIVE — photos are sent to OpenAI", "skip"] : ["LIVE — not ready", "skip"]);
  const result = first && first.ok ? first.result : null;
  const other = second && second.ok ? second.result : null;
  const differs = new Set(((second && second.disagreements) || []).map((d) => d.field));
  const [statusText, statusClass] = STATUS[first ? first.status : "failed"] || STATUS.failed;
  const confirmed = item && item.identity.confirmed;

  return (
    <>
      <header className="page-head">
        <h1>Identify Item</h1>
        {badge && <span className={`tag ${badge[1]}`} data-testid="vision-mode">{badge[0]}</span>}
      </header>
      {error && <div className="error" role="alert">{error}</div>}
      {status && (
        <p className="hint" data-testid="allowance">
          AI allowance: <b>{cost(status.remaining)}</b> left of {cost(status.allowance)} (limit {cost(status.max_cost_per_item)} per item).
          {status.unresolved_count > 0 && <span className="warn-text"> {status.unresolved_count} request(s) with uncertain billing are still held ({cost(status.unresolved)}); settle them in Settings.</span>}
          {" "}This is separate from your inventory budget.
        </p>
      )}

      <div className="grid-2">
        <section className="card">
          <h2>1. Item</h2>
          {items === null ? <p>Loading…</p> : items.length === 0 ? <p className="muted">No items yet. Add one on the right.</p> : (
            <label>Item
              <select value={itemId} onChange={(e) => setItemId(e.target.value)}>
                {items.map((i) => <option key={i.id} value={i.id}>#{i.id} {i.description}</option>)}
              </select>
            </label>
          )}
          {item && <p className="hint">Identity: {confirmed ? <b className="ok-text">confirmed by you</b> : <b className="warn-text">not confirmed</b>}
            {item.identity.needs_reconfirmation && ` — ${item.identity.last_revoke_reason} Confirm again.`}</p>}
        </section>
        <form className="card" onSubmit={createItem}>
          <h2>Or add a new item</h2>
          <label>Short description
            <input value={newName} onChange={(e) => setNewName(e.target.value)} required placeholder="e.g. blue denim jacket from tonight's show" />
          </label>
          <div className="actions"><button type="submit" disabled={busy === "item"}>Add item</button></div>
        </form>
      </div>

      {item && form && (
        <>
          <section className="card">
            <h2>2. Photos <span className="muted">({images.length} of {status ? status.max_images : 3})</span></h2>
            <p className="hint">Add a photo of the whole garment and a close, sharp photo of the label. Drag across a photo to keep only the part that matters. Location and camera data are removed when you upload.</p>
            <div className="photos">
              {images.map((img, n) => (
                <div className="photo" key={img.id}>
                  <CropBox image={img} onCrop={(crop) => changeImage(img, { crop })} />
                  <div className="row">
                    <label>Photo {n + 1} shows
                      <select value={img.role} onChange={(e) => changeImage(img, { role: e.target.value })}>
                        {ROLES.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                      </select>
                    </label>
                    <div className="actions end">
                      {img.crop && <button type="button" className="link" onClick={() => changeImage(img, { crop: null })}>Clear crop</button>}
                      <button type="button" className="link" onClick={() => removeImage(img)}>Delete</button>
                    </div>
                  </div>
                  <span className="hint">{img.crop ? "Cropped: only the outlined part is analyzed." : "Whole photo is analyzed."}</span>
                </div>
              ))}
            </div>
            {status && images.length < status.max_images && (
              <div className="row">
                <label>Add a photo (JPEG, PNG or WEBP)
                  <input ref={fileInput} type="file" accept="image/jpeg,image/png,image/webp" data-testid="photo-input" onChange={(e) => upload(e.target.files[0])} disabled={busy === "upload"} />
                </label>
                <label>It shows
                  <select value={uploadRole} onChange={(e) => setUploadRole(e.target.value)}>
                    {ROLES.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                  </select>
                </label>
              </div>
            )}
          </section>

          <section className="card">
            <h2>3. What the seller said <span className="muted">(optional)</span></h2>
            <textarea rows={2} value={form.seller_transcript} onChange={set("seller_transcript")} placeholder="Type what the seller wrote or said. It is treated as a claim, not as proof." />
            <h2>4. Analyze</h2>
            {status && <div className="notice" data-testid="external-notice">{status.external_notice}</div>}
            {status && !status.ready && <p className="warn-text">{status.not_ready_reason} You can still fill in the details yourself below.</p>}
            {estimate && (
              <p className="hint" data-testid="estimate">
                {status.simulated_billing && "Test mode: the costs below are pretend. "}{!estimate.bills ? "Mock mode: this costs nothing."
                  : estimate.cached ? "Already analyzed with these exact photos and text: the saved result is reused at no cost."
                  : <>Estimated cost: at most <b>{cost(estimate.max_cost)}</b> using {estimate.model} ({cost(estimate.max_cost_with_retry)} if one retry is needed). Usually much less.</>}
                {!estimate.allowed && <span className="warn-text"> This does not fit the remaining AI allowance or the per-item limit.</span>}
              </p>
            )}
            <div className="actions">
              <button className="primary big" type="button" onClick={analyze} disabled={busy !== "" || images.length === 0 || !status || !status.ready}>
                {busy === "analyze" ? "Analyzing…" : "Analyze photos"}
              </button>
              {busy === "analyze" && <button type="button" onClick={() => pending.current && pending.current.abort()}>Stop waiting</button>}
              {images.length === 0 && <span className="muted">Add at least one photo first.</span>}
            </div>
            {busy === "analyze" && <p className="hint">Waiting for the answer. If you stop waiting, a request already sent may still finish and be billed; its result is kept and reused.</p>}
          </section>

          {first && (
            <section className="card" data-testid="result">
              <div className="page-head">
                <h2>5. AI suggestions <span className={`tag ${statusClass}`} data-testid="id-status">{statusText}</span>
                  {first.is_mock && <span className="tag warn">MOCK</span>}{first.from_cache && <span className="tag">reused</span>}</h2>
                <span className="muted">{first.model} · cost {cost(first.cost)}{first.attempts[0] && first.attempts[0].latency_ms !== null ? ` · ${first.attempts[first.attempts.length - 1].latency_ms} ms` : ""}</span>
              </div>
              {!first.ok ? (
                <div className="error">{first.error} Nothing was identified. You can try again or fill in the details yourself below.</div>
              ) : (
                <>
                  <div className="notice"><b>Unconfirmed suggestions.</b> Check each one against the item. They do not count as identification until you confirm below. Authenticity is not assessed, and "no visible defect" says nothing about overall condition.</div>
                  {result.summary && <p>{result.summary}</p>}
                  {result.another_photo_needed && <p className="warn-text">⚠ Another photo is needed{result.photo_request ? `: ${result.photo_request}` : "."}</p>}
                  <div className="scroll-x">
                    <table className="evidence">
                      <thead><tr><th>Detail</th><th>Suggestion</th>{other && <th>Second look</th>}<th>Basis</th><th>Evidence</th><th></th></tr></thead>
                      <tbody>
                        {FIELD_ROWS.map(([name, label, target]) => {
                          const s = result.fields[name];
                          const [basisText, basisClass] = BASIS[s.basis];
                          return (
                            <tr key={name} className={differs.has(name) ? "differs" : ""}>
                              <td>{label}</td>
                              <td>{s.value ? <b>{s.value}</b> : <span className="muted">unknown</span>}{s.disputed && <span className="tag skip">conflicting</span>}</td>
                              {other && <td>{other.fields[name].value || <span className="muted">unknown</span>}{differs.has(name) && <span className="tag skip">differs</span>}</td>}
                              <td><span className={`tag ${basisClass}`}>{basisText}</span></td>
                              <td><span className="muted small">{s.value ? `${SOURCE[s.evidence_source] || "no source"}: ${s.evidence}` : ""}</span></td>
                              <td className="num">{target && s.value && <button type="button" className="link" onClick={() => setForm((f) => ({ ...f, [target]: s.value }))}>Use</button>}
                                {target && other && other.fields[name].value && differs.has(name) && <> <button type="button" className="link" onClick={() => setForm((f) => ({ ...f, [target]: other.fields[name].value }))}>Use 2nd</button></>}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  <dl className="facts">
                    <dt>Label text read</dt><dd>{result.label_text.length ? result.label_text.join(" · ") : "none"} {result.label_text.length > 0 && <button type="button" className="link" onClick={() => setForm((f) => ({ ...f, identifiers: result.label_text.join(" · ") }))}>Use</button>}</dd>
                    <dt>Visible defects</dt><dd>{result.visible_defects.length ? result.visible_defects.map((d) => `${d.description} (${SOURCE[d.evidence_source] || d.evidence_source})`).join("; ") : "none seen in these photos"}</dd>
                    <dt>Could also be</dt><dd>{result.possible_variations.length ? result.possible_variations.map((v) => `${v.name} — tell apart by: ${v.distinguishing_evidence}`).join("; ") : "no alternatives listed"}</dd>
                    {result.conflicts.length > 0 && <><dt>Conflicts</dt><dd className="warn-text">{result.conflicts.map((c) => `${c.field}: ${c.description}`).join("; ")}</dd></>}
                    <dt>Missing</dt><dd>{result.missing_information.join("; ") || "nothing listed"}</dd>
                    <dt>Search ideas</dt><dd>{result.suggested_search_terms.join(" · ") || "none"}</dd>
                  </dl>
                  {result.notes.map((n) => <p key={n} className="warn-text">⚠ {n}</p>)}

                  {first.kind === "PRIMARY" && !second && status && (
                    <div className="second-look">
                      {!offer ? (
                        <button type="button" onClick={askSecondLook} disabled={busy !== ""}>Request second look…</button>
                      ) : (
                        <div className="notice" data-testid="second-offer">
                          A second look uses <b>{offer.model}</b>{offer.bills ? <> and costs at most <b>{cost(offer.max_cost)}</b> ({cost(offer.max_cost_with_retry)} if one retry is needed). So far this item has used {cost(offer.item_spent)} of its {cost(offer.item_limit)} limit.</> : " in mock mode, at no cost."}
                          {!offer.allowed && <b className="warn-text"> It does not fit the remaining allowance or the per-item limit.</b>}
                          <div className="actions">
                            <button type="button" className="primary" onClick={sendSecondLook} disabled={busy !== "" || !offer.allowed}>{busy === "second" ? "Asking…" : "Send second look"}</button>
                            <button type="button" onClick={() => setOffer(null)}>Cancel</button>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                  {second && (
                    <div className="notice" data-testid="second-result">
                      <b>Second look ({second.model}, cost {cost(second.cost)}).</b>{" "}
                      {!second.ok ? `It failed: ${second.error}`
                        : second.disagreements.length === 0 ? "It gave the same answers. Two models agreeing is not proof; you still need to check."
                        : `It disagrees on: ${second.disagreements.map((d) => d.field).join(", ")}. Both answers are shown above; neither replaced the other. Decide by checking the item.`}
                    </div>
                  )}
                </>
              )}
            </section>
          )}

          <section className="card">
            <h2>6. Your details for this item</h2>
            <p className="hint">Correct anything that is wrong and leave unknown things empty. Boxes you already filled are never overwritten by a suggestion.</p>
            <label>Description<input value={form.description} onChange={set("description")} required /></label>
            <div className="row three">
              {FIELD_ROWS.filter((r) => r[2]).map(([, label, target]) => (
                <label key={target}>{label}<input value={form[target]} onChange={set(target)} data-testid={`detail-${target}`} /></label>
              ))}
              {EXTRA_INPUTS.map(([name, label]) => <label key={name}>{label}<input value={form[name]} onChange={set(name)} /></label>)}
            </div>
            <div className="actions">
              <button type="button" onClick={save} disabled={!dirty || busy !== "" || !form.description.trim()}>Save details</button>
              {dirty ? <span className="warn-text">Unsaved changes.</span> : <span className="muted">Saved.</span>}
            </div>

            <h2>7. Confirm identity</h2>
            {confirmed ? (
              <div className="card ok" data-testid="confirmed">You confirmed these details and photos. <button type="button" className="link" onClick={withdraw}>Withdraw confirmation</button></div>
            ) : (
              <>
                <label className="check">
                  <input type="checkbox" checked={checked} disabled={dirty} onChange={(e) => setChecked(e.target.checked)} />
                  I have checked the saved details above against the photos or the item myself
                </label>
                <div className="actions">
                  <button type="button" className="primary" onClick={confirm} disabled={!checked || dirty || busy !== ""}>Confirm identity</button>
                  {dirty && <span className="muted">Save your changes first.</span>}
                </div>
                <p className="hint">Only your confirmation counts toward a BUY result. Changing a detail or a photo later withdraws it.</p>
              </>
            )}
            <div className="actions">
              <button type="button" onClick={() => goTo("research", item.id)} disabled={dirty}>Continue to comparable research</button>
              <button type="button" onClick={() => goTo("analyze", item.id)} disabled={dirty}>Analyze item</button>
            </div>
          </section>
        </>
      )}
    </>
  );
}
