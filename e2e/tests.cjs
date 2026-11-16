// The tests. Everything typed or uploaded here is SYNTHETIC.
const assert = require("node:assert/strict");
const path = require("node:path");

const nav = (page, name) => page.locator(".sidebar").getByRole("button", { name, exact: true }).click();
const field = (scope, label) => scope.locator("label", { hasText: label }).locator("input, select, textarea").first();
const main = (page) => page.locator("main").innerText();
const today = () => new Date().toLocaleDateString("en-CA");

async function settings(page, base, changes) {
  const s = await (await page.request.get(`${base}/api/settings`)).json();
  const r = await page.request.put(`${base}/api/settings`, { data: { ...s, ...changes } });
  assert.equal(r.status(), 200, await r.text());
}

async function startSession(page, seller = "synthetic_seller") {
  await nav(page, "Seller Sessions");
  const form = page.locator("form", { hasText: "Start a session with a seller" });
  await field(form, "Seller username").fill(seller);
  await field(form, "First item shipping").fill("5");
  await field(form, "Each additional item").fill("0");
  await form.getByRole("button", { name: "Start session" }).click();
  await page.locator("section.card", { hasText: seller }).first().waitFor();
}

async function newItemWithPhotos(page, fixtures, names = ["synthetic-garment.png"]) {
  await nav(page, "Identify Item");
  const add = page.locator("form", { hasText: "Or add a new item" });
  await field(add, "Short description").fill("SYNTHETIC denim jacket");
  await add.getByRole("button", { name: "Add item" }).click();
  await page.getByText("2. Photos").waitFor();
  for (const [i, name] of names.entries()) {
    if (name.includes("label")) await page.locator("label", { hasText: "It shows" }).locator("select").selectOption("label");
    await page.getByTestId("photo-input").setInputFiles(path.join(fixtures, name));
    await page.locator(".photo").nth(i).waitFor();
  }
}

async function addComparable(page, title, price, extra = {}) {
  const form = page.locator("#comparable-form");
  await field(form, "Marketplace").fill("Vinted");
  await field(form, "Listing title").fill(title);
  await field(form, "Link to the listing").fill(`https://example.com/synthetic/${title.replace(/\W+/g, "-")}`);
  await field(form, "Listing type").selectOption("SOLD");
  await form.locator("label", { hasText: /price \(\$\)/ }).locator("input").fill(price);
  await field(form, "How closely does it match").fill(extra.match || "95");
  await field(form, "Days it took to sell").fill("12");
  await form.getByRole("button", { name: "Add comparable" }).click();
  await page.locator(`a:has-text("${title}")`).waitFor();
}

