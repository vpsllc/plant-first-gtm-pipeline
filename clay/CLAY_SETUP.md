# Clay setup: the Tier 2 candidate enrichment

The Clay moment is one enrichment that runs only on Tier 2 candidate rows, plus a visible formula that applies the same strict trigger rules as `pipeline/filters.py`. A row is promoted only when the formula finds a qualifying posting.

## 1. Results (run Nov 19, 2026; 6 Clay credits)

| Candidate | Clay found | Employer site | Result |
|---|---|---|---|
| Owens Corning | Reliability Engineer, Fort Smith, AR | Open (req 70296) | Promoted |
| International Paper | Mechanical Maintenance Planner, Cayuga, IN | Open (req 2004955, posted Nov 18) | Promoted |
| Louisiana-Pacific | Maintenance Planner, Thomasville, AL | Open (Req Id 12881, posted Nov 10) | Promoted |
| Hershey | Analyst Maintenance Planner, Hershey, PA | Employer page says the posting is no longer active | Not promoted |
| General Mills | Maintenance Planner, Cedar Rapids, IA | Not confirmed on the employer site | Not promoted |
| Kimberly-Clark | Only an Electrical Reliability Technician (excluded title) | n/a | No trigger |

Rejected on title or location in the same run: Hershey's "Reliability Lead" postings (not on the strict list) and a Louisiana-Pacific corporate role with no named plant.

## 2. Enrichment column (conditional run)

- Enrichment: Clay's job openings enrichment (company job openings), keyed on the company domain.
- Run condition ("Only run if"): `{{row_group}} == "clay_candidate"`
- Do not use auto-run on the whole table. Credits only go to the 6 candidate rows.

## 3. Strict-title formula column: `Qualifying trigger`

**Keep this in sync with `pipeline/filters.py`.** The two regexes below are generated from the INCLUDE and EXCLUDE lists in `filters.py`, every `\b` word boundary included, by `python scripts/print_clay_regex.py`. The offline tests fail if this file and `filters.py` drift apart. Never hand-edit the patterns here: change `filters.py`, regenerate, paste. Without the word boundaries, "mechanic" would block "Mechanical," "product" would block "Production," "build" would block "Building" and "intern" would block "International," and the Clay demo would contradict the scripts on the same title.

Set `AS_OF` to the same fixed date passed to `02_triggers.py --as-of` (the run date, 2026-11-19).

Generated regexes (the reference the tests check):

```javascript
// BEGIN generated from pipeline/filters.py (python scripts/print_clay_regex.py)
const include = /\breliability\s+engineer|\bengineer\W+(?:mechanical\s+)?reliability\b|\breliability\s+(?:engineering\s+)?manager|\bmaintenance\s+(?:&\s+reliability\s+)?planner|\bcondition\s+monitoring\s+(?:analyst|engineer|specialist)|\bvibration\s+analyst/i;
const exclude = /\bsite\s+reliability|\bsre\b|\bsoftware\b|\bdevops\b|\bcloud\b|\bobservability\b|\bquality\b|\bproduct\b|\bbuild\b|\bhardware\b|\btest\b|\bsystems?\s+safety\b|\bdata\s+center\b|\bmaintenance\s+tech|\btechnician\b|\bmechanic\b|\belectrician\b|\bintern\b|\bco-?op\b/i;
// END generated
```

Clay's formula column accepts only a single expression (no `const` or `return` statements), so the deployed formula passes the same two regexes in as arguments. The one-row test on Owens Corning (Nov 19) confirmed the enrichment's real output keys: `jobs[]` with `title`, `location` and `posted_at` (ISO date-time), plus `jobCount`.

Deployed `Qualifying trigger` formula (paste as is; Clay shows the column name as a token):

```javascript
((jobs, include, exclude, namedPlant, asof) => ((hit) => hit ? hit.title + " | " + hit.location + " | " + (hit.posted_at || "").slice(0, 10) : "")(jobs.find(j => include.test(j.title || "") && !exclude.test(j.title || "") && namedPlant.test(j.location || "") && (asof - new Date((j.posted_at || "").slice(0, 10))) / 86400000 >= 0 && (asof - new Date((j.posted_at || "").slice(0, 10))) / 86400000 <= 60)))(Array.isArray({{Job openings (Clay)}}?.jobs) ? {{Job openings (Clay)}}.jobs : [], /\breliability\s+engineer|\bengineer\W+(?:mechanical\s+)?reliability\b|\breliability\s+(?:engineering\s+)?manager|\bmaintenance\s+(?:&\s+reliability\s+)?planner|\bcondition\s+monitoring\s+(?:analyst|engineer|specialist)|\bvibration\s+analyst/i, /\bsite\s+reliability|\bsre\b|\bsoftware\b|\bdevops\b|\bcloud\b|\bobservability\b|\bquality\b|\bproduct\b|\bbuild\b|\bhardware\b|\btest\b|\bsystems?\s+safety\b|\bdata\s+center\b|\bmaintenance\s+tech|\btechnician\b|\bmechanic\b|\belectrician\b|\bintern\b|\bco-?op\b/i, /[A-Za-z .'-]+,\s*[A-Za-z]{2,}/, new Date("2026-11-19"))
```

Add a second formula, `Trigger reason`, so the table explains each candidate in plain English (blank on non-candidate rows and before the enrichment runs):

