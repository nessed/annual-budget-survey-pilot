# Portable Budget Extraction Pilot — Reproduction Prompt

You are an autonomous coding agent. Your job is to **extract level-2 (sub-code)
functional expenditure data from Pakistan's Annual Budget Statement (ABS) PDFs
and produce `subcodes_wide.csv`** — exactly reproducing the file shipped in the
root of this folder. Follow the steps below precisely. Everything you need is in
the `supporting/` folder; you can run the whole thing offline.

---

## 0. What this is and why it's hard

The ABS is Pakistan's federal budget document, published yearly. Each year's PDF
contains **four functional-expenditure tables**, always in this order:

1. **Current Expenditure on Revenue Account**  → `current_revenue` (`cur_rev`)
2. **Current Expenditure on Capital Account**  → `current_capital` (`cur_cap`)
3. **Development Expenditure on Revenue Account** → `dev_revenue` (`dev_rev`)
4. **Development Expenditure on Capital Account** → `dev_capital` (`dev_cap`)

Each table lists expenditure by a **functional classification**:

- 10 top-level **function codes** `01`–`10` (01 General Public Services …
  10 Social Protection).
- Under each, 3-digit **sub-codes** (`011`, `014`, `041` …) — and, only under
  `02 Defence`, object heads `A01`–`A13`. These 69 level-2 codes are the rows of
  the output. The canonical list is `supporting/function_schema_level2.csv`.

Each table prints **three money columns** (Rs million), in this fixed order:

| Column | Meaning |
|---|---|
| `BE_prior` | Budget Estimate of the **prior** year |
| `RE_prior` | Revised Estimate of the **prior** year |
| `BE_current` | Budget Estimate of the **current** (title) year |

**Why it's hard / the trap that ruined the first attempt:** after the 4th table,
every ABS continues with non-functional material that *looks* like the same
table — object-wise **"CAPITAL EXPENDITURE"** (public-debt repayment), **PUBLIC
ACCOUNT EXPENDITURE**, **SCHEDULE-I (Demand-Wise)**, and **SCHEDULE-III
(Object-Wise)**. A parser that latches onto the last table and keeps reading will
ingest those rows. In particular, **Schedule-I demand numbers 100–109 collide
with real Social-Protection sub-codes 100–109**, and Schedule-III object heads
`A01`–`A13` collide with the Defence object heads. The first version bled **1,160
bogus `dev_cap` cells** this way. **You must stop at the table boundary.**

---

## The 5 rules (obey all of them)

You are extracting function-level expenditure data from Pakistan's ABS. Codes in
other sections superficially resemble function codes but are a separate
classification.

1. **Strict table boundaries.** Function/sub-codes are valid ONLY inside the 4
   named tables above. Never read values from Summary of Expenditure, Schedule-I
   (Demand-Wise), Schedule-III (Object-Wise), the object-wise CAPITAL
   EXPENDITURE page, Public Account, or footnotes.
2. **Demand# ≠ function code.** Schedule-I rows like "10 BOARD OF INVESTMENT" use
   *demand numbers* (1..~136), not function codes. A demand number such as `100`,
   `101`, `107` must NEVER be mapped to sub-code 100/101/107. Never assign a
   Schedule-I value to a function/sub-code.
3. **Function 10 in `dev_capital`.** Function 10 (Social Protection) may or may
   not appear in the Development Expenditure on Capital Account table depending
   on the year. When present, its value is the sum of its in-table sub-codes
   (Frontier Regions, FATA, Maintenance Allowances to Ex-Rulers, Afghan
   Refugees, Administration, Others, Social Protection NEC). When absent, record
   **0** — never substitute a figure from Schedule-I or another table. (In these
   16 ABS years function 10 is in fact **absent from dev_capital in every year**,
   so every fn-10 dev_cap value is 0.)
4. **Zero vs. absent.** If a code does not appear in a given table for a given
   year, record its value as **0** — not null, not blank, and never a value
   carried over from another table or estimate.
5. **Validate by summing.** After extracting each table, the sub-codes must roll
   up (sum by parent function) to the table's function totals. Reconcile against
   the ABS-anchored level-1 figures in `supporting/top_level_functions.csv`. If a
   parent disagrees, re-examine the page for rows misattributed to the wrong
   table or conflated with non-function numbers.

---

## 1. Environment

```bash
python --version            # 3.10+ (developed on 3.14)
python -m pip install -r supporting/requirements.txt   # pdfplumber
```

