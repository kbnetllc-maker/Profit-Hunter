# Development roadmap

## v0.1

- [x] **Milestone 1 — Engine.** Financial calculations, settings, weekly budget ledger, seller sessions and shipping, tests.
- [x] **Milestone 2 — Dashboard and manual item analysis.** Web API, web app (Dashboard, Analyze Item, Seller Sessions, Settings), item and analysis-history tables, every analysis saved with its inputs and settings.
- [x] **Milestone 3 — Comparables and conservative valuation.** Manual comparable entry, include/reject with reasons, active vs sold evidence kept separate, lowest credible comparable, 5% undercut, 15% active-only discount, least-valuable-variation rule, expected holding time, opportunity ranking, lookup-adapter extension point (no adapter installed).
- [x] **Milestone 4 — AI identification from photos (mock-tested only).** Provider-independent interface, mock and OpenAI providers, field-level evidence, cost ledger with reservations, cache, second look on request, confirmation bound to details and photos, evaluation harness. Live accuracy and cost are unmeasured pending approval and labelled photos.
- [ ] **Milestone 5 — Inventory and real results.** Listings, completed resales, realized profit vs prediction, days held.
- [ ] **Milestone 6 — End-to-end tests and documentation.**

## Open decisions for the owner

1. Confirm Vinted's real seller costs (fees, who pays shipping) and correct them in Settings.
2. Typical packaging cost per item (default: $0.50).
3. Whatnot's bid-step thresholds at higher prices (enter in Settings when known).
4. Approve live AI spending and supply an OpenAI API key on a paid tier.
5. Supply 40 to 50 labelled real photo sets for the vision evaluation.
6. Whether each intended resale marketplace permits the intended selling.

Decided: OpenAI `gpt-6-luna` first look, `gpt-6.1-terra` second look on request; comparable rules 2 credible, 80% floor, 90% and 60 days for BUY grade, 90-day maximum age and holding time; the asking-price discount applies whenever an asking price sets the value. Central time (America/Chicago), week starts Monday, 9% purchase tax on bid + shipping, resell on Vinted, $1 bid steps.

## Later (not in v0.1; each needs separate authorization and review)

Authorized livestream ingestion, real-time recognition, speech-to-text, multiple
monitored streams, seller prioritization, auction countdown tracking, opportunity
alerts, calibration from sales history, automated inventory listing, authorized
bidding integrations. Weight-based shipping estimates. Database migrations.
Marketplace lookup adapters (documented, authorized APIs only). Editable ranking weights.

No unattended Whatnot monitoring, scraping or automated bidding will be built
without explicit authorization.
