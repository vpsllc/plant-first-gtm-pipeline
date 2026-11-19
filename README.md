# Plant-first account selection for a predictive maintenance seller

A predictive maintenance platform sells to large manufacturers. Its wins start at one plant and spread, and a list of every manufacturer over $1B got near-zero replies. This repo builds a better list: it rolls companies up to the parent and ranks them on what predicts a deal, which is plant footprint, a reliability hire posted at a named plant in the last 60 days, and whether the parent is already a customer somewhere. The scripts gather sourced inputs into one CSV; the tiering, ranking and play routing run as live formulas in Clay.

Augury stands in as the seller. Every customer flag comes from a public announcement, with the source URL and date. Built and run from the terminal with Claude Code.

## What it does

| Step | Script | Source | Output |
|---|---|---|---|
| 1 | `scripts/01_plant_counts.py` | SEC EDGAR (free) finds each 10-K and saves its Item 2 "Properties" text as evidence. Final counts are read by hand from that text (or from company pages and statements) and recorded in `config/parents.csv` with their source. Firecrawl only for non-10-K sources. | `out/plant_counts.csv`, `out/item2/*.txt` |
| 2 | `scripts/02_triggers.py` | Firecrawl reads employer job boards. Seed postings are opened on the employer's own site to confirm they are open; board searches cover the rest. | `out/triggers.csv`, `out/triggers_best.csv` |
| 3 | `scripts/03_merge.py` | Joins the parent map, counts and triggers. No tiering here. | `out/clay_import.csv`, `out/run_report.md` |

Tiering, ranking and play routing live in Clay as formulas, so the logic is visible in the table. Rows marked `trigger_source=clay` are left for Clay's job-openings enrichment, which runs only on Tier 2 candidates.

## Results (run of Nov 19, 2026)

27 accounts: 9 Augury customer parents (Tier 1), 11 Tier 2 (8 from the scripts, 3 promoted by Clay’s job-openings enrichment after employer-site checks), 7 excluded or not promoted, each with its reason. Cost: 96 Firecrawl credits and 6 Clay credits.

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

# 1. Plant counts: 10-K rows read Item 2 from EDGAR (free); check two first, then the rest
python scripts/01_plant_counts.py                                     # dry run
python scripts/01_plant_counts.py --run --only "Graphic Packaging"    # free; expect 102 total / 54 US
python scripts/01_plant_counts.py --run --only "PepsiCo"              # free; different Item 2 layout
#    Check out/plant_counts.csv against out/item2/<company>.txt. Any status starting CHECK gets a hand look.
python scripts/01_plant_counts.py --run --resume                      # the rest; only 3 rows use Firecrawl

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

**Timing:** triggers age out on their own, 60 days after each posting date. `out/run_report.md` lists the first three to expire.

## Failure handling

One bad call never stops a run. A failed Firecrawl request or EDGAR lookup is logged to `out/credit_ledger.jsonl` (with the error), printed, and the row is marked so `run_report.md` lists it as a gap. Only hitting the credit cap stops a run.

Every plant-count row has a `status`. For 10-K rows, `method` says how the count was read (location list, summary table, or stated count) and `out/item2/<company>.txt` holds the Item 2 text it came from. A status starting with "CHECK" (a stated count in prose, a list and a table that disagree, or no Item 2 found) gets checked by hand before the row ships. Firecrawl rows also get a `quote_check`.

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
