# Profit Hunter

A conservative, AI-assisted resale sourcing tool. It helps decide whether an
auction item is worth bidding on, and the most you can pay while still meeting
strict profit rules. It runs entirely on your own computer.

**Status: v0.1 in progress. Milestones 1 and 2 of 6 are complete**: the
calculation engine, and a working web app with Dashboard, Analyze Item, Seller
Sessions and Settings. Comparable research, AI screenshot identification and
inventory are not built yet. See [docs/ROADMAP.md](docs/ROADMAP.md) and
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
3. **Analyze Item**: describe the item, enter the current bid and a conservative expected sale price, and press *Calculate maximum bid*.
4. If you bid and win on Whatnot yourself, record the win. Its cost is reserved from the weekly budget.
5. When the receipt arrives, enter the actual charges in Seller Sessions.

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
| Web API | `backend/profit_hunter/api/main.py` | Everything the web app needs; saves every analysis with its inputs |
| Web app | `frontend/src/` | Dashboard, Analyze Item, Seller Sessions, Settings |
| Tests | `backend/tests/` | 108 tests, synthetic data |

## How the numbers are defined

- **Expected sale price**: the conservative total a buyer is expected to pay. Not the asking price.
- **Net proceeds**: sale price minus marketplace fee, payment processing, outbound label, packaging and a risk reserve.
- **All-in cost**: bid + incremental inbound shipping + purchase tax.
- **Net profit**: net proceeds minus all-in cost.
- **ROI**: net profit divided by all-in cost.
- **Maximum bid**: the highest whole-increment bid where profit, ROI, max bid, max all-in cost, remaining weekly budget and seller exposure all pass together.

## Known limitations

- No comparables, AI screenshot identification or inventory yet (Milestones 3 to 5). Realized profit is not tracked yet.
- Identification is manual only: an item counts as identified when you tick the confirmation box.
- The web app has no automated browser tests yet; it was checked by a scripted browser walkthrough during development.
- The expected sale price must be supplied by hand for now; the valuation logic that derives it from comparables is Milestone 3.
- **Default marketplace fees and shipping estimates are unverified placeholders**, including the assumption that Vinted charges sellers nothing and the buyer pays shipping. Check them against each marketplace's current fee page before trusting any result.
- Whatnot's larger bid steps at higher prices are not known; add them in Settings when you learn them.
- When a seller's additional-item shipping is unknown, a flat $3.00 estimate is used. Weight-based shipping estimates are not implemented.
- Seller exposure is counted per budget week.
- If a real charge settles higher than expected, it is recorded truthfully and the week can show as over budget; new purchases are then blocked.
- The 5% undercut, 15% active-listing discount and 5% risk reserve are preliminary assumptions, to be calibrated from real sales.
- Changing the database structure in later milestones may require deleting `data/profit_hunter.db` until migrations are added.

## Data and secrets

The database lives at `data/profit_hunter.db` (not committed to git). Set the
`PROFIT_HUNTER_DB` environment variable to use a different file. No API keys
are needed yet; when they are, they will be read from environment variables.
