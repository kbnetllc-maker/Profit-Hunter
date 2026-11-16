# Changelog

## Unreleased (v0.1)

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