module.exports = {
  "main path: upload, mock analysis, correction, confirmation, comparables, recommendation": async ({ page, base, fixtures, shot }) => {
    await page.goto(base);
    await startSession(page);
    await newItemWithPhotos(page, fixtures, ["synthetic-garment.png", "synthetic-label.png"]);
    assert.match(await page.getByTestId("vision-mode").innerText(), /MOCK/);
    assert.match(await page.getByTestId("external-notice").innerText(), /nothing leaves this computer/i);

    // Crop the label photo by dragging across it.
    const label = page.locator(".photo").nth(1);
    const box = await label.locator(".cropbox").boundingBox();
    await page.mouse.move(box.x + box.width * 0.2, box.y + box.height * 0.25);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width * 0.8, box.y + box.height * 0.75, { steps: 5 });
    await page.mouse.up();
    await label.getByText("Cropped: only the outlined part is analyzed.").waitFor();

    await page.locator("textarea").fill("SYNTHETIC seller: vintage jacket, size M");
    await page.getByTestId("estimate").getByText("Estimated cost: at most").waitFor();
    await page.getByRole("button", { name: "Analyze photos" }).click();
    await page.getByTestId("id-status").waitFor();
    assert.equal(await page.getByTestId("id-status").innerText(), "Ready for human review");
    const result = await page.getByTestId("result").innerText();
    assert.match(result, /Unconfirmed suggestions/);
    assert.match(result, /MOCKBRAND/);
    assert.match(result, /photo 1: MOCK RESPONSE/);            // field-level evidence
    assert.match(result, /cost \$0\.0006/);                    // reconciled actual cost
    assert.match(await main(page), /Identity: not confirmed/);  // a suggestion confirms nothing
    assert.equal(await page.getByTestId("detail-brand").inputValue(), "MOCKBRAND");   // seen in photo: prefilled
    assert.equal(await page.getByTestId("detail-model").inputValue(), "");            // a guess: NOT prefilled
    assert.equal(await page.getByTestId("detail-size").inputValue(), "");             // unknown stays empty

    // Second look: the cost is shown before anything is sent.
    await page.getByRole("button", { name: "Request second look…" }).click();
    const offer = await page.getByTestId("second-offer").innerText();
    assert.match(offer, /gpt-6\.1-terra/);
    assert.match(offer, /costs at most \$0\.0\d+/);
    await page.getByRole("button", { name: "Send second look" }).click();
    const second = await page.getByTestId("second-result").innerText();
    assert.match(second, /disagrees on: style/);
    assert.match(second, /neither replaced the other/);
    assert.match(await page.getByTestId("result").innerText(), /Mock Trucker II/);
    assert.match(await page.getByTestId("result").innerText(), /Mock Trucker\b/);

    // Correct the details, save, and only then confirm.
    await page.getByTestId("detail-brand").fill("Corrected Brand");
    await page.getByTestId("detail-size").fill("M");
    assert.ok(await page.getByRole("button", { name: "Confirm identity" }).isDisabled());
    await page.getByRole("button", { name: "Save details" }).click();
    await page.getByText("Saved.", { exact: true }).waitFor();
    assert.ok(await page.getByRole("button", { name: "Confirm identity" }).isDisabled());      // needs the tick
    await page.locator("label", { hasText: "I have checked the saved details" }).locator("input").check();
    await page.getByRole("button", { name: "Confirm identity" }).click();
    await page.getByTestId("confirmed").waitFor();
    assert.match(await page.getByTestId("allowance").innerText(), /\$1\.99\d\d left of \$2\.0000/);
    await shot("identify");

    // Comparable research, then the financial recommendation.
    await page.getByRole("button", { name: "Continue to comparable research" }).click();
    await page.getByText("No comparables have been entered").waitFor();
    assert.match(await main(page), /Identity confirmed by you/);
    await addComparable(page, "SYNTHETIC sold A", "60");
    await addComparable(page, "SYNTHETIC sold B", "64");
    await page.getByText("C. Conservative expected sale price").waitFor();
    assert.match(await main(page), /\$57\.00/);                 // $60 less 5%; a sale sets the price
    assert.match(await main(page), /2 BUY grade/);
    await shot("research");

    await page.getByRole("button", { name: "Analyze this item" }).click();
    await page.getByText("Conservative expected sale price from 2 comparables").waitFor();
    const form = page.locator("form", { hasText: "Seller and auction" });
    const tick = form.locator("label", { hasText: "I have personally confirmed" }).locator("input");
    assert.ok(await tick.isChecked());                          // carried from the confirmation
    await field(form, "Current bid").fill("1");
    await form.getByRole("button", { name: "Calculate maximum bid" }).click();
    await page.locator(".verdict").waitFor();
    assert.equal(await page.locator(".verdict-word").innerText(), "BUY");
    assert.equal(await page.locator(".verdict-amount").innerText(), "$8.00");
    assert.match(await main(page), /does not place a bid or authorize a purchase/);
    await shot("analyze");

    // Recording the win twice in a row creates one purchase.
    const win = page.locator("form", { hasText: "Did you win it?" });
    await field(win, "Winning bid").fill("3");
    await win.getByRole("button", { name: "Record my win" }).dblclick();
    await page.getByText("Recorded. All-in cost $8.72").waitFor();
    const dash = await (await page.request.get(`${base}/api/dashboard`)).json();
    assert.equal(dash.purchases.length, 1);
    assert.equal(dash.available, "41.28");

    // Changing an identifying detail clears the confirmation tick.
    await field(form, "Brand").fill("Another Brand");
    assert.equal(await tick.isChecked(), false);

    // The earlier BUY is now shown as out of date on the dashboard.
    await nav(page, "Dashboard");
    await page.getByText("Recent analyses").waitFor();
    assert.match(await main(page), /out of date/i);
    await shot("dashboard");
  },

  "failure path: refused and timed-out analyses are never shown as identifications": async ({ page, base, fixtures, shot }) => {
    await page.goto(base);
    await newItemWithPhotos(page, fixtures);
    await page.locator("textarea").fill("[mock:refuse] SYNTHETIC");
    await page.getByRole("button", { name: "Analyze photos" }).click();
    await page.getByTestId("id-status").waitFor();
    assert.equal(await page.getByTestId("id-status").innerText(), "Identification failed");
    assert.match(await page.getByTestId("result").innerText(), /Nothing was identified/);
    assert.equal(await page.getByTestId("detail-brand").inputValue(), "");
    assert.equal(await page.getByRole("button", { name: "Request second look…" }).count(), 0);

    // A timeout may have been billed: the money stays held and is visible.
    await page.locator("textarea").fill("[mock:timeout] SYNTHETIC");
    await page.getByRole("button", { name: "Analyze photos" }).click();
    await page.getByTestId("allowance").getByText("uncertain billing").waitFor();
    assert.equal(await page.getByTestId("id-status").innerText(), "Identification failed");
    assert.match(await page.getByTestId("allowance").innerText(), /2 request\(s\) with uncertain billing/);   // first try and one retry
    await shot("failure");

    // Manual entry still works, and a person can still confirm.
    await page.getByTestId("detail-brand").fill("Typed By Hand");
    await page.getByRole("button", { name: "Save details" }).click();
    await page.getByText("Saved.", { exact: true }).waitFor();
    await page.locator("label", { hasText: "I have checked the saved details" }).locator("input").check();
    await page.getByRole("button", { name: "Confirm identity" }).click();
    await page.getByTestId("confirmed").waitFor();

    // Settle the uncertain requests in Settings after "checking the provider".
    await nav(page, "Settings");
    await page.getByText("Recent AI requests").waitFor();
    page.on("dialog", (d) => d.accept());
    while (await page.getByRole("button", { name: "Not billed" }).count()) {
      const before = await page.getByRole("button", { name: "Not billed" }).count();
      await page.getByRole("button", { name: "Not billed" }).first().click();
      await page.waitForFunction((n) => document.querySelectorAll("button").length && [...document.querySelectorAll("button")].filter((b) => b.textContent === "Not billed").length < n, before);
    }
    const status = await (await page.request.get(`${base}/api/vision/status`)).json();
    assert.equal(status.unresolved_count, 0);
    assert.equal(status.used, "0.000480");                     // only the refused answer was really charged
  },

  "AI allowance exhausted: nothing is sent and manual entry remains": async ({ page, base, fixtures, shot }) => {
    await page.goto(base);
    await settings(page, base, { ai_pilot_allowance: "0.0001" });
    await newItemWithPhotos(page, fixtures);
    await page.getByTestId("estimate").getByText("does not fit").waitFor();
    await page.getByRole("button", { name: "Analyze photos" }).click();
    const alert = page.getByRole("alert");
    await alert.waitFor();
    assert.match(await alert.innerText(), /AI allowance is left\. Nothing was sent\./);
    assert.equal(await page.getByTestId("result").count(), 0);
    await shot("allowance");
    const usage = await (await page.request.get(`${base}/api/vision/usage`)).json();
    assert.deepEqual(usage.map((u) => [u.state, u.charged_cost]), [["BLOCKED", "0.000000"]]);
    await page.getByTestId("detail-brand").fill("Typed By Hand");
    await page.getByRole("button", { name: "Save details" }).click();
    await page.getByText("Saved.", { exact: true }).waitFor();
  },

  "live mode without approval: analysis is unavailable and says why": async ({ page, base, fixtures }) => {
    await page.goto(base);
    await settings(page, base, { vision_provider: "openai" });
    await newItemWithPhotos(page, fixtures);
    assert.match(await page.getByTestId("vision-mode").innerText(), /LIVE — not ready/);
    assert.match(await main(page), /Live AI calls are switched off in Settings/);
    assert.match(await page.getByTestId("external-notice").innerText(), /sent to OpenAI/);
    assert.ok(await page.getByRole("button", { name: "Analyze photos" }).isDisabled());
    await nav(page, "Settings");
    await page.getByText("API key on the server: not set").waitFor();
  },

  "inventory budget exhausted: a win that does not fit is refused": async ({ page, base }) => {
    await page.goto(base);
    await settings(page, base, { weekly_budget: "5.00" });
    await startSession(page);
    const card = page.locator("section.card", { hasText: "synthetic_seller" }).first();
    await card.locator("label", { hasText: "Record an item you won" }).locator("input").fill("SYNTHETIC tee");
    await field(card, "Winning bid").fill("3");
    await card.getByRole("button", { name: "Record purchase" }).click();
    await card.getByText("exceeds the remaining weekly budget of $5.00").waitFor();
    const dash = await (await page.request.get(`${base}/api/dashboard`)).json();
    assert.equal(dash.purchases.length, 0);
    assert.equal(dash.available, "5.00");
  },
};
