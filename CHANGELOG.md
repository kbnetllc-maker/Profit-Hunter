# Changelog

## Unreleased (v0.1)

### 2026-11-17
- Vinted default fee is now 3% of the item price (owner's figure), marked verified. Existing saved settings are not changed.
- Photos in MPO format (written by many phones) are accepted, using the main frame.
- Fixed: an embedded JPEG text comment or color profile could survive metadata removal. Preprocessing version is now `pre-2`.
- Imported the "public-starter-40" evaluation set locally (not in git) and ran a mock dry run. No live calls.
- Fixed: the comparable form used the browser's date, so near midnight a browser ahead of the configured timezone was refused with "date cannot be in the future". The form now uses the server's date. Found by the browser test when the date rolled over.
- Recorded the owner's approval of live API spending; live calls remain off until a key is supplied.

### Milestone 4 — AI identification, and a financial audit
- Identify Item page: upload and crop 1 to 3 photos, add seller text, get suggested details with a basis and source for each, correct them, confirm.
- Provider-independent vision interface with a mock provider and an OpenAI adapter (Responses API, structured output). Live calls are off by default and have never been made.
- AI cost ledger in micro-dollars: reservation before each call, reconciliation after, held "billing uncertain" amounts for timeouts, $2 total and $0.02 per-item limits, one bounded retry, no hidden SDK retries, dated prices.
- Identification cache keyed by workspace, photos, text, model and versions.
- Second look on request only, with the cost shown first; both answers kept and differences listed.
- Identity confirmation is bound to the exact details and photos and is withdrawn when they change.
- Uploads are checked by content, stripped of metadata and stored under random names; photos can be deleted.
- Audit fixes (see docs/AUDIT.md): BUY-grade comparable tiers (90% match, 60 days), duplicate links counted once, asking-price discount whenever an asking price sets the value, a model's confidence can never unlock BUY, concurrent and repeated win recording made safe, budget change and week-boundary change races closed, out-of-date flags on saved analyses, in-place database upgrades.
- Evaluation harness and labelling template for real photos; cost projection and commercial-readiness notes (docs/VISION.md).
- Permanent browser tests (`e2e/`). 393 backend tests.

### Milestone 3 — Comparables and conservative valuation
- Comparable Research page: add, edit, reject (with a reason), restore, delete and filter comparables; exact source link shown for each.
- Comparables store marketplace, title, link, asking or sold price, shipping, condition, size, variation, match, listing type, date observed and the reason for inclusion or exclusion.
- Valuation engine: lowest credible comparable, 5% undercut, further 15% discount when only asking prices exist. Auction prices are never evidence.
- Version rule: an unconfirmed item is priced as the least valuable version it might be; different versions are excluded.
- Expected time to sell from completed sales; slower than the limit is SKIP (holding risk).
- Analyze Item can take its sale price from a saved item's comparables and shows the comparables used and not used. A snapshot of the evidence is saved with every such analysis.
- Opportunity score (0-100, eight factors) on each BUY/REVIEW analysis; ranked list on the Dashboard.
- New editable settings: minimum credible comparables, minimum match, maximum comparable age, maximum time to sell. Discount rates must be below 100%.
- Extension point for authorized marketplace lookups with a timeout; no adapter installed.
- New tables `comparable_listings` and `valuations` are added to an existing database without a reset.
- 26 new tests (134 total).

### Milestone 2 — Dashboard and manual item analysis
- Web API (FastAPI) for settings, dashboard, seller sessions, purchases and item analysis.
- Web app (React): Dashboard, Analyze Item, Seller Sessions, Settings, with separate Real and Practice modes.
- Every analysis is saved with its exact inputs and the settings in force.
- Owner defaults: Central time, 9% purchase tax, Vinted as resale marketplace.
- Configurable larger bid steps at higher prices; per-marketplace outbound shipping.
- Changing the weekly budget applies to the week in progress; earlier weeks keep their budget.
- Fixed: database start-up race when several requests arrive at once.

### Milestone 1 — Engine
- Exact decimal money handling; integer cents in SQLite.
- Configurable settings with the project's default limits; automatic purchasing cannot be enabled and human approval cannot be disabled.
- Marketplace fee profiles (eBay, Poshmark, Mercari, Depop, Vinted) as unverified placeholders.
- Acquisition cost, sale proceeds, net profit, ROI, margin and resale multiple.
- Maximum-bid solver satisfying profit, ROI, max bid, max all-in, weekly budget and seller exposure together.
- BUY / REVIEW / SKIP rules including risk-policy rejections.
- Seller sessions, bundles, shipping caps, weekly bundling, incremental and allocated shipping.
- Weekly budget ledger with commitments, settlement, cancellation, and separate simulated mode.
- 99 automated tests and a runnable demo (`python -m profit_hunter.demo`).
