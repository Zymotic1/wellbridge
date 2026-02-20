#!/usr/bin/env python3
"""
Import the CMS Doctors & Clinicians dataset into the cms_providers Supabase table.

Source:  https://data.cms.gov/provider-data/topics/doctors-clinicians
Dataset: DAC_NationalDownloadableFile.csv  (~2.7 M rows, ~400 MB)

Usage
-----
# From the wellbridge/ root:
cd wellbridge
python scripts/import_cms_providers.py

# With a pre-downloaded file (skip the download):
python scripts/import_cms_providers.py --csv /path/to/DAC_NationalDownloadableFile.csv

# Filter to one state only (useful for testing or smaller installs):
python scripts/import_cms_providers.py --state NJ

Prerequisites
-------------
pip install requests python-dotenv supabase tqdm

.env (or environment) must have:
  SUPABASE_URL=...
  SUPABASE_SERVICE_KEY=...
"""

import argparse
import csv
import io
import os
import sys
import time
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv
from supabase import create_client
from tqdm import tqdm

# ── Config ────────────────────────────────────────────────────────────────────

DATASET_ID = "mj5m-pzi6"          # CMS Doctors & Clinicians
METADATA_URL = (
    "https://data.cms.gov/provider-data/api/1/metastore/schemas/dataset/items/"
    f"{DATASET_ID}?show-reference-ids=true"
)
BATCH_SIZE = 500                   # rows per Supabase upsert
CHUNK_BYTES = 1024 * 1024          # 1 MB download chunks


# ── Helpers ───────────────────────────────────────────────────────────────────

def find_download_url() -> str:
    """Discover the current CSV download URL from CMS dataset metadata."""
    print("Fetching dataset metadata from CMS…")
    resp = requests.get(METADATA_URL, timeout=30)
    resp.raise_for_status()
    meta = resp.json()

    distributions = meta.get("distribution", [])
    for dist in distributions:
        data = dist.get("data", {})
        if data.get("mediaType") == "text/csv":
            url = data.get("downloadURL") or data.get("accessURL")
            if url:
                return url

    raise RuntimeError(
        "Could not find a CSV download URL in CMS dataset metadata. "
        "Check https://data.cms.gov/provider-data/topics/doctors-clinicians manually."
    )


def download_csv(url: str, dest: Path) -> None:
    """Stream-download the CSV file to disk with a progress bar."""
    print(f"Downloading from:\n  {url}")
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        with open(dest, "wb") as f, tqdm(
            total=total, unit="B", unit_scale=True, desc="Downloading"
        ) as bar:
            for chunk in r.iter_content(chunk_size=CHUNK_BYTES):
                f.write(chunk)
                bar.update(len(chunk))
    print(f"Saved to {dest}")


def clean(val: Optional[str]) -> Optional[str]:
    """Strip and return None for empty strings."""
    if not val:
        return None
    v = val.strip()
    return v if v else None


def build_row(row: dict) -> Optional[dict]:
    """Map a CMS CSV row to a cms_providers record.  Returns None to skip.

    CMS updated their DAC column names (circa 2024) from short codes to
    human-readable labels.  We strip all header whitespace first (some headers
    like "Cred" arrive with trailing tab characters in the downloaded file).

    New name  →  Old name
    ---------------------------------
    Provider Last Name   → lst_nm
    Provider First Name  → frst_nm
    Facility Name        → org_nm
    City/Town            → cty
    State                → st
    ZIP Code             → zip
    Telephone Number     → phn_numbr
    """
    # Strip trailing whitespace from all keys (some CMS headers contain \t padding)
    row = {k.strip(): v for k, v in row.items()}

    npi = clean(row.get("NPI"))
    if not npi:
        return None

    first = clean(row.get("Provider First Name")) or ""
    last  = clean(row.get("Provider Last Name"))  or ""
    cred  = clean(row.get("Cred"))                or ""
    org   = clean(row.get("Facility Name"))

    # Build display name: individual = "Cred First Last", org-only = facility name
    full_name = " ".join(p for p in [cred, first, last] if p).strip() or None
    display   = full_name or org
    if not display:
        return None

    # Address
    line1 = clean(row.get("adr_ln_1")) or ""
    line2 = clean(row.get("adr_ln_2")) or ""
    address = ", ".join(p for p in [line1, line2] if p) or None

    # ZIP: keep 5-digit only
    zip_raw = clean(row.get("ZIP Code"))
    zip5 = zip_raw[:5] if zip_raw else None

    return {
        "npi":          npi,
        "display_name": display,
        "first_name":   first or None,
        "last_name":    last  or None,
        "org_name":     org,
        "credential":   cred  or None,
        "specialty":    clean(row.get("pri_spec")),
        "address":      address,
        "city":         clean(row.get("City/Town")),
        "state_abbr":   clean(row.get("State")),
        "zip":          zip5,
        "phone":        clean(row.get("Telephone Number")),
    }


