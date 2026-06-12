#!/usr/bin/env python3
"""
Extract printed function-code rows from the FY2026-27 ABS PDF.

This is intentionally separate from supporting/extract_subcodes.py. It keeps the
same table-boundary rules, but writes a raw printed-row file containing both
level-1 function totals (01..10) and level-2/detail rows (011..109, A01..A13).
"""

from __future__ import annotations

import csv
import importlib.util
import os
import re
import sys
from collections import defaultdict


THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(THIS_DIR, ".."))
SUPPORTING_DIR = os.path.join(ROOT_DIR, "supporting")
FY = "2026-27"
PDF_PATH = os.path.join(SUPPORTING_DIR, "budget_docs", FY, f"abs_{FY}.pdf")
HELPER_PATH = os.path.join(SUPPORTING_DIR, "extract_subcodes.py")
SCHEMA_PATH = os.path.join(SUPPORTING_DIR, "function_schema.csv")
ROWS_OUT = os.path.join(THIS_DIR, f"printed_code_totals_{FY}.csv")
ROLLUP_OUT = os.path.join(THIS_DIR, f"rollup_check_{FY}.csv")


spec = importlib.util.spec_from_file_location("extract_subcodes", HELPER_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Could not load helper module: {HELPER_PATH}")
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


DETAIL_RE = re.compile(r"^((0[1-9]|10)\d|A(0[1-9]|1[0-3]))$")
CODE_RE = re.compile(r"^(0[1-9]|10|((0[1-9]|10)\d)|A(0[1-9]|1[0-3]))$")


def load_schema() -> dict[str, dict[str, str]]:
    with open(SCHEMA_PATH, newline="", encoding="utf-8-sig") as f:
        return {row["code"]: row for row in csv.DictReader(f)}


def parent_of(code: str) -> str:
    if helper.TOP_CODE_RE.match(code):
        return ""
    if DETAIL_RE.match(code) and code.startswith("A"):
        return "021"
    if DETAIL_RE.match(code):
        return code[:2]
    return ""


def level_of(code: str) -> int:
    return 1 if helper.TOP_CODE_RE.match(code) else 2


def row_code(first_token: str) -> tuple[str | None, str]:
    if CODE_RE.match(first_token):
        return first_token, ""
    if len(first_token) >= 4 and DETAIL_RE.match(first_token[:3]):
        return first_token[:3], first_token[3:]
    return None, ""


def row_starts_code(row: list[dict]) -> bool:
    if not row:
        return False
    code, _rest = row_code(row[0]["text"])
    return code is not None


def bin_numeric_words(words: list[dict], b1: float, b2: float) -> dict[int, list[str]]:
    cols = {0: [], 1: [], 2: []}
    for word in words:
        x = word["x0"]
        col = 0 if x < b1 else 1 if x < b2 else 2
        cols[col].append(word["text"])
    return cols


def merge_missing_continuation_cols(
    rows: list[tuple[int, list[dict]]],
    start_index: int,
    cols: dict[int, list[str]],
    b1: float,
    b2: float,
) -> None:
    """Handle PDF rows where one money column is visually pushed down a line."""
    if all(cols[idx] for idx in range(3)):
        return
    for j in range(start_index + 1, min(start_index + 3, len(rows))):
        nrow = rows[j][1]
        if row_starts_code(nrow):
            break
        cont = [word for word in nrow if helper.NUM_RE.match(word["text"])]
        if not cont:
            continue
        cont_cols = bin_numeric_words(cont, b1, b2)
        for idx in range(3):
            if not cols[idx] and cont_cols[idx]:
                cols[idx].extend(cont_cols[idx])
        if all(cols[idx] for idx in range(3)):
            break


def printed_name(row: list[dict], first_remainder: str) -> str:
    parts = []
    if first_remainder:
        parts.append(first_remainder)
    for word in row[1:]:
        text = word["text"]
        if helper.NUM_RE.match(text):
            break
        parts.append(text)
    return " ".join(parts).strip().rstrip(",")


def extract_printed_rows(page, table: str, page_number: int, b1: float, b2: float) -> list[dict]:
    extracted = []
    rows = helper.page_word_rows(page)
    for i, (_y, row) in enumerate(rows):
        if not row:
            continue
        code, first_remainder = row_code(row[0]["text"])
        if code is None:
            continue

        numeric_words = [word for word in row[1:] if helper.NUM_RE.match(word["text"])]
        cols = bin_numeric_words(numeric_words, b1, b2)
        merge_missing_continuation_cols(rows, i, cols, b1, b2)
        values = [helper.clean_num(cols[0]), helper.clean_num(cols[1]), helper.clean_num(cols[2])]
        if not any(value != 0.0 for value in values):
            continue

        extracted.append(
            {
                "fiscal_year": FY,
                "expenditure_table": table,
                "page": page_number,
                "code": code,
                "parent_code": parent_of(code),
                "level": level_of(code),
                "printed_name": printed_name(row, first_remainder),
                "BE_prior": int(values[0]) if values[0] == int(values[0]) else values[0],
                "RE_prior": int(values[1]) if values[1] == int(values[1]) else values[1],
                "BE_current": int(values[2]) if values[2] == int(values[2]) else values[2],
            }
        )
    return extracted


def process_pdf() -> tuple[list[dict], list[str]]:
    printed_rows: list[dict] = []
    row_instances: defaultdict[tuple[str, str], int] = defaultdict(int)
    section_bounds: dict[str, tuple[float, float]] = {}
    current_section = None
    seen_devcap = False
    log: list[str] = []

    with helper.pdfplumber.open(PDF_PATH) as pdf:
        for page_number, page in enumerate(pdf.pages, 1):
            detected = helper.detect_section_top(page)
            if detected:
                b1, b2 = helper.find_col_boundaries(page)
                if b1 is not None and b2 is not None:
                    current_section = detected
                    section_bounds[detected] = (b1, b2)
                    if detected == "dev_capital":
                        seen_devcap = True
            elif seen_devcap and helper.matches_stop(page):
                log.append(f"p{page_number}: STOP - left the 4 tables")
                break

            if not current_section:
                continue
            b1, b2 = section_bounds.get(current_section, (None, None))
            if b1 is None or b2 is None:
                continue
            for row in extract_printed_rows(page, current_section, page_number, b1, b2):
                key = (row["expenditure_table"], row["code"])
                row_instances[key] += 1
                row["row_instance"] = row_instances[key]
                printed_rows.append(row)
    return printed_rows, log


def write_rollup(rows: list[dict]) -> list[dict]:
    by_key = {(row["expenditure_table"], row["code"]): row for row in rows}
    children = defaultdict(list)
    for row in rows:
        if str(row["level"]) == "2" and row["parent_code"]:
            children[(row["expenditure_table"], row["parent_code"])].append(row)

    out = []
    for (table, code), row in sorted(by_key.items()):
        if str(row["level"]) != "1":
            continue
        child_rows = children.get((table, code), [])
        for estimate in ["BE_prior", "RE_prior", "BE_current"]:
            child_sum = sum(float(child[estimate]) for child in child_rows)
            printed_total = float(row[estimate])
            diff = printed_total - child_sum
            if diff == 0:
                status = "exact"
            elif abs(diff) <= 2:
                status = "rounding"
            elif table == "current_capital" and code == "01":
                status = "known_artifact"
            else:
                status = "diff"
            out.append(
                {
                    "fiscal_year": FY,
                    "expenditure_table": table,
                    "top_code": code,
                    "top_name": row["printed_name"],
                    "estimate": estimate,
                    "printed_top_total": int(printed_total)
                    if printed_total == int(printed_total)
                    else printed_total,
                    "sum_printed_children": int(child_sum) if child_sum == int(child_sum) else child_sum,
                    "difference_top_minus_children": int(diff) if diff == int(diff) else diff,
                    "child_count": len(child_rows),
                    "status": status,
                }
            )
    return out


def main() -> int:
    if not os.path.exists(PDF_PATH):
        print(f"Missing PDF: {PDF_PATH}", file=sys.stderr)
        return 1

    schema = load_schema()
    rows, log = process_pdf()
    for row in rows:
        row["schema_name"] = schema.get(row["code"], {}).get("name", "")

    row_fields = [
        "fiscal_year",
        "expenditure_table",
        "page",
        "code",
        "row_instance",
        "parent_code",
        "level",
        "printed_name",
        "schema_name",
        "BE_prior",
        "RE_prior",
        "BE_current",
    ]
    with open(ROWS_OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=row_fields)
        writer.writeheader()
        writer.writerows(rows)

    rollup = write_rollup(rows)
    rollup_fields = [
        "fiscal_year",
        "expenditure_table",
        "top_code",
        "top_name",
        "estimate",
        "printed_top_total",
        "sum_printed_children",
        "difference_top_minus_children",
        "child_count",
        "status",
    ]
    with open(ROLLUP_OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rollup_fields)
        writer.writeheader()
        writer.writerows(rollup)

    counts = defaultdict(int)
    for row in rows:
        counts[(row["expenditure_table"], row["level"])] += 1
    print(f"Wrote {len(rows)} printed rows -> {ROWS_OUT}")
    print(f"Wrote {len(rollup)} roll-up rows -> {ROLLUP_OUT}")
    for table in ["current_revenue", "current_capital", "dev_revenue", "dev_capital"]:
        print(
            f"{table}: level1={counts[(table, 1)]} "
            f"level2={counts[(table, 2)]}"
        )
    for line in log:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