`pdfplumber` is the only third-party dependency. Everything else is stdlib.

## 2. Inputs (already provided in `supporting/`)

| File | Role |
|---|---|
| `budget_docs/<fy>/abs_fy_<fy>.pdf` | the 16 source ABS PDFs, FY2010-11 … FY2025-26 |
| `function_schema_level2.csv` | the 69 level-2 codes (= output rows, in order) + `parent_code` |
| `function_schema.csv` | full code dimension table (reference) |
| `top_level_functions.csv` | ABS-anchored level-1 values, used for the Rule-5 reconciliation |
| `extract_subcodes.py` | the reference implementation of Step 4 |
| `download_budgets.py`, `build_schema.py` | upstream Steps 1–2 (see below) |

The four target table headers and the post-table STOP headers are:

```
target  = ["Current Expenditure on Revenue Account",  "Current Revenue Expenditure",
           "Current Expenditure on Capital Account",  "Current Capital Expenditure",
           "Development Expenditure on Revenue Account","Development Revenue Expenditure",
           "Development Expenditure on Capital Account","Development Capital Expenditure"]
STOP    = ["capital expenditure", "public account expenditure", "schedule",
           "object classification", "demand-wise", "demand budget estimates",
           "statement of estimated"]
```
Note `"capital expenditure"` matches only the standalone object-wise page; the
real tables read "…Expenditure on **Capital Account**" (the words are not
adjacent), so it does not false-trigger.

## 3. (Optional) Re-deriving the inputs from scratch — Steps 1–2

These are already done; the CSVs/PDFs above are canonical. Re-run only if
starting from nothing:

- **Step 1 — `download_budgets.py`**: downloads each ABS PDF from
  `finance.gov.pk` (per-year URLs, browser User-Agent, `%PDF` magic-byte check,
  ~2.5 s delay). Saves to `budget_docs/<fy>/`.
- **Step 2 — `build_schema.py`**: scans all PDFs to collect every code + its
  canonical name → `function_schema.csv` / `function_schema_level2.csv`. (Top
  level names are fixed; sub-code names = most frequent observed string.)
- **Step 3 — top-level extract** produced `top_level_functions.csv` (10 function
  codes × 4 tables × 3 estimates × 16 years). It is anchored to the ABS summary
  pages and is treated here as the reference for Rule 5.

> Caveat: the provided `function_schema_level2.csv` lists `A01`–`A13` as
> belonging to `dev_capital`. That is an artifact of an earlier schema scan that
> also crossed the table boundary; those rows are harmless because Step 4 writes
> 0 for them in dev_capital. Keep the schema file as-is so the output rows match.

## 4. Step 4 — extract the sub-codes (the deliverable)

Reproduce the algorithm in `supporting/extract_subcodes.py`. For each of the 16
PDFs:

1. **Walk pages in order.** Maintain `current_section` (one of the 4 tables or
   None), a `seen_devcap` flag, and a `stopped` flag.
2. **Detect a table** by testing the top 35 % of the page against the target
   headers. Only switch `current_section` if you can also derive **column
   boundaries** for that page (this guards against the Contents page, which
   names the tables but has no data). When you switch into
   `dev_capital`, set `seen_devcap = True`.
3. **STOP rule (Rules 1 & 2).** If the page is **not** a target header, and
   `seen_devcap` is True, and the top text matches any `STOP` header → set
   `stopped` and break out of the PDF. This is what prevents Schedule /
   object-wise / public-account bleed. Do **not** stop before dev_capital.
4. **Column boundaries.** Infer the 2 x-splits between the 3 money columns by
   clustering the `x0` of **comma-containing** numeric tokens found in
   top-level-code rows (need ≥6; take the 2 largest gaps). Fallback: the centres
   of the three "Estimates" header words in the right 55 % of the page.
5. **Read sub-code rows.** A row "belongs" if its first token matches
   `^((0[1-9]|10)\d|A(0[1-9]|1[0-3]))$`. Handle two PDF quirks:
   - **Concatenated token** (FY2014-15…2020-21): e.g. `011Executive` — the code
     is the first 3 chars.
   - **Wrapped description**: the code is on one line and the numbers on the next
     1–2 lines — look ahead, but stop if a new code begins.
   Bin each numeric token into column 0/1/2 by `x0` vs the two boundaries; join
   fragments, strip commas, parse to a number (blank/`-` → 0).