def import_file(
    csv_path: Path,
    client,
    state_filter: Optional[str] = None,
) -> None:
    """Read the CSV and upsert rows into cms_providers in batches."""
    state_filter = state_filter.upper() if state_filter else None

    print(f"Reading {csv_path}…")

    imported = 0
    skipped  = 0
    batch: list[dict] = []

    # f.tell() is disabled by csv's line iterator, so track progress by row count
    with open(csv_path, newline="", encoding="utf-8-sig") as f, tqdm(
        unit=" rows", desc="Importing"
    ) as bar:
        reader = csv.DictReader(f)
        for raw in reader:
            bar.update(1)

            r = build_row(raw)
            if r is None:
                skipped += 1
                continue
            if state_filter and r.get("state_abbr") != state_filter:
                skipped += 1
                continue

            batch.append(r)

            if len(batch) >= BATCH_SIZE:
                _upsert(client, batch)
                imported += len(batch)
                batch = []

    if batch:
        _upsert(client, batch)
        imported += len(batch)

    print(f"\nDone — {imported:,} rows imported, {skipped:,} skipped.")


def _upsert(client, batch: list[dict], retries: int = 3) -> None:
    """Upsert a batch, deduplicating by NPI first.

    The CMS CSV contains duplicate NPI rows (same provider listed under
    multiple specialties or addresses).  PostgreSQL raises error 21000
    if the same PK appears twice in a single ON CONFLICT upsert — we
    deduplicate within each batch to prevent this.  Last occurrence wins.
    """
    # Deduplicate within batch: keep last row for each NPI
    deduped: dict[str, dict] = {}
    for row in batch:
        deduped[row["npi"]] = row
    clean_batch = list(deduped.values())

    for attempt in range(retries):
        try:
            client.table("cms_providers").upsert(clean_batch, on_conflict="npi").execute()
            return
        except Exception as exc:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                print(f"  [WARN] batch upsert failed after {retries} attempts: {exc}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Import CMS provider data into Supabase")
    parser.add_argument("--csv",   help="Path to a pre-downloaded DAC_NationalDownloadableFile.csv")
    parser.add_argument("--state", help="Only import providers for this state (e.g. NJ, CA)")
    args = parser.parse_args()

    # Load .env from wellbridge/ root (one level up from scripts/)
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()

    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")

    if not supabase_url or not supabase_key:
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
        sys.exit(1)

    client = create_client(supabase_url, supabase_key)

    # Resolve the CSV path
    if args.csv:
        csv_path = Path(args.csv)
        if not csv_path.exists():
            print(f"ERROR: File not found: {csv_path}")
            sys.exit(1)
    else:
        csv_path = Path(__file__).parent / "DAC_NationalDownloadableFile.csv"
        if not csv_path.exists():
            try:
                url = find_download_url()
            except Exception as exc:
                print(f"ERROR discovering download URL: {exc}")
                sys.exit(1)
            download_csv(url, csv_path)

    import_file(csv_path, client, state_filter=args.state)


if __name__ == "__main__":
    main()
