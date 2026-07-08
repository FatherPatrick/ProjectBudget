# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-user, local-only personal finance app (FastAPI + SQLite + vanilla JS, no build step).
The owner imports bank-statement CSVs (Chase credit, Chase debit, BofA credit), the app
auto-categorizes spending, and the dashboard reports by category/time range. **It is designed
to never be deployed**: no outbound requests (Chart.js is vendored in `static/vendor/`), and
all financial data lives in git-ignored `data/budget.db`. Never commit anything under `data/`
or any real statement CSV.

## Commands

```
run.bat                                          # launch app at http://localhost:8000 (creates .venv, installs deps)
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000   # same, without the wrapper

.venv\Scripts\python.exe -m pip install -r requirements-dev.txt   # test deps (pytest, httpx)
.venv\Scripts\python.exe -m pytest tests -q                       # full suite
.venv\Scripts\python.exe -m pytest tests/test_categorize.py::test_gresham_portland_locals -q   # single test
```

There is no linter or build step. Interactive API docs at `/docs` when running.

Ad-hoc scripts must set `PYTHONPATH` to the repo root to import `app.*`, and go in a scratch
directory — not the repo.

## Architecture: the transaction pipeline

Everything is one flow; each stage lives in one module:

1. **`app/importers.py`** — CSV bytes → normalized records. Bank formats are detected by
   header signature (never filename), via per-bank `Adapter` subclasses. Preamble/summary
   lines before the real header are skipped — including when `format` is forced.
   **Sign convention: positive amount = money spent, negative = money in.** All three banks
   use the opposite convention raw, so adapters flip the sign (`flip_sign`).
2. **`app/db.py`** — SQLite at `data/budget.db`. Dedupe is a UNIQUE `hash` column:
   `sha1(account|date|amount|description)`, with an occurrence counter appended for the
   Nth identical row within a file (first occurrence keeps the base hash). **Do not change
   the hash format** — existing rows would stop deduping and re-imports would double-count.
   Schema changes go in `_migrate()` as additive `ALTER TABLE`s; `init_db()` is idempotent
   and runs from the FastAPI lifespan hook.
3. **`app/categorize.py`** — resolution order: learned DB rules (lowest `priority`, then id)
   → built-in `_STARTER` ruleset → `Uncategorized`. Rules are case-insensitive substring
   matches against whitespace-collapsed descriptions, optionally direction-gated
   (`'in'` = amount < 0, `'out'` = amount > 0).
4. **`app/reports.py`** — spend = `amount > 0` excluding `Transfer/Payment` and `Income`.
   Ranges anchor to the latest transaction by default (statements lag the calendar).
5. **`static/app.js` + `static/index.html`** — no framework. Escape user data with `esc()`.
   Theme is CSS custom properties (light/dark via `prefers-color-scheme`); charts read
   colors through `cssVar()`, so renaming a report API field or CSS variable requires a
   matching app.js change.

## Invariants that are easy to break

- **`_STARTER` in categorize.py is an ORDERED list and the order is load-bearing.**
  Card-payment descriptors come first so a debit charge paying off a credit card is always
  `Transfer/Payment` and never double-counted as a Bill; generic transfer keywords
  (`AUTOPAY`, `ONLINE PAYMENT`, `PYMT`) come dead last so named billers win. In between,
  specifics must precede the generics that would swallow them: Food before Transport
  (`UBER EATS` vs `UBER`), Transport before Grocery (`COSTCO GAS` vs `COSTCO`), Health
  before Travel (`DELTA DENTAL` vs `DELTA`).
- **Substring collisions are the main hazard when adding rules.** The owner lives in
  Gresham, OR, so nearly every local merchant description ends in "GRESHAM OR" — a bare
  city/region pattern will swallow groceries and restaurants (use `CITY OF GRESHAM`, not
  `GRESHAM`). Same class of bug: `TACO ` not `TACO` (Tacoma), `ACH DEBIT` not `ACH`
  (COACH). Bank descriptors also truncate mid-word — patterns like `RESTAU` and
  `INTERNATIONAL MARK` exist on purpose.
- **Owner-specific semantics are learned DB rules, not starter rules** (e.g. Unitus CU =
  reimbursed car payment → Transfer/Payment; Venmo/Cash App out → Fun). They live in the
  `rules` table, outrank everything, and are managed in the dashboard — don't encode
  personal one-offs into `_STARTER`.
- **`manually_set = 1` pins a transaction's category.** `reapply_all()` must keep skipping
  pinned rows, or manual fixes get silently clobbered on the next rule change.
- **Income starter patterns are direction-gated `'in'`** so spends containing
  `REFUND`/`DEPOSIT` can't claim to be income. All incoming P2P (Venmo, Cash App,
  Apple Cash) is deliberately Income — the owner is reimbursed through these apps.
- **History floor**: combined reports clamp to the latest per-account start date (so the
  window is only where every source has data); a single-account filter uses that account's
  own earliest date. Implemented in `reports._history_floor()`.

## Tests

`tests/conftest.py` has an autouse fixture that points `app.db` at a temp database — every
test runs isolated from `data/budget.db`, and API tests use FastAPI's `TestClient` via the
`client` fixture. CSV fixtures in `tests/fixtures.py` are small anonymized samples shaped
exactly like each bank's real export; extend those rather than inventing new shapes. When
changing categorization rules, add the real-world descriptor to the regression tests in
`tests/test_categorize.py` (see `test_gresham_portland_locals`).

After rule changes, categories for existing data only update via `reapply_all()` (triggered
by teaching/deleting a rule, or run directly); imports categorize at insert time.

## Conventions

- **Never `git commit` or `git push` without the owner's explicit confirmation in the
  current conversation — including in auto-accept/auto modes.** Prepare the change and
  the commit message, then ask. (`.claude/settings.json` also enforces this with `ask`
  permission rules on `git commit*` / `git push*`.)
- README.md has a checked-off TODO section recording completed work and an API table —
  keep both in sync when adding endpoints or features.
- Bank CSV exports in the wild may have BOMs, preamble lines, padded whitespace, and
  parenthesized negatives; `importers.py` handles all of these — preserve that tolerance.