6. **First occurrence within a table wins** (Rule 4 — never overwrite with, or
   carry over, a value from a later page or another table).

Then write the wide CSV:

- **Rows:** the 69 codes from `function_schema_level2.csv`, in file order, with
  their 7 schema columns (`code, parent_code, level, name, expenditure_tables,
  first_year, last_year`).
- **Value columns:** for each of the 16 years, each of the 4 tables, each of the
  3 estimates → `"{fy}_{cur_rev|cur_cap|dev_rev|dev_cap}_{BE_prior|RE_prior|BE_current}"`
  = 192 columns. **199 columns total.**
- **Every value cell is written as an integer 0 when absent (Rule 4), never
  blank.**
- Write to the **root** `subcodes_wide.csv` (the script writes `../subcodes_wide.csv`).

Run it:

```bash
cd supporting
python extract_subcodes.py
```

## 5. Step 5 — validate (Rule 5) and acceptance criteria

The script finishes by rolling sub-codes up by parent and reconciling against
`top_level_functions.csv`. Your run is correct if you reproduce these:

- **Output shape:** 69 data rows × 199 columns, **0 blank value cells**.
- **Per-year sub-code counts** match (e.g. 2010-11 `cur_rev=48 cur_cap=4
  dev_rev=36 dev_cap=6`; a `STOP` line prints once per year right after
  dev_capital).
- **dev_capital never contains function 10** (all fn-10 dev_cap cells = 0).
- **Rule-5 reconciliation ≈ 91.9 %** (712 exact + 302 rounding + 17
  known-artifact; **91 mismatches**: `current_revenue=24, dev_capital=38,
  dev_revenue=29`).
  - The `current_capital fn01` gaps are a **known artifact** (level-1 lumps
    non-functional debt repayment onto fn01) — excluded from failures.
  - The residual `dev_capital fn01` gaps are a level-1 definitional difference
    (loans/investments not split into functional sub-codes); flag, don't "fix"
    by inventing numbers.

If you instead see ~180 dev_capital mismatches and non-zero fn-10 dev_cap values,
you have the **bleed bug** — your STOP rule is not firing; revisit step 3.

## 6. Definition of done

- `subcodes_wide.csv` in the root is byte-for-byte reproducible by re-running
  `supporting/extract_subcodes.py`.
- All 5 rules hold; the acceptance numbers above are met.
- No value was hand-edited or sourced from anything other than the 4 named
  tables of the ABS PDFs.

---

## Appendix A — Original instructions, verbatim (as received)

The sections above are a cleaned-up restatement. This is the exact prompt that
defined the task and the failure modes, preserved word-for-word as the source of
truth. (Some lines were truncated in the original message; reproduced as sent.)

> these are the issues i ran into last time, take this prompt and the mistakes
> that were made in the current subcodes wide csv i take it you understand what
> they were now and their nature. You are extracting function-level expenditure
> data from Pakistan's Annual Budget Statement (ABS).
> superficially resemble function codes (01–10) but are a completely separate
> classification. If you see a row in Schedule-I labelled "10 BOARD OF
> INVESTMENT" or any other ministry/division, the 10 is a demand number. Never
> assign its value to function code 10 (Social Protection) or any other function
> code.
> Rule 3 — Function 10 in the dev_capital table. Function 10 (Social Protection)
> may or may not appear explicitly in the Development Expenditure on Capital
> Account table depending on the year. When it does appear, its value must be the
> sum of all subcode rows listed under it within that table (subcodes such as
> Frontier Regions, FATA, Maintenance Allowances to Ex-Rulers, Afghan Refugees,
> Administration, Others, and Social Protection NEC). If function 10 is absent
> from the dev_capital table entirely, record its value as zero — do not
> substitute any figure from another table or context.
> Rule 4 — Zero vs. absent. If a function code does not appear in a given table
> for a given year, record its value as 0, not null or a
> Rule 5 — Validate by summing. After extracting each table, verify that the sum
> of all function-code rows equals the table's stated grand total. If there is a
> discrepancy, re-examine the page for rows you may have misattributed to the
> wrong table or conflated with non-function-code numbers.
> i want u to reproduce the outputs we got from the budget statements subfolder
> in a new subfolder called budget_statements_amended. and execute. and skip step
> 1 cuz we already have budgets here downloaded in the original just copy those
> over and recreate subcodes_wide just executing step 4 the existing top level
> functions and function schema csv already exist just refer to those for that i
> just need you to recreate step 4. execute
