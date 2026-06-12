#!/usr/bin/env python3
"""Compare FY2026-27 subcode output to printed PDF totals."""

from __future__ import annotations

import csv
import os
from collections import defaultdict


THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(THIS_DIR, ".."))
FY = "2026-27"
CORRECTED_SUBCODES_CSV = os.path.join(ROOT_DIR, f"subcodes_wide_{FY}_corrected.csv")
SUBCODES_CSV = (
    CORRECTED_SUBCODES_CSV
    if os.path.exists(CORRECTED_SUBCODES_CSV)
    else os.path.join(ROOT_DIR, f"subcodes_wide_{FY}.csv")
)
PRINTED_CSV = os.path.join(THIS_DIR, f"printed_code_totals_{FY}.csv")
DETAIL_OUT = os.path.join(THIS_DIR, f"subcodes_vs_printed_detail_{FY}.csv")
ROLLUP_OUT = os.path.join(THIS_DIR, f"subcodes_vs_printed_rollup_{FY}.csv")

TABLES = {
    "cur_rev": "current_revenue",
    "cur_cap": "current_capital",
    "dev_rev": "dev_revenue",
    "dev_cap": "dev_capital",
}
ESTIMATES = ["BE_prior", "RE_prior", "BE_current"]


def to_number(value: str) -> float:
    text = str(value).strip().replace(",", "")
    if not text or text == "-":
        return 0.0
    return float(text)


def fmt_number(value: float) -> int | float:
    return int(value) if value == int(value) else value


def main() -> int:
    with open(SUBCODES_CSV, newline="", encoding="utf-8-sig") as f:
        subcode_rows = list(csv.DictReader(f))
    with open(PRINTED_CSV, newline="", encoding="utf-8-sig") as f:
        printed_rows = list(csv.DictReader(f))

    printed_detail_totals = defaultdict(lambda: {estimate: 0.0 for estimate in ESTIMATES})
    printed_detail_counts = defaultdict(int)
    for row in printed_rows:
        if row["level"] != "2":
            continue
        key = (row["expenditure_table"], row["code"])
        printed_detail_counts[key] += 1
        for estimate in ESTIMATES:
            printed_detail_totals[key][estimate] += to_number(row[estimate])

    detail_rows = []
    detail_counts = defaultdict(int)
    for sub_row in subcode_rows:
        code = sub_row["code"]
        for short_table, table in TABLES.items():
            printed = printed_detail_totals.get((table, code))
            for estimate in ESTIMATES:
                col = f"{FY}_{short_table}_{estimate}"
                sub_value = to_number(sub_row[col])
                if printed is None:
                    printed_value = 0.0
                    status = "not_printed_zero" if sub_value == 0 else "missing_printed_row"
                else:
                    printed_value = printed[estimate]
                    diff = sub_value - printed_value
                    status = "exact" if diff == 0 else "diff"
                diff = sub_value - printed_value
                detail_counts[status] += 1
                detail_rows.append(
                    {
                        "fiscal_year": FY,
                        "expenditure_table": table,
                        "code": code,
                        "parent_code": sub_row["parent_code"],
                        "estimate": estimate,
                        "subcodes_value": fmt_number(sub_value),
                        "printed_detail_value": fmt_number(printed_value),
                        "printed_row_count_for_code": printed_detail_counts.get((table, code), 0),
                        "difference_subcodes_minus_printed": fmt_number(diff),
                        "status": status,
                    }
                )

    with open(DETAIL_OUT, "w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "fiscal_year",
            "expenditure_table",
            "code",
            "parent_code",
            "estimate",
            "subcodes_value",
            "printed_detail_value",
            "printed_row_count_for_code",
            "difference_subcodes_minus_printed",
            "status",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(detail_rows)

    printed_top_by_key = {
        (row["expenditure_table"], row["code"]): row
        for row in printed_rows
        if row["level"] == "1"
    }
    rollup_rows = []
    rollup_counts = defaultdict(int)
    for table in TABLES.values():
        parents = sorted(
            {
                row["parent_code"]
                for row in subcode_rows
                if row["parent_code"] and (table, row["parent_code"]) in printed_top_by_key
            }
        )
        for parent in parents:
            printed_top = printed_top_by_key[(table, parent)]
            children = [row for row in subcode_rows if row["parent_code"] == parent]
            for estimate in ESTIMATES:
                short = next(k for k, v in TABLES.items() if v == table)
                col = f"{FY}_{short}_{estimate}"
                sub_sum = sum(to_number(row[col]) for row in children)
                printed_total = to_number(printed_top[estimate])
                diff = sub_sum - printed_total
                if diff == 0:
                    status = "exact"
                elif abs(diff) <= 2:
                    status = "rounding"
                elif table == "current_capital" and parent == "01":
                    status = "known_artifact"
                else:
                    status = "diff"
                rollup_counts[status] += 1
                rollup_rows.append(
                    {
                        "fiscal_year": FY,
                        "expenditure_table": table,
                        "parent_code": parent,
                        "estimate": estimate,
                        "subcodes_child_sum": fmt_number(sub_sum),
                        "printed_top_total": fmt_number(printed_total),
                        "difference_subcodes_minus_printed_top": fmt_number(diff),
                        "child_count": len(children),
                        "status": status,
                    }
                )

    with open(ROLLUP_OUT, "w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "fiscal_year",
            "expenditure_table",
            "parent_code",
            "estimate",
            "subcodes_child_sum",
            "printed_top_total",
            "difference_subcodes_minus_printed_top",
            "child_count",
            "status",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rollup_rows)

    print(f"Wrote detail comparison -> {DETAIL_OUT}")
    print(f"Wrote rollup comparison -> {ROLLUP_OUT}")
    print("Detail statuses:", ", ".join(f"{k}={detail_counts[k]}" for k in sorted(detail_counts)))
    print("Rollup statuses:", ", ".join(f"{k}={rollup_counts[k]}" for k in sorted(rollup_counts)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
