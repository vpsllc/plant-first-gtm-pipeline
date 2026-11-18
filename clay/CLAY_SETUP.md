# Clay setup: the Tier 2 candidate enrichment

The Clay moment is one enrichment that runs only on Tier 2 candidate rows, plus a visible formula that applies the same strict trigger rules as `pipeline/filters.py`. A row is promoted only when the formula finds a qualifying posting.

## 1. Pre-check (done Nov 18, free searches, not proof)

| Candidate | What free searches showed | Expectation |
|---|---|---|
| International Paper | Mill reliability engineer postings at several US mills; dates not confirmed | Likely promotes |
| Owens Corning | Plant reliability engineer postings at several US plants; dates not confirmed | Likely promotes |
| Kimberly-Clark | Older Reliability Manager listing; a technician role (excluded) | Uncertain |
| General Mills | Maintenance & Reliability Manager roles that look older than 60 days | Uncertain |
| Louisiana-Pacific | Latest plant reliability posting started Feb 2026; another closed | Likely stays out on trigger |
| Hershey | "Reliability Lead" titles (not on the strict list), latest Aug 30, 2026 | Likely stays out on trigger |

The two "stays out" rows are useful: they show the formula rejecting a near-miss title and a stale posting. Rows that come back empty become Excluded with the reason "no plant-level reliability trigger in 60 days."

## 2. Enrichment column (conditional run)

- Enrichment: Clay's job openings enrichment (company job openings), keyed on the company domain.
- Run condition ("Only run if"): `{{row_group}} == "clay_candidate"`
- Do not use auto-run on the whole table. Credits only go to the 6 candidate rows.

## 3. Strict-title formula column: `Qualifying trigger`

**Keep this in sync with `pipeline/filters.py`.** The two regexes below are generated from the INCLUDE and EXCLUDE lists in `filters.py`, every `\b` word boundary included, by `python scripts/print_clay_regex.py`. The offline tests fail if this file and `filters.py` drift apart. Never hand-edit the patterns here: change `filters.py`, regenerate, paste. Without the word boundaries, "mechanic" would block "Mechanical," "product" would block "Production," "build" would block "Building" and "intern" would block "International," and the Clay demo would contradict the scripts on the same title.

Set `AS_OF` to the same fixed date passed to `02_triggers.py --as-of` (the Stage 4 run date).

The field names inside the job openings output (`title`, `location`, `posted_date`) are placeholders until the one-row test shows the real keys. Rename them to match before running on all six rows.

```javascript
(() => {
  const AS_OF = new Date("YYYY-MM-DD");
  const jobs = Array.isArray({{Job Openings}}) ? {{Job Openings}} : [];
  // BEGIN generated from pipeline/filters.py (python scripts/print_clay_regex.py)
  const include = /\breliability\s+engineer|\bengineer\W+(?:mechanical\s+)?reliability\b|\breliability\s+(?:engineering\s+)?manager|\bmaintenance\s+(?:&\s+reliability\s+)?planner|\bcondition\s+monitoring\s+(?:analyst|engineer|specialist)|\bvibration\s+analyst/i;
  const exclude = /\bsite\s+reliability|\bsre\b|\bsoftware\b|\bdevops\b|\bcloud\b|\bobservability\b|\bquality\b|\bproduct\b|\bbuild\b|\bhardware\b|\btest\b|\bsystems?\s+safety\b|\bdata\s+center\b|\bmaintenance\s+tech|\btechnician\b|\bmechanic\b|\belectrician\b|\bintern\b|\bco-?op\b/i;
  // END generated
  const namedPlant = /[A-Za-z .'-]+,\s*[A-Za-z]{2,}/;
  const hit = jobs.find(j => {
    const title = j.title || "";
    const posted = new Date(j.posted_date || "");
    const age = (AS_OF - posted) / 86400000;
    return include.test(title) && !exclude.test(title) && namedPlant.test(j.location || "")
      && age >= 0 && age <= 60;
  });
  return hit ? `${hit.title} | ${hit.location} | ${hit.posted_date}` : "";
})()
```

If Clay's formula editor rejects the multi-line function, paste the two generated regexes unchanged into Clay's formula generator with this instruction: "Return the first job whose title matches INCLUDE and not EXCLUDE, whose location is a city and state, and whose posted date is 0 to 60 days before AS_OF, formatted title | location | date; otherwise empty." Then check that the generated formula still contains both regexes character for character.

Add a second formula, `Trigger reason`, so the table explains each candidate in plain English:

```javascript
{{Qualifying trigger}} ? "Promoted: plant-level reliability hire in the last 60 days" : "No plant-level reliability trigger in 60 days"
```

## 4. One-row test (before the other five)

1. Run the enrichment on the **Owens Corning** row only.
2. Record the credits charged in the execution log.
3. Open the raw output, confirm the real field names, and fix them in the formula.
4. Confirm `Qualifying trigger` either shows a posting that passes the rules or stays empty, and spot-check one posting against Owens Corning's careers site.
5. Only then run the remaining five candidate rows.
