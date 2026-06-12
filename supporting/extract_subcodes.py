#!/usr/bin/env python3
"""
PORTABLE Step 4 — extract level-2 sub-code expenditure from the 16 Pakistan ABS
PDFs and write ../subcodes_wide.csv (the pilot's main deliverable).

Self-contained: run from anywhere; all paths are resolved relative to THIS file.

  supporting/
    extract_subcodes.py            <- this script
    function_schema_level2.csv     <- 69 level-2 codes (ordered output rows)
    top_level_functions.csv        <- ABS-anchored level-1 values (Rule-5 check)
    budget_docs/<fy>/abs_fy_<fy>.pdf
  subcodes_wide.csv                <- written to the PARENT (root) folder

Amendments vs. a naive extractor (see ../prompt.md for the full rationale):
  Rules 1&2  Strict table boundaries: once the 4th expenditure table
             (Development Expenditure on Capital Account) has been read, a
             STOP-header on any following page terminates extraction so
             Schedule-I demand numbers / Schedule-III object heads / object-wise
             CAPITAL EXPENDITURE never bleed into a function table.
  Rule 3     Function 10 in dev_capital is read ONLY from the genuine table
             (it is absent in all 16 years -> recorded 0), never from Schedule-I.
  Rule 4     Absent (year, table) cells are written 0, never blank/null.
  Rule 5     Sub-codes are rolled up by parent and reconciled vs the level-1 set.

Output: 69 rows x 199 cols (7 schema + 16 years x 4 tables x 3 estimates).
Column naming: {fy}_{cur_rev|cur_cap|dev_rev|dev_cap}_{BE_prior|RE_prior|BE_current}
"""

import os, re, csv, pdfplumber
from collections import defaultdict

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
PDF_DIR    = os.path.join(BASE_DIR, "budget_docs")
SCHEMA_CSV = os.path.join(BASE_DIR, "function_schema_level2.csv")
TOPLVL_CSV = os.path.join(BASE_DIR, "top_level_functions.csv")
OUTPUT_CSV = os.path.abspath(os.path.join(BASE_DIR, "..", "subcodes_wide.csv"))

FISCAL_YEARS = [
    "2010-11", "2011-12", "2012-13", "2013-14", "2014-15",
    "2015-16", "2016-17", "2017-18", "2018-19", "2019-20",
    "2020-21", "2021-22", "2022-23", "2023-24", "2024-25", "2025-26",
]

TABLES = ["current_revenue", "current_capital", "dev_revenue", "dev_capital"]
TABLE_SHORT = {
    "current_revenue": "cur_rev", "current_capital": "cur_cap",
    "dev_revenue": "dev_rev", "dev_capital": "dev_cap",
}
ESTIMATES = ["BE_prior", "RE_prior", "BE_current"]

SECTION_HEADERS = {
    "current_revenue": ["Current Expenditure on Revenue Account", "Current Revenue Expenditure"],
    "current_capital": ["Current Expenditure on Capital Account", "Current Capital Expenditure"],
    "dev_revenue":     ["Development Expenditure on Revenue Account", "Development Revenue Expenditure"],
    "dev_capital":     ["Development Expenditure on Capital Account", "Development Capital Expenditure"],
}

# Headers that mark NON-functional material printed after the 4 tables. Once the
# last table (dev_capital) is seen, any of these terminates extraction.
# "capital expenditure" matches only the standalone object-wise page; the real
# tables read "...Expenditure on Capital Account" (words not adjacent).
STOP_HEADERS = [
    "capital expenditure", "public account expenditure", "schedule",
    "object classification", "demand-wise", "demand budget estimates",
    "statement of estimated",
]

TOP_CODE_RE = re.compile(r"^(0[1-9]|10)$")
SUB_CODE_RE = re.compile(r"^((0[1-9]|10)\d|A(0[1-9]|1[0-3]))$")
NUM_RE      = re.compile(r"^[\d,.\-]+$")
ROUNDING_TOLERANCE = 1.0


def prior_fy(fy):
    s, e = fy.split("-")
    return f"{int(s)-1}-{int(e)-1:02d}"


def top_norm_text(page, frac=0.35):
    ws = page.extract_words()
    top = [w for w in ws if w["top"] < page.height * frac]
    return " ".join(" ".join(w["text"] for w in top).split()).lower()


def detect_section_top(page):
    norm = top_norm_text(page)
    for key, labels in SECTION_HEADERS.items():
        for label in labels:
            if label.lower() in norm:
                return key
    return None


def matches_stop(page):
    norm = top_norm_text(page)
    return any(s in norm for s in STOP_HEADERS)


def page_word_rows(page):
    ws = page.extract_words(keep_blank_chars=False)
    rm = defaultdict(list)
    for w in ws:
        rm[round(w["top"] / 5) * 5].append(w)
    return [(y, sorted(rm[y], key=lambda w: w["x0"])) for y in sorted(rm)]


