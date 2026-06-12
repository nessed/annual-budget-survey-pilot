#!/usr/bin/env python3
"""
Download Pakistan Federal Budget Annual Budget Statement PDFs from finance.gov.pk.
"""

import os
import time
import requests

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "budget_docs")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,application/octet-stream,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.finance.gov.pk/",
}

FISCAL_YEARS = [
    {"fy": "2010-11", "url": "https://finance.gov.pk/budget/abs_10_11.pdf"},
    {"fy": "2011-12", "url": "https://finance.gov.pk/budget/abs_11_12.pdf"},
    {"fy": "2012-13", "url": "https://finance.gov.pk/budget/abs_2012_13.pdf"},
    {"fy": "2013-14", "url": "https://finance.gov.pk/budget/abs_2013_14.pdf"},
    {"fy": "2014-15", "url": "https://finance.gov.pk/budget/abs_2014_15.pdf"},
    {"fy": "2015-16", "url": "https://finance.gov.pk/budget/abs_2015_16.pdf"},
    {"fy": "2016-17", "url": "https://finance.gov.pk/budget/abs_2016_17.pdf"},
    {"fy": "2017-18", "url": "https://finance.gov.pk/budget/Annual%20Budget%20Statement%202017-18.pdf"},
    {"fy": "2018-19", "url": "https://finance.gov.pk/budget/Annual_Budget_Statement_2018_19.pdf"},
    {"fy": "2019-20", "url": "https://finance.gov.pk/budget/Annual_Budget_Statement_2019_20.pdf"},
    {"fy": "2020-21", "url": "https://finance.gov.pk/budget/Annual_budget_Statement_English_202021.pdf"},
    {"fy": "2021-22", "url": "https://finance.gov.pk/budget/Budget_2021_22/1_ABS-English_2021_22.pdf"},
    {"fy": "2022-23", "url": "https://finance.gov.pk/budget/Budget_2022_23/Annual_Budget_Statement_English.pdf"},
    {"fy": "2023-24", "url": "https://finance.gov.pk/budget/Budget_2023_24/Annual_Budget_Statement.pdf"},
    {"fy": "2024-25", "url": "https://finance.gov.pk/budget/Budget_2024_25/Annual_Budget_Statement.pdf"},
    {"fy": "2025-26", "url": "https://finance.gov.pk/budget/budget_2025_26/abs_eng_10062025.pdf"},
]

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def is_pdf(data: bytes) -> bool:
    return data[:4] == b"%PDF"


def download(fy: str, url: str) -> dict:
    out_dir = os.path.join(BASE_DIR, fy)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "annual_budget_statement.pdf")

    try:
        resp = SESSION.get(url, timeout=60, allow_redirects=True)
        if resp.status_code == 404:
            return {"fy": fy, "status": "not_found", "url": url, "note": "404 Not Found"}
        if resp.status_code != 200:
            return {"fy": fy, "status": "failed", "url": url, "note": f"HTTP {resp.status_code}"}

        content_type = resp.headers.get("Content-Type", "")
        if "text/html" in content_type and not is_pdf(resp.content):
            return {"fy": fy, "status": "failed", "url": url, "note": "HTML page returned (not a PDF)"}

        if not is_pdf(resp.content):
            return {"fy": fy, "status": "failed", "url": url, "note": f"Bad magic bytes: {resp.content[:8]!r}"}

        with open(out_path, "wb") as f:
            f.write(resp.content)
        return {"fy": fy, "status": "success", "url": url, "note": f"{len(resp.content):,} bytes"}

    except requests.exceptions.ConnectionError:
        return {"fy": fy, "status": "failed", "url": url, "note": "Connection error"}
    except requests.exceptions.Timeout:
        return {"fy": fy, "status": "failed", "url": url, "note": "Timeout"}
    except Exception as exc:
        return {"fy": fy, "status": "failed", "url": url, "note": str(exc)}


def main():
    os.makedirs(BASE_DIR, exist_ok=True)
    results = []

    print("=" * 72)
    print("Pakistan Federal Budget — Annual Budget Statement Downloader")
    print("=" * 72)

    for i, entry in enumerate(FISCAL_YEARS):
        fy, url = entry["fy"], entry["url"]
        print(f"\nFY {fy}")
        print(f"  URL: {url}")
        result = download(fy, url)
        results.append(result)
        icon = "✓" if result["status"] == "success" else "✗"
        print(f"  {icon} {result['status'].upper()}: {result['note']}")
        if i < len(FISCAL_YEARS) - 1:
            time.sleep(2.5)

    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    print(f"{'FY':<10}  {'Status':<10}  {'Note'}")
    print("-" * 72)
    successes = 0
    for r in results:
        icon = "✓" if r["status"] == "success" else "✗"
        print(f"{r['fy']:<10}  {icon} {r['status']:<8}  {r['note']}")
        if r["status"] == "success":
            successes += 1
    print("-" * 72)
    print(f"Downloaded: {successes}/{len(results)}")
    print(f"Saved to:   {BASE_DIR}")


if __name__ == "__main__":
    main()
