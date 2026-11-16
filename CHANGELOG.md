# Changelog

## Unreleased (v0.1)

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