def _cluster_3(xs):
    uniq = sorted(set(xs))
    if len(uniq) < 3:
        return None, None
    gaps = sorted(((uniq[i+1]-uniq[i], i) for i in range(len(uniq)-1)), reverse=True)
    splits = sorted([gaps[0][1], gaps[1][1]])
    g1 = [x for x in uniq if x <= uniq[splits[0]]]
    g2 = [x for x in uniq if uniq[splits[0]] < x <= uniq[splits[1]]]
    g3 = [x for x in uniq if x > uniq[splits[1]]]
    if not (g1 and g2 and g3):
        return None, None
    c1, c2, c3 = sum(g1)/len(g1), sum(g2)/len(g2), sum(g3)/len(g3)
    return (c1+c2)/2, (c2+c3)/2


def find_col_boundaries(page):
    all_x = []
    for _y, row in page_word_rows(page):
        if not row or not TOP_CODE_RE.match(row[0]["text"]):
            continue
        for w in row[1:]:
            if NUM_RE.match(w["text"]) and "," in w["text"]:
                all_x.append(w["x0"])
    if len(all_x) >= 6:
        return _cluster_3(all_x)
    ws = page.extract_words()
    est = [w for w in ws if w["text"].lower() == "estimates" and w["x0"] > page.width * 0.45]
    if len(est) >= 3:
        centers = sorted((w["x0"]+w["x1"])/2 for w in est)
        ded = [centers[0]]
        for c in centers[1:]:
            if c - ded[-1] > 20:
                ded.append(c)
        if len(ded) >= 3:
            c = ded[-3:]
            return (c[0]+c[1])/2, (c[1]+c[2])/2
    return None, None


def clean_num(frags):
    joined = "".join(str(f) for f in frags).replace(",", "").replace(" ", "")
    if not joined or joined == "-":
        return 0.0
    try:
        return float(joined)
    except ValueError:
        return 0.0


def extract_subcode_rows(page, b1, b2):
    if b1 is None:
        return {}
    results = {}
    rows = page_word_rows(page)
    for i, (_y, row) in enumerate(rows):
        if not row:
            continue
        first = row[0]["text"]
        if SUB_CODE_RE.match(first):
            code = first
        elif len(first) >= 4 and SUB_CODE_RE.match(first[:3]):
            code = first[:3]                      # concatenated token "011Executive"
        else:
            continue
        numeric_words = [w for w in row[1:] if NUM_RE.match(w["text"])]
        if not numeric_words:                     # wrapped description -> look ahead
            for j in range(i+1, min(i+3, len(rows))):
                _yn, nrow = rows[j]
                if not nrow:
                    continue
                if TOP_CODE_RE.match(nrow[0]["text"]) or SUB_CODE_RE.match(nrow[0]["text"]):
                    break
                cont = [w for w in nrow if NUM_RE.match(w["text"])]
                if cont:
                    numeric_words = cont
                    break
        cols = {0: [], 1: [], 2: []}
        for w in numeric_words:
            x = w["x0"]
            cols[0 if x < b1 else 1 if x < b2 else 2].append(w["text"])
        vals = [clean_num(cols[0]), clean_num(cols[1]), clean_num(cols[2])]
        if any(v != 0.0 for v in vals):
            results[code] = vals
    return results


def process_pdf(fy, pdf_path):
    section_data = {t: {} for t in TABLES}
    section_bounds = {}
    current_section = None
    seen_devcap = False
    stopped = False
    log = []
    with pdfplumber.open(pdf_path) as pdf:
        for pnum, page in enumerate(pdf.pages, 1):
            if stopped:
                break
            detected = detect_section_top(page)
            if detected:
                b1c, b2c = find_col_boundaries(page)
                if b1c is not None:
                    current_section = detected
                    section_bounds[detected] = (b1c, b2c)
                    if detected == "dev_capital":
                        seen_devcap = True
            elif seen_devcap and matches_stop(page):
                log.append(f"    p{pnum}: STOP — left the 4 tables (post-dev_capital)")
                stopped = True
                break
            if not current_section:
                continue
            b1, b2 = section_bounds.get(current_section, (None, None))
            for code, vals in extract_subcode_rows(page, b1, b2).items():
                if code not in section_data[current_section]:   # first-in-table wins
                    section_data[current_section][code] = vals
    return section_data, log


