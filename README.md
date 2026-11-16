# Profit Hunter

A conservative, AI-assisted resale sourcing tool. It helps decide whether an
auction item is worth bidding on, and the most you can pay while still meeting
strict profit rules. It runs entirely on your own computer.

**Status: v0.1 in progress. Milestones 1 to 3 of 6 are complete**: the
calculation engine, a working web app (Dashboard, Analyze Item, Seller
Sessions, Settings), and Comparable Research with conservative valuation. AI
screenshot identification and inventory are not built yet. See [docs/ROADMAP.md](docs/ROADMAP.md) and
[CHANGELOG.md](CHANGELOG.md).

Profit Hunter never places bids or buys anything. A BUY result is a
recommendation only; you approve every purchase yourself.

## Install (one time)

You need Python 3.11 or newer and Node.js 20 or newer.

Backend:

```bash
cd backend
python -m venv .venv
```

Activate the environment. On macOS/Linux:

```bash
source .venv/bin/activate
```

On Windows:

```bash
.venv\Scripts\activate
```

Then install:

```bash
pip install -e ".[dev]"
```

Frontend (in a second terminal, from the project folder):

```bash
cd frontend
npm install
```

## Start the app

Terminal 1, the backend (from `backend`, with the environment activated):

```bash
uvicorn profit_hunter.api.main:app --reload
```

Terminal 2, the frontend (from `frontend`):

```bash
npm run dev
```

Then open http://localhost:5173 in your browser.

**One-terminal alternative:** run `npm run build` once in `frontend`, then start
only the backend and open http://localhost:8000. Re-run the build after any
frontend change.

## Using it

1. **Settings**: check every number, especially tax and marketplace fees.
2. **Seller Sessions**: start a session for the seller you are watching and enter their shipping terms if you know them.
3. **Comparable Research**: add the item, then enter each comparable listing you find (link, price, for sale or sold, how closely it matches). The page shows the conservative resale value and which listings were used or not, and why.
4. **Analyze Item**: pick the saved item, enter the current bid, and press *Calculate maximum bid*. The sale price comes from the comparables; you can still type your own instead.
5. If you bid and win on Whatnot yourself, record the win. Its cost is reserved from the weekly budget.
6. When the receipt arrives, enter the actual charges in Seller Sessions.

Use **Practice** mode (left sidebar) to try things without touching your real budget.

## Verify it works

Run the automated tests (from the `backend` folder):

```bash
python -m pytest
```

Run the command-line demonstration with synthetic data:

```bash
python -m profit_hunter.demo
```

## What exists today

| Part | Where | What it does |
|---|---|---|
| Money | `backend/profit_hunter/money.py` | Exact decimal dollars; floats are refused |
| Settings | `config.py`, `services/settings_service.py` | Every limit and assumption, editable and saved |
| Profit maths | `engine/profit.py` | All-in cost, fees, net proceeds, profit, ROI, margin, multiple |
| Maximum bid | `engine/max_bid.py` | Highest bid that passes all six limits at once |
| Decision | `engine/decision.py` | BUY / REVIEW / SKIP with reasons |
| Shipping | `engine/shipping.py`, `services/sessions_service.py` | Seller sessions, bundles, caps, incremental shipping |
| Budget | `engine/ledger.py`, `services/budget_service.py` | Weekly ledger; blocks overspending |
| Valuation | `engine/valuation.py`, `services/valuation_service.py` | Conservative sale price from comparables, with a reason for every listing used or excluded |
| Ranking | `engine/ranking.py` | 0-100 opportunity score from eight weighted factors |
| Lookup framework | `marketplaces.py` | Extension point for authorized marketplace APIs. No adapter is installed |
| Web API | `backend/profit_hunter/api/main.py` | Everything the web app needs; saves every analysis with its inputs |
| Web app | `frontend/src/` | Dashboard, Analyze Item, Comparable Research, Seller Sessions, Settings |
| Tests | `backend/tests/` | 134 tests, synthetic data |

## How the numbers are defined

- **Expected sale price**: the conservative total a buyer is expected to pay. Not the asking price.
- **Net proceeds**: sale price minus marketplace fee, payment processing, outbound label, packaging and a risk reserve.
- **All-in cost**: bid + incremental inbound shipping + purchase tax.
- **Net profit**: net proceeds minus all-in cost.
- **ROI**: net profit divided by all-in cost.
- **Maximum bid**: the highest whole-increment bid where profit, ROI, max bid, max all-in cost, remaining weekly budget and seller exposure all pass together.

## How an item is valued from comparables

A comparable is **credible** when you have not rejected it, it is not an
auction price or starting bid, it is not a different version of the item, its
match is at least 80%, and you saw it within the last 90 days. At least 2
credible comparables are required; otherwise there is no valuation and the
result is SKIP. All four numbers are editable in Settings.

- **A. Lowest credible comparable.** Item price only when the buyer pays shipping separately on your resale marketplace (the Vinted assumption); price plus shipping otherwise.
- **B. Competitive listing price** = A less 5%. This is what to *list* at.
- **C. Conservative expected sale price** = B, less a further 15% when no credible completed sale exists. This is what to *expect*, and the only figure profit is calculated from.
- **Version uncertainty.** Each comparable is marked as the same version, a version the item *might* be, or a different version. While the item's identity is unconfirmed, "might be" versions count and the lowest sets the price. Once confirmed, only same-version listings count.
- **Time to sell** is the slowest credible completed sale that records it, or unknown. Over 90 days is SKIP.
- **Evidence**: STRONG (2 or more sales), MODERATE (1 sale), WEAK (asking prices only).

Every analysis stores a copy of the comparables it used, so later edits or
deletions never change a past recommendation's record.

## Known limitations

- No AI screenshot identification or inventory yet (Milestones 4 and 5). Realized profit is not tracked yet.
- Comparables are entered by hand. Nothing is looked up automatically, and the app cannot check that a link, price or "sold" status you type is true.
- The match percentage of a comparable is your own judgement.
- With completed-sale evidence present, a lower asking price still sets the value with only the 5% undercut (no 15% discount).
- The opportunity score's weights are fixed in code and preliminary. The score is saved with each analysis and is not recalculated when the budget changes afterwards.
- The Comparable Research page values an item for your default resale marketplace only; Analyze Item lets you choose another.
- Identification is manual only: an item counts as identified when you tick the confirmation box.
- The web app has no automated browser tests yet; it was checked by a scripted browser walkthrough during development.
- **Default marketplace fees and shipping estimates are unverified placeholders**, including the assumption that Vinted charges sellers nothing and the buyer pays shipping. Check them against each marketplace's current fee page before trusting any result.
- Whatnot's larger bid steps at higher prices are not known; add them in Settings when you learn them.
- When a seller's additional-item shipping is unknown, a flat $3.00 estimate is used. Weight-based shipping estimates are not implemented.
- Seller exposure is counted per budget week.
- If a real charge settles higher than expected, it is recorded truthfully and the week can show as over budget; new purchases are then blocked.
- The 5% undercut, 15% active-listing discount, 5% risk reserve and the four comparable evidence rules are preliminary assumptions, to be calibrated from real sales.
- Changing the database structure in later milestones may require deleting `data/profit_hunter.db` until migrations are added.

## Data and secrets

The database lives at `data/profit_hunter.db` (not committed to git). Set the
`PROFIT_HUNTER_DB` environment variable to use a different file. No API keys
are needed yet; when they are, they will be read from environment variables.
