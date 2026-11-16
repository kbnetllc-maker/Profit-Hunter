# Profit Hunter

A conservative, AI-assisted resale sourcing tool. It helps decide whether an
auction item is worth bidding on, and the most you can pay while still meeting
strict profit rules. It runs entirely on your own computer.

**Status: v0.1 in progress. Milestone 1 of 6 is complete** (the calculation
engine and its database layer). There is no web interface yet; that is
Milestone 2. See [docs/ROADMAP.md](docs/ROADMAP.md) and [CHANGELOG.md](CHANGELOG.md).

Profit Hunter never places bids or buys anything. A BUY result is a
recommendation only; you approve every purchase yourself.

## Install (one time)

You need Python 3.11 or newer.

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

## Verify it works

Run the automated tests (from the `backend` folder):

```bash
python -m pytest
```

Run the demonstration, which walks through five synthetic items and prints the
maximum bid and BUY / REVIEW / SKIP result for each:

```bash
python -m profit_hunter.demo
```

The demo uses made-up data and a temporary database. Nothing is saved.

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
| Tests | `backend/tests/` | 99 tests, synthetic data |

## How the numbers are defined

- **Expected sale price**: the conservative total a buyer is expected to pay. Not the asking price.
- **Net proceeds**: sale price minus marketplace fee, payment processing, outbound label, packaging and a risk reserve.
- **All-in cost**: bid + incremental inbound shipping + purchase tax.
- **Net profit**: net proceeds minus all-in cost.
- **ROI**: net profit divided by all-in cost.
- **Maximum bid**: the highest whole-increment bid where profit, ROI, max bid, max all-in cost, remaining weekly budget and seller exposure all pass together.

## Known limitations

- No web interface, item records, comparables, AI identification or inventory yet (Milestones 2 to 5).
- The expected sale price must be supplied by hand for now; the valuation logic that derives it from comparables is Milestone 3.
- **Default marketplace fees, the 7% purchase tax, and shipping estimates are unverified placeholders.** Check them against each marketplace's current fee page and your own tax rate before trusting any result.
- When a seller's additional-item shipping is unknown, a flat $3.00 estimate is used. Weight-based shipping estimates are not implemented.
- Seller exposure is counted per budget week.
- If a real charge settles higher than expected, it is recorded truthfully and the week can show as over budget; new purchases are then blocked.
- The 5% undercut, 15% active-listing discount and 5% risk reserve are preliminary assumptions, to be calibrated from real sales.
- Changing the database structure in later milestones may require deleting `data/profit_hunter.db` until migrations are added.

## Data and secrets

The database lives at `data/profit_hunter.db` (not committed to git). Set the
`PROFIT_HUNTER_DB` environment variable to use a different file. No API keys
are needed yet; when they are, they will be read from environment variables.
