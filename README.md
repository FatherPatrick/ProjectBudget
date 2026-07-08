# ProjectBudget

A local, private personal-finance app. Import bank-statement CSVs (Chase credit,
Chase debit, Bank of America credit), auto-categorize spending, and see reports by
category and time range. Everything stays on your machine — no cloud, no deploy,
no financial data ever leaves your computer.

## Run

```
run.bat
```

First launch creates a virtual environment and installs dependencies, then serves
the app at <http://localhost:8000>. Interactive API docs at <http://localhost:8000/docs>.

> If port 8000 is busy, change the port in [run.bat](run.bat).

## Features

- **Multi-bank import** — auto-detects Chase credit, Chase debit, and Bank of
  America credit CSVs from their headers; mix and drop in as many files as you like.
- **Spending by category** — Bills, Food, Grocery, Fun, Subscriptions, Transport,
  Shopping, Health, Travel, Fees, Income, Transfer/Payment.
- **Top 5 purchases per category** — click any category in the breakdown to expand.
- **Time ranges** — last 30 days, 3 months, 6 months, 1 year, or all.
- **Account filter** — view all accounts combined or one at a time.
- **Charts** — spending doughnut + month-over-month trend (Chart.js, vendored offline).
- **Learns as you go** — assign a category to any unknown merchant and it writes a
  rule, then re-categorizes your whole history automatically.

## Exporting statements (CSV)

- **Chase:** Account activity → download as CSV (works for both the credit card and
  the debit/checking account).
- **Bank of America:** Statements & Documents / account activity → download as CSV.

Then open the app and use the **Import** box at the top of the dashboard. Re-uploading
an overlapping statement is safe — duplicates are skipped automatically.

## Using the dashboard

1. **Import** one or more CSVs — the result shows what was detected and how many rows
   were new vs. duplicate.
2. Pick a **range** (30d / 3mo / 6mo / 1yr / All) and optionally an **account**.
3. Read the **summary cards**, **charts**, and the **breakdown table** (click a
   category row to see its top 5 purchases).
4. Work the **"Teach the app"** panel: assign a category to any uncategorized
   merchant from the dropdown. A rule is saved and applied across all history.

## How it works

**Normalized schema.** Every bank CSV is mapped to a common shape
(`date, description, amount, account, category`) where **positive amount = money
spent** and negative = money in (income, refunds, payments). Each bank has a small
adapter in [app/importers.py](app/importers.py); detection is by header signature,
so the file name doesn't matter.

**De-duplication.** Each transaction gets a content hash (account + date + amount +
description), enforced unique in the database — so importing overlapping statements
never double-counts.

**Categorization** ([app/categorize.py](app/categorize.py)) resolves in order:

1. **Learned rules** you've taught (stored in the DB, highest priority).
2. **Built-in starter ruleset** (~530 patterns + your specifics).
3. Fallback to **Uncategorized**.

Rules are case-insensitive substring matches, with whitespace collapsed (bank
descriptions pad fields with many spaces). Rules can be **direction-conditional**:
e.g. money *in* via Venmo or Cash App counts as Income, while payments *out* don't.

The starter ruleset is **priority-ordered** to avoid misfiles:

1. **Card-payment descriptors first** (`CHASE CREDIT CRD AUTOPAY`,
   `BANK OF AMERICA CREDIT CARD Bill Payment`, `PAYMENT THANK YOU`, other
   issuers' `CRCARDPMT`-style strings) → always Transfer/Payment, so the debit
   charge that pays off a card is never double-counted as a Bill.
2. **Income patterns**, gated to money-in only, so a spend containing
   "REFUND" or "DEPOSIT" can't claim to be Income.
3. **Bills**: mortgage servicers (Rocket, Mr. Cooper, PennyMac, ...), student
   loans (Nelnet, MOHELA, Aidvantage, ...), car loans (Toyota Financial, GM
   Financial, CarMax, ...), utilities (PGE, NW Natural, ...), waste (`WASTE
   MGMT WM EZPAY`, Republic Services), internet/TV/phone, and insurance.
4. Merchant groups — ordered so specifics win: `UBER EATS` → Food before
   `UBER` → Transport, `COSTCO GAS` → Transport before `COSTCO` → Grocery,
   `DELTA DENTAL` → Health before `DELTA` → Travel.
5. **Generic transfer keywords dead last** (`AUTOPAY`, `ONLINE PAYMENT`,
   `PYMT`), so "ONLINE PAYMENT TO PORTLAND GENERAL" still lands in Bills.

**Spend vs. transfers.** `Transfer/Payment` (credit-card payments, internal
transfers) and `Income` are excluded from spend totals, so paying off a card or
getting a paycheck doesn't distort the spending breakdown.

**History floor.** For the combined view, reports never start earlier than the
point where **every imported source account** has data — a card whose statements
begin later would make older months read artificially low. When filtering to a
single account, that account's full history is shown instead. The dashboard notes
when a range is clamped.

## API (for scripting / the docs page)

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/upload` | Import CSV file(s); optional `format` override |
| GET | `/report?range=6mo&account=&anchor=latest` | Full report payload |
| GET | `/summary` | Quick spend-by-category across all data |
| GET | `/transactions?limit=&category=` | Recent transactions |
| GET | `/uncategorized` | Merchants still needing a category |
| GET | `/accounts` / `/categories` | Filter options |
| GET | `/rules` | List learned rules |
| POST | `/rules` | Teach a rule (`pattern`, `category`, optional `direction`) |
| DELETE | `/rules/{id}` | Delete a learned rule (re-categorizes history) |
| POST | `/categories` | Add a custom category (`name`) |
| POST | `/transactions/{id}/category` | Re-categorize one transaction (pins it against rule changes) |
| GET | `/export/transactions.csv` | Download all transactions as a CSV backup |
| POST | `/reset` | Wipe transactions + rules (requires `confirm=DELETE`) |

## Status

- [x] Phase 1 — scaffold, SQLite schema, launcher
- [x] Phase 2 — CSV import pipeline (per-bank adapters, normalize, dedupe)
- [x] Phase 3 — categorization (rules + learning, starter ruleset)
- [x] Phase 4 — reports API (by category, top-5, 30d/6mo/1yr ranges)
- [x] Phase 5 — web dashboard (upload, charts, inline re-categorize)
- [x] Phase 6 — validated against real Chase debit, Chase credit, and BofA credit CSVs

## TODO

Suggested changes from a code review (2026-07-08). **All completed 2026-07-08.**

### Bugs & correctness

- [x] **Fix the forced `format` override in [app/importers.py](app/importers.py).**
  A forced format now scans past preamble lines for its real header row (matching
  the columns it actually reads), and an unknown `format` value fails fast with
  the valid format names.
- [x] **Dedupe hash collides on identical same-day transactions.** Repeats within a
  file now get an occurrence-derived hash; the first occurrence keeps the original
  hash so existing databases stay deduplicated.
- [x] **Manual re-categorizations get clobbered.** One-off edits via
  `POST /transactions/{id}/category` set `manually_set = 1`, and `reapply_all()`
  skips pinned rows.
- [x] **Migrate off deprecated `@app.on_event("startup")`** — now a lifespan handler.

### Cleanup

- [x] **Remove `pandas` from [requirements.txt](requirements.txt)** (was unused).
- [x] Public `get_rules()` in [app/categorize.py](app/categorize.py) replaces the
  private `_db_rules()` reach-in.
- [x] `report()`'s `range` parameter renamed to `range_key` (query param still `range`).
- [x] `limit` query params capped (1–1000) on `/transactions` and `/uncategorized`.
- [x] Shared `_require_valid_category()` helper replaces endpoint-function reuse.

### Features

- [x] **Rules management UI/API** — `GET /rules`, `DELETE /rules/{id}`, and a
  "Learned rules" panel in the dashboard with per-rule delete.
- [x] **Export / backup** — `GET /export/transactions.csv` plus a danger-zone reset
  (`POST /reset`, requires typing DELETE) in the dashboard's Tools panel.
- [x] **Custom categories** — `POST /categories` + an "Add category" input in Tools.
- [x] **Explicit date-range picker** — From/To date inputs in the header (presets
  clear them and vice versa).
- [x] **Partial-month indicator on the trend chart** — partially-covered months are
  drawn muted, starred, and labeled "(partial month)" in the tooltip.

### Dev experience

- [x] **Add tests** — 34 pytest tests in [tests/](tests/) covering the three
  adapters, preamble/forced-format handling, occurrence hashing, categorization
  precedence & direction rules, report math (spend exclusions, history floor,
  partial months), and the API surface end-to-end.
  Run with: `pip install -r requirements-dev.txt && pytest`
- [x] **Harden [run.bat](run.bat)** — clear error if Python is missing, and deps
  re-install automatically whenever requirements.txt changes.
- [x] **Light-theme support** — theme colors follow `prefers-color-scheme`; charts
  read their colors from the CSS variables and re-render on OS theme flips.

## Project layout

```
app/
  main.py        FastAPI app + endpoints (upload, report, rules, ...)
  db.py          SQLite schema & connection
  importers.py   per-bank CSV adapters + normalizer
  categorize.py  rules engine, starter ruleset, learning
  reports.py     aggregation: by category, top-5, time ranges, trend
static/
  index.html     dashboard UI
  app.js         dashboard logic (fetches /report, renders charts)
  vendor/chart.min.js   charting library (vendored, offline)
tests/           pytest suite (adapters, categorization, reports, API)
data/budget.db   local database (git-ignored — your data stays here)
run.bat          launcher
```

## Privacy

This app is designed to never be deployed. Your statements and the `data/` database
are git-ignored and stay on your machine. Chart.js is vendored locally, so the app
makes no outbound network requests.
