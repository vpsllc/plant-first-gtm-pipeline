# Plant-first account selection for a predictive maintenance seller

A small CLI pipeline that builds the input table for a Clay workbook. The scenario: a predictive maintenance platform sells to large manufacturers, wins start at one plant and spread, and a list of every manufacturer over $1B got near-zero replies. This pipeline ranks on the things that actually predict a deal instead: plant footprint, a live reliability-hiring trigger at a named plant, and whether the parent is already a customer somewhere.

Augury stands in as the seller. Every customer flag comes from a public announcement, with the source URL and date.

## What it does

| Step | Script | Source | Output |
|---|---|---|---|
| 1 | `scripts/01_plant_counts.py` | SEC EDGAR (free) finds each 10-K; Firecrawl extracts the plant count from Item 2 "Properties" with a supporting quote. Annual reports for non-US filers. | `out/plant_counts.csv` |
| 2 | `scripts/02_triggers.py` | Firecrawl reads employer job boards. Seed postings are opened on the employer's own site to confirm they are open; board searches cover the rest. | `out/triggers.csv`, `out/triggers_best.csv` |
| 3 | `scripts/03_merge.py` | Joins the parent map, counts and triggers. No tiering here. | `out/clay_import.csv`, `out/run_report.md` |

Tiering, ranking and play routing live in Clay as formulas, so the logic is visible in the table. Rows marked `trigger_source=clay` are left for Clay's job-openings enrichment, which runs only on Tier 2 candidates.

## Rules the code enforces

- **Parent first.** `config/parents.csv` maps each hiring entity to its parent (Johns Manville to Berkshire Hathaway, Guardian to Koch, WK Kellogg Co to Ferrero). Parent comes from the hiring company, not the brand: Coca-Cola Consolidated is its own public company.
- **Strict trigger titles.** Reliability engineer, reliability manager, maintenance planner, condition monitoring, vibration analyst. Software SRE, product, quality, test and hardware reliability roles are excluded, and so are maintenance techs, who are always hiring. See `pipeline/filters.py` and `tests/test_filters.py`.
- **Named plant, 60 days.** A posting counts only with a city and state and a posted date inside the window.
- **Verified on the employer board.** Job-site rows are not trusted until the employer's own page confirms them.
- **Revenue, headcount and generic intent are never read.**

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add FIRECRAWL_API_KEY and SEC_USER_AGENT
python -m unittest discover tests   # offline, no credits
```

## Run order

Every script that spends credits is a **dry run by default**. It prints each planned call and the credit estimate. Add `--run` to spend. A ledger in `out/credit_ledger.jsonl` enforces `FIRECRAWL_CREDIT_CAP` across all runs.

Pick one fixed as-of date for the whole run (the day you run step 2) and use it everywhere, including the Clay formula. Every trigger is labeled "as of" that date, and each one gets the date it ages out of the 60-day window.

```bash
AS_OF=2026-11-19   # example: set to the day you run step 2

# 1. Plant counts: two one-row tests first, then the rest
python scripts/01_plant_counts.py                                     # dry run
python scripts/01_plant_counts.py --run --only "Graphic Packaging"    # short 10-K
python scripts/01_plant_counts.py --run --only "PepsiCo"              # long 10-K
#    Check out/plant_counts.csv: the quote must support the count (see quote_check)
python scripts/01_plant_counts.py --run --resume                      # the rest; skips rows already ok

# 2. Triggers: seed postings first
python scripts/02_triggers.py --as-of $AS_OF                          # dry run
python scripts/02_triggers.py --run --limit 1 --as-of $AS_OF
python scripts/02_triggers.py --run --as-of $AS_OF
#    Optional, last, only if credits allow: customer board searches
python scripts/02_triggers.py --run --boards --as-of $AS_OF

# 3. Merge (free)
python scripts/03_merge.py
```

Then import `out/clay_import.csv` into Clay and follow `clay/CLAY_SETUP.md`.

**Timing:** seed triggers age out on their own. With the Stage 2 postings, LSB Industries ages out Nov 24, GAF Nov 27 and 3M Nov 28. `out/run_report.md` lists the first three to expire.

## Failure handling

One bad call never stops a run. A failed Firecrawl request or EDGAR lookup is logged to `out/credit_ledger.jsonl` (with the error), printed, and the row is marked so `run_report.md` lists it as a gap. Only hitting the credit cap stops a run.

`01_plant_counts.py` writes a `quote_check` for every count. "CHECK" means the quote does not state the number (often because the count was read off a list). Check those rows against the filing before they ship.

## Plant-count sources

`plant_count_source` in `config/parents.csv` is one of:
- `10-K`: latest 10-K found on EDGAR, Item 2 "Properties"
- `annual_report`: a non-US annual report at `filing_url`
- `company_page`: a company locations, directory or operations page at `filing_url` (the prompt says "this page")
- `estimate`: a private company's own public statement, copied from `plant_count_manual`, no call
- `none`: not pulled

PDFs cost credits per page. A PDF row needs a page cap, from the row's `pdf_max_pages` column or `--pdf-max-pages N`.

## Clay formula sync

The Clay strict-title formula in `clay/CLAY_SETUP.md` uses regexes generated from `pipeline/filters.py`. After any change to `filters.py`, run `python scripts/print_clay_regex.py` and paste the output into the formula. The offline tests fail if the two drift apart.

## Config notes before a full run

Search `config/parents.csv` for `VERIFY`:
- Canfor and Indorama company-page URLs (check the first scrape reads the right page).
- `careers_url` (only for the optional board searches): Colgate, Molson Coors and Canfor are pattern guesses. KDP, Coca-Cola Consolidated, Atlas and PepsiCo have none, so the board step skips them.