```javascript
{{List group (code)}} !== "clay_candidate" ? "" : ({{Qualifying trigger}} && String({{Verified on employer site}}).toLowerCase() === "true" ? "Promoted: plant-level reliability hire in the last 60 days, confirmed on employer site" : ({{Qualifying trigger}} ? "Clay found a posting; not confirmed on employer site." : ({{Job openings (Clay)}} ? "No plant-level reliability trigger in 60 days" : "")))
```

## 4. One-row test (before the other five)

1. Run the enrichment on the **Owens Corning** row only.
2. Record the credits charged in the execution log.
3. Open the raw output, confirm the real field names, and fix them in the formula.
4. Confirm `Qualifying trigger` either shows a posting that passes the rules or stays empty, and spot-check one posting against Owens Corning's careers site.
5. Only then run the remaining five candidate rows.

## 5. Promotion, ranking and play (live formula columns)

A Clay candidate is promoted only when the Clay enrichment finds a qualifying posting AND the posting is confirmed on the employer's own site (`Verified on employer site` = True, entered after a hand check). A Clay posting that isn't confirmed stays "Tier 2 candidate (not promoted)" with the reason "Clay found a posting; not confirmed on employer site."

Priority score: Tier 1 = 2000 + plants (US if stated, else total; "not stated" ranks last). Tier 2 = 1000 + 300 x title weight (reliability engineer or manager = 2, planner = 1) + plants (capped at 299). Everything else 0. Saved views sort by it.

`Tier`:

```javascript
{{List group (code)}} === "customer" ? "Tier 1" : ({{List group (code)}} === "prospect" ? "Tier 2" : ({{List group (code)}} === "clay_candidate" ? ({{Qualifying trigger}} && String({{Verified on employer site}}).toLowerCase() === "true" ? "Tier 2 (promoted by Clay)" : ({{Qualifying trigger}} ? "Tier 2 candidate (not promoted)" : ({{Job openings (Clay)}} ? "Excluded" : "Tier 2 candidate"))) : "Excluded"))
```

`Tier reason`:

```javascript
{{List group (code)}} === "customer" ? ({{Augury status (code)}} === "customer_site" ? "Augury customer with a confirmed live site: expand to the rest of the plants" : "Augury customer, live site not confirmed: expand once the AE confirms it") : ({{List group (code)}} === "prospect" ? "Plant-level reliability hire in the last 60 days, confirmed on employer site" : ({{List group (code)}} === "clay_candidate" ? ({{Qualifying trigger}} && String({{Verified on employer site}}).toLowerCase() === "true" ? "Promoted: plant-level reliability hire in the last 60 days, confirmed on employer site" : ({{Qualifying trigger}} ? "Clay found a posting; not confirmed on employer site." : ({{Job openings (Clay)}} ? "No plant-level reliability trigger in 60 days" : "Waiting on the Clay enrichment"))) : ((s) => s.charAt(0).toUpperCase() + s.slice(1))(String({{Notes}} || "").replace(/^Excluded reason: /, ""))))
```

`Priority score`:

```javascript
{{List group (code)}} === "customer" ? 2000 + Math.min((Number({{US plants}}) || Number({{Plants (total)}}) || 0), 999) : ({{List group (code)}} === "prospect" || ({{List group (code)}} === "clay_candidate" && {{Qualifying trigger}} && String({{Verified on employer site}}).toLowerCase() === "true") ? 1000 + 300 * (/\breliability\s+(?:engineering\s+)?(?:engineer|manager)|\bengineer\W+(?:mechanical\s+)?reliability\b/i.test(String({{Trigger role}} || "")) ? 2 : 1) + Math.min((Number({{US plants}}) || Number({{Plants (total)}}) || 0), 299) : 0)
```

`Play`:

```javascript
{{List group (code)}} === "customer" ? (({{Augury status (code)}} === "customer_site_not_named" || {{Augury status (code)}} === "customer_site_unconfirmed") ? "Expansion, live site unconfirmed: the AE confirms the live site first" : "Expansion: the AE brings the live plant's results first") : (({{List group (code)}} === "prospect" || ({{List group (code)}} === "clay_candidate" && {{Qualifying trigger}} && String({{Verified on employer site}}).toLowerCase() === "true")) ? "New logo: start at the plant with the open reliability role" : "")
```

`First contact role`:

```javascript
{{List group (code)}} === "customer" ? (({{Augury status (code)}} === "customer_site_not_named" || {{Augury status (code)}} === "customer_site_unconfirmed") ? "AE confirms the live site, then the SDR goes to the regional ops or manufacturing leader" : "Regional ops or manufacturing leader, after the AE shares the live plant's results") : (({{List group (code)}} === "prospect" || ({{List group (code)}} === "clay_candidate" && {{Qualifying trigger}} && String({{Verified on employer site}}).toLowerCase() === "true")) ? "Plant maintenance or reliability lead at " + ({{Trigger plant}} || "the trigger plant") + " (not IT or procurement)" : "")
```

`60-day check`:

```javascript
{{List group (code)}} === "customer" ? "Customer expansion signal: review at about 100 contacts; cut it under 1% positive replies. Baseline: old $1B list, near zero." : (({{List group (code)}} === "prospect" || ({{List group (code)}} === "clay_candidate" && {{Qualifying trigger}} && String({{Verified on employer site}}).toLowerCase() === "true")) ? "Reliability-hire signal: review at about 100 contacts; cut it under 1% positive replies. Baseline: old $1B list, near zero." : "")
```

## 6. Saved views

- **SDR working list:** Play is not empty, sorted by Priority score (high to low).
- **Expansion plays:** Play contains "Expansion", same sort.
- **Excluded and why:** Play is empty; Tier reason says why.
