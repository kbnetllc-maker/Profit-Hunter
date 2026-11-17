# Development roadmap

## v0.1

- [x] **Milestone 1 — Engine.** Financial calculations, settings, weekly budget ledger, seller sessions and shipping, tests.
- [x] **Milestone 2 — Dashboard and manual item analysis.** Web API, web app (Dashboard, Analyze Item, Seller Sessions, Settings), item and analysis-history tables, every analysis saved with its inputs and settings.
- [x] **Milestone 3 — Comparables and conservative valuation.** Manual comparable entry, include/reject with reasons, active vs sold evidence kept separate, lowest credible comparable, 5% undercut, 15% active-only discount, least-valuable-variation rule, expected holding time, opportunity ranking, lookup-adapter extension point (no adapter installed).
- [x] **Milestone 4 — AI identification from photos (mock-tested only).** Provider-independent interface, mock and OpenAI providers, field-level evidence, cost ledger with reservations, cache, second look on request, confirmation bound to details and photos, evaluation harness. Live accuracy and cost are unmeasured pending approval and labelled photos.
- [ ] **Milestone 5 — Inventory and real results.** Listings, completed resales, realized profit vs prediction, days held.
- [ ] **Milestone 6 — End-to-end tests and documentation.**

## Open decisions for the owner

1. Confirm what Vinted's 3% is charged on (item price is assumed) and that the buyer pays shipping.
2. Typical packaging cost per item (default: $0.50).
3. Whatnot's bid-step thresholds at higher prices (enter in Settings when known).
4. Supply an OpenAI API key on a paid tier when ready (spending is approved; live calls stay off until then).
5. Review the draft labels of the 40-photo evaluation set before any scored run.

Decided (17 Nov 2026): live AI spending approved by the owner, on hold until a key exists; Vinted charges a 3% seller fee and permits the intended selling (owner's statement). Decided earlier: OpenAI `gpt-6-luna` first look, `gpt-6.1-terra` second look on request; comparable rules 2 credible, 80% floor, 90% and 60 days for BUY grade, 90-day maximum age and holding time; the asking-price discount applies whenever an asking price sets the value. Central time (America/Chicago), week starts Monday, 9% purchase tax on bid + shipping, resell on Vinted, $1 bid steps.

## Later (not in v0.1; each needs separate authorization and review)

Authorized livestream ingestion, real-time recognition, speech-to-text, multiple
monitored streams, seller prioritization, auction countdown tracking, opportunity
alerts, calibration from sales history, automated inventory listing, authorized
bidding integrations. Weight-based shipping estimates. Database migrations.
Marketplace lookup adapters (documented, authorized APIs only). Editable ranking weights.

No unattended Whatnot monitoring, scraping or automated bidding will be built
without explicit authorization.
