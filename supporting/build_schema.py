#!/usr/bin/env python3
"""
Scan all 16 ABS PDFs to collect every function code + subcode and their names.
Outputs budget_data/function_schema.csv — the master dimension table.
No values; just codes, hierarchy, and canonical names.
"""

import os, re, csv, pdfplumber
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PDF_DIR  = os.path.join(BASE_DIR, "budget_docs")
OUTPUT   = os.path.join(BASE_DIR, "budget_data", "function_schema.csv")

FISCAL_YEARS = [
    "2010-11", "2011-12", "2012-13", "2013-14", "2014-15",
    "2015-16", "2016-17", "2017-18", "2018-19", "2019-20",
    "2020-21", "2021-22", "2022-23", "2023-24", "2024-25", "2025-26",
]

SECTION_HEADERS = {
    "current_revenue": ["Current Expenditure on Revenue Account", "Current Revenue Expenditure"],
    "current_capital": ["Current Expenditure on Capital Account", "Current Capital Expenditure"],
    "dev_revenue":     ["Development Expenditure on Revenue Account", "Development Revenue Expenditure"],
    "dev_capital":     ["Development Expenditure on Capital Account", "Development Capital Expenditure"],
}

# 2-digit top-level: 01–10
TOP_RE  = re.compile(r"^(0[1-9]|10)$")
# 3-digit sub-function: first 2 digits must be a valid top-level code
SUB_RE  = re.compile(r"^(0[1-9]|10)\d$")
# A-codes (object codes) that appear as sub-items within Defence tables
# Restrict to A01–A13 to avoid A10 from the public debt section
A_RE    = re.compile(r"^A(0[1-9]|1[0-3])$")

# Anything that's purely numeric / a bracket-number / punctuation
NUM_RE  = re.compile(r"^[\d,.\-\(\)]+$")

# Words to drop from description text
SKIP    = {"Contd…..", "Contd.....", "Contd….", "Contd", "Contd.",
           "(Rs", "in", "million)", "million", "Rs", "&", "and"}

FIXED_TOP = {
    "01": "General Public Services",
    "02": "Defence Affairs and Services",
    "03": "Public Order and Safety Affairs",
    "04": "Economic Affairs",
    "05": "Environment Protection",
    "06": "Housing and Community Amenities",
    "07": "Health",
    "08": "Recreation, Culture and Religion",
    "09": "Education Affairs and Services",
    "10": "Social Protection",
}


def is_code(text: str) -> bool:
    return bool(TOP_RE.match(text) or SUB_RE.match(text) or A_RE.match(text))


def detect_section_top(page) -> str | None:
    words  = page.extract_words()
    top    = [w for w in words if w["top"] < page.height * 0.35]
    text   = " ".join(w["text"] for w in top)
    norm   = " ".join(text.split()).lower()
    for key, labels in SECTION_HEADERS.items():
        for label in labels:
            if label.lower() in norm:
                return key
    return None


def page_word_rows(page):
    words   = page.extract_words(keep_blank_chars=False)
    row_map = defaultdict(list)
    for w in words:
        row_map[round(w["top"] / 5) * 5].append(w)
    return [(y, sorted(row_map[y], key=lambda w: w["x0"]))
            for y in sorted(row_map)]


# ── scan every PDF ────────────────────────────────────────────────────────────

# code → {names: {name: count}, tables: set[str], years: set[str]}
code_db: dict[str, dict] = {}

for fy in FISCAL_YEARS:
    pdf_path = os.path.join(PDF_DIR, fy, f"abs_fy_{fy}.pdf")
    if not os.path.exists(pdf_path):
        print(f"  MISSING: {pdf_path}")
        continue

    current_section: str | None = None

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            detected = detect_section_top(page)
            if detected:
                current_section = detected
            if not current_section:
                continue

            for _y, row in page_word_rows(page):
                if not row:
                    continue
                first = row[0]["text"]
                if not is_code(first):
                    continue

                # Description = non-numeric words after the code, up to first number
                desc_parts = []
                for w in row[1:]:
                    t = w["text"]
                    if NUM_RE.match(t):
                        break
                    if t not in SKIP:
                        desc_parts.append(t)

                desc = " ".join(desc_parts).strip().rstrip(",").strip()
                if not desc:
                    continue

                if first not in code_db:
                    code_db[first] = {
                        "names":  defaultdict(int),
                        "tables": set(),
                        "years":  set(),
                    }
                code_db[first]["names"][desc] += 1
                code_db[first]["tables"].add(current_section)
                code_db[first]["years"].add(fy)

    print(f"  {fy}: done")

print(f"\nTotal unique codes found: {len(code_db)}")


# ── build sorted master list ──────────────────────────────────────────────────

def parent_of(code: str) -> str:
    if TOP_RE.match(code):
        return ""
    if SUB_RE.match(code):
        return code[:2]
    if A_RE.match(code):
        # A-codes appear under 021 (Military Defence) in the data
        return "021"
    return ""


def level_of(code: str) -> int:
    if TOP_RE.match(code):
        return 1
    return 2


def sort_key(code: str):
    """Sort so top-level codes are followed immediately by their children."""
    if TOP_RE.match(code):
        return (code, "000")
    if SUB_RE.match(code):
        return (code[:2], code)
    if A_RE.match(code):
        # A-codes sort after 021, before 022 etc.
        return ("02", "021" + code)
    return (code, code)


all_codes = sorted(code_db.keys(), key=sort_key)


# ── write CSV ─────────────────────────────────────────────────────────────────

os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)

fieldnames = [
    "code", "parent_code", "level",
    "name",
    "expenditure_tables",
    "first_year", "last_year",
]

with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()

    for code in all_codes:
        info  = code_db[code]
        years = sorted(info["years"])

        # Canonical name: fixed for top-level, most-frequent for subcodes
        if TOP_RE.match(code) and code in FIXED_TOP:
            canonical = FIXED_TOP[code]
        else:
            canonical = max(info["names"].items(), key=lambda x: x[1])[0]

        tables = "; ".join(sorted(info["tables"]))

        writer.writerow({
            "code":               code,
            "parent_code":        parent_of(code),
            "level":              level_of(code),
            "name":               canonical,
            "expenditure_tables": tables,
            "first_year":         years[0],
            "last_year":          years[-1],
        })

print(f"Written → {OUTPUT}")


# ── quick summary ─────────────────────────────────────────────────────────────

print("\nCodes per top-level function:")
for fc in sorted(FIXED_TOP):
    children = [c for c in all_codes if parent_of(c) == fc]
    print(f"  {fc} {FIXED_TOP[fc][:40]:<42} {len(children)} sub-codes: "
          f"{', '.join(children)}")