def load_toplevel():
    if not os.path.exists(TOPLVL_CSV):
        return None
    data = {}
    with open(TOPLVL_CSV, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            data[(r["fiscal_year"], r["reference_year"], r["estimate_type"],
                  r["expenditure_table"], r["function_code"])] = float(r["value_rs_million"])
    return data


def phase_keyparts(fy, phase):
    if phase == "BE_current":
        return fy, "BE"
    if phase == "RE_prior":
        return prior_fy(fy), "RE"
    return prior_fy(fy), "BE"


def reconcile(data_store, schema, toplvl):
    parent_of = {row["code"]: row["parent_code"] for row in schema}
    exact = rounding = artifact = 0
    mismatches = []
    for fy in FISCAL_YEARS:
        for table in TABLES:
            for phase in ESTIMATES:
                ry, et = phase_keyparts(fy, phase)
                idx = ESTIMATES.index(phase)
                sums = defaultdict(float)
                for code, parent in parent_of.items():
                    vals = data_store.get((fy, table, code))
                    if vals:
                        sums[parent] += vals[idx]
                for parent, s in sums.items():
                    key = (fy, ry, et, table, parent)
                    if key not in toplvl:
                        continue
                    diff = abs(s - toplvl[key])
                    if diff == 0:
                        exact += 1
                    elif diff <= ROUNDING_TOLERANCE:
                        rounding += 1
                    elif table == "current_capital" and parent == "01":
                        artifact += 1          # level-1 lumps debt repayment onto fn01
                    else:
                        mismatches.append((diff, fy, ry, et, table, parent, s, toplvl[key]))
    mismatches.sort(reverse=True)
    return {"exact": exact, "rounding": rounding, "artifact": artifact, "mismatches": mismatches}


def main():
    with open(SCHEMA_CSV, encoding="utf-8-sig") as f:
        schema = list(csv.DictReader(f))
    schema_cols = list(schema[0].keys())

    data = {}
    print("=" * 64)
    print("PORTABLE Sub-code Extractor — Pakistan ABS 2010-11 to 2025-26")
    print("=" * 64)
    for fy in FISCAL_YEARS:
        pdf_path = os.path.join(PDF_DIR, fy, f"abs_fy_{fy}.pdf")
        if not os.path.exists(pdf_path):
            print(f"  {fy}: MISSING — skipping")
            continue
        section_data, log = process_pdf(fy, pdf_path)
        c = {t: len(section_data[t]) for t in TABLES}
        print(f"  {fy}  cur_rev={c['current_revenue']:2d}  cur_cap={c['current_capital']:2d}  "
              f"dev_rev={c['dev_revenue']:2d}  dev_cap={c['dev_capital']:2d}")
        for line in log:
            print(line)
        for table, code_map in section_data.items():
            for code, vals in code_map.items():
                data[(fy, table, code)] = vals

    value_cols = [f"{fy}_{TABLE_SHORT[t]}_{e}"
                  for fy in FISCAL_YEARS for t in TABLES for e in ESTIMATES]
    fieldnames = schema_cols + value_cols
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in schema:
            out = {k: row[k] for k in schema_cols}
            for fy in FISCAL_YEARS:
                for table in TABLES:
                    ts = TABLE_SHORT[table]
                    vals = data.get((fy, table, row["code"]), [0.0, 0.0, 0.0])
                    for est, v in zip(ESTIMATES, vals):       # Rule 4: 0 not blank
                        out[f"{fy}_{ts}_{est}"] = int(v) if v == int(v) else v
            writer.writerow(out)
    print(f"\nWrote {len(schema)} rows x {len(fieldnames)} cols -> {OUTPUT_CSV}")

    toplvl = load_toplevel()
    if toplvl is None:
        print("\n[Rule 5] top_level_functions.csv not found — skipping reconciliation.")
        return
    rec = reconcile(data, schema, toplvl)
    tot = rec["exact"] + rec["rounding"] + rec["artifact"] + len(rec["mismatches"])
    ok = rec["exact"] + rec["rounding"] + rec["artifact"]
    print("\n" + "=" * 64)
    print("[Rule 5] HIERARCHY RECONCILIATION vs top_level_functions.csv")
    print("-" * 64)
    print(f"  {rec['exact']} exact, {rec['rounding']} rounding, {rec['artifact']} known-artifact, "
          f"{len(rec['mismatches'])} MISMATCH ({100*ok/tot:.1f}% reconcile)")
    bt = defaultdict(int)
    for m in rec["mismatches"]:
        bt[m[4]] += 1
    if bt:
        print("  mismatches by table:", ", ".join(f"{k}={v}" for k, v in sorted(bt.items())))
    for diff, fy, ry, et, table, parent, s, t in rec["mismatches"][:12]:
        print(f"    {fy} {ry} {et} {table} fn{parent}: subcodes={s:,.0f} level1={t:,.0f} (off {diff:,.0f})")
    if len(rec["mismatches"]) > 12:
        print(f"    ... and {len(rec['mismatches'])-12} more")
    print("=" * 64)


if __name__ == "__main__":
    main()
