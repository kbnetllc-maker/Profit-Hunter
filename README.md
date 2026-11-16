# Profit Hunter

A conservative, AI-assisted resale sourcing tool. It helps decide whether an
auction item is worth bidding on, and the most you can pay while still meeting
strict profit rules. It runs entirely on your own computer.

**Status: v0.1 in progress. Milestones 1 to 4 of 6 are built**: the
calculation engine, the web app, Comparable Research with conservative
valuation, and AI identification from photos. AI identification has only run
against a mock provider; no real model has been called and its accuracy is
untested. Inventory is not built yet. It is a local, single-user tool. It does
not authenticate items and does not guarantee profit. See [docs/ROADMAP.md](docs/ROADMAP.md) and
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
3. **Identify Item** (optional): add photos and review the suggested details, correct them, then confirm the identity yourself.
4. **Comparable Research**: add the item, then enter each comparable listing you find (link, price, for sale or sold, how closely it matches). The page shows the conservative resale value and which listings were used or not, and why.
5. **Analyze Item**: pick the saved item, enter the current bid, and press *Calculate maximum bid*. The sale price comes from the comparables; you can still type your own instead.
6. If you bid and win on Whatnot yourself, record the win. Its cost is reserved from the weekly budget.
7. When the receipt arrives, enter the actual charges in Seller Sessions.

Use **Practice** mode (left sidebar) to try things without touching your real budget.

## Verify it works

Run the automated tests (from the `backend` folder):

```bash
python -m pytest
```

Run the browser tests (from the project folder; they start their own backend
on a throwaway database with the mock AI provider, and never open your data):

```bash
cd frontend
```

```bash
npm run build
```

```bash
cd ..
```

```bash
node e2e/run.cjs
```

On your own computer the browser tests need Playwright once: `cd e2e`, then
`npm install`, then `npx playwright install chromium`.

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
| AI identification | `vision/`, `services/vision_service.py`, `services/ai_ledger.py`, `services/identity_service.py` | Photo checks, mock and OpenAI providers, cost limits, cache, bound confirmation |
| Evaluation | `backend/eval/`, `vision/evaluation.py` | Harness for scoring a real model on labelled photos (not yet run) |
| Web app | `frontend/src/` | Dashboard, Analyze Item, Identify Item, Comparable Research, Seller Sessions, Settings |
| Tests | `backend/tests/`, `e2e/` | 393 backend tests and 5 browser tests, synthetic data |

## How the numbers are defined

- **Expected sale price**: the conservative total a buyer is expected to pay. Not the asking price.
- **Net proceeds**: sale price minus marketplace fee, payment processing, outbound label, packaging and a risk reserve.
- **All-in cost**: bid + incremental inbound shipping + purchase tax.
- **Net profit**: net proceeds minus all-in cost.
- **ROI**: net profit divided by all-in cost.
- **Maximum bid**: the highest whole-increment bid where profit, ROI, max bid, max all-in cost, remaining weekly budget and seller exposure all pass together.

## How an item is valued from comparables

Each comparable falls into one of three grades. The thresholds are settings,
and they are working criteria, not measured accuracy.

| Grade | Rule | Effect |
|---|---|---|
| Excluded | Rejected by you, an auction price or starting bid, a different version, match under 80%, seen more than 90 days ago, or the same link as another entry | Ignored |
| Credible | Everything else | Counts toward the price. It can lower the value, never raise it |
| BUY grade | Credible, match 90% or more, seen within 60 days | Also counts toward a BUY |

At least 2 credible comparables are needed for any valuation; otherwise SKIP.
At least 2 BUY-grade comparables are needed for BUY; otherwise REVIEW at most.

- **A. Lowest credible comparable.** Item price only when the buyer pays shipping separately on your resale marketplace (the Vinted assumption); price plus shipping otherwise, with unknown shipping counted as $0 and said so.
- **B. Competitive listing price** = A less 5%. This is what to *list* at.
- **C. Conservative expected sale price** = B, less a further 15% whenever A is an asking price, including when a higher completed sale exists. Example: sold $30, asking $25 gives B $23.75 and C $20.19. Profit is calculated only from C.
- **Version uncertainty.** While identity is unconfirmed, "might be this version" comparables count and the lowest sets the price. Once confirmed, only same-version listings count.
- **Time to sell** is the slowest credible completed sale that records it, or unknown. Over 90 days is SKIP.

Every analysis stores a copy of its evidence. If the comparables, item,
financial settings or budget change afterwards, the saved result is shown as
out of date with the reason; the stored copy itself is never altered.

## AI identification (Identify Item)

Upload 1 to 3 photos, crop them, optionally add what the seller said, and get
suggested details with the evidence for each. Suggestions are never applied
to boxes you already filled, and never count as identification. Only your own
confirmation does, and changing a detail or photo afterwards withdraws it.

It runs in **mock mode** by default: nothing is sent anywhere and the answers
are obviously fake. Real identification needs an OpenAI API key and your
explicit switch in Settings, and is limited by a separate AI allowance ($2
total, $0.02 per item by default). **No live request has been made yet; real
accuracy is untested.** Details: [docs/VISION.md](docs/VISION.md).

## Known limitations

- AI identification has never run against a real model. Its accuracy, token use and cost are unmeasured.
- No inventory yet (Milestone 5). Realized profit is not tracked yet.
- **Resale marketplace eligibility is unresolved.** It has not been checked whether Vinted (or any other marketplace) permits the selling you intend, in your region, for the brands and categories you buy.
- Comparables are entered by hand. Nothing is looked up automatically, and the app cannot check that a link, price or "sold" status you type is true.
- The match percentage of a comparable is your own judgement.
- The opportunity score's weights are fixed in code and preliminary. The score is saved with each analysis and is not recalculated when the budget changes afterwards.
- The Comparable Research page values an item for your default resale marketplace only; Analyze Item lets you choose another.
- An item counts as identified only when you confirm it yourself.
- The web app has no automated browser tests yet; it was checked by a scripted browser walkthrough during development.
- **Default marketplace fees and shipping estimates are unverified placeholders**, including the assumption that Vinted charges sellers nothing and the buyer pays shipping. Check them against each marketplace's current fee page before trusting any result.
- Whatnot's larger bid steps at higher prices are not known; add them in Settings when you learn them.
- When a seller's additional-item shipping is unknown, a flat $3.00 estimate is used. Weight-based shipping estimates are not implemented.
- Seller exposure is counted per budget week.
- If a real charge settles higher than expected, it is recorded truthfully and the week can show as over budget; new purchases are then blocked.
- The 5% undercut, 15% active-listing discount, 5% risk reserve and the four comparable evidence rules are preliminary assumptions, to be calibrated from real sales.
- Database upgrades only add optional columns, indexes and tables. A change that needs more than that is not supported automatically.

## Data and secrets

The database lives at `data/profit_hunter.db` and photos under `data/images/`
(neither is committed to git). `PROFIT_HUNTER_DB` and `PROFIT_HUNTER_IMAGES`
move them. The only secret is the OpenAI API key, needed solely for live AI
identification. It is read from the `OPENAI_API_KEY` environment variable on
the computer running the backend and is never stored in the database or sent
to the browser. See `backend/.env.example`.
