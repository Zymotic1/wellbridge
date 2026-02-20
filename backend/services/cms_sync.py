"""
CMS Doctors & Clinicians dataset — incremental diff-sync service.

Algorithm (mark-and-sweep diff):
  1. Fetch CMS metadata → get `modified` timestamp for the dataset.
  2. Compare against last successful sync in cms_sync_log.
     → If unchanged, log "skipped" and return immediately (no download).
  3. Download the new CSV and upsert every row.
     Each upserted row gets  updated_at = sync_start_time.
  4. After all rows are upserted, DELETE any cms_providers rows where
     updated_at < sync_start_time — these NPIs were removed from CMS.
  5. Write a 'success' row to cms_sync_log with counts.

The same `updated_at` column already exists on cms_providers (added in 0016).
The upsert explicitly sets it so we can sweep stale rows afterward.

Concurrency guard:
  Before starting, check whether a 'running' entry younger than 2 hours
  exists in cms_sync_log.  If so, skip to prevent double-runs in multi-
  instance deployments.
"""

import csv
import io
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from services.supabase_client import get_admin_client

log = logging.getLogger("cms_sync")

DATASET_ID   = "mj5m-pzi6"
METADATA_URL = (
    f"https://data.cms.gov/provider-data/api/1/metastore/schemas/dataset/"
    f"items/{DATASET_ID}?show-reference-ids=true"
)
DATASET_NAME = "cms_dac"
BATCH_SIZE   = 500
CHUNK_BYTES  = 1024 * 1024   # 1 MB per stream chunk


# ── Public entry point ────────────────────────────────────────────────────────

async def run_sync(force: bool = False) -> dict:
    """
    Execute one full sync cycle.  Returns a summary dict.
    Safe to call from APScheduler or an admin HTTP endpoint.

    Args:
        force: If True, skip the "already up to date" check and re-import even
               if CMS reports the same modified date as last sync.
    """
    db = get_admin_client()

    # ── Concurrency guard ────────────────────────────────────────────────────
    if not force and _sync_already_running(db):
        log.info("cms_sync: another sync is already running — skipping")
        return {"status": "skipped", "reason": "already_running"}

    # ── Open log row ─────────────────────────────────────────────────────────
    log_id = _open_log(db, DATASET_NAME)
    sync_start = datetime.now(tz=timezone.utc)

    try:
        # ── Step 1: check CMS metadata ───────────────────────────────────────
        meta = await _fetch_metadata()
        source_url      = meta.get("download_url")
        source_modified = meta.get("modified")       # ISO-8601 string or None

        _update_log(db, log_id, source_url=source_url, source_modified=source_modified)

        # ── Step 2: compare with last sync ───────────────────────────────────
        if not force and source_modified:
            last_sync_modified = _last_sync_modified(db, DATASET_NAME)
            if last_sync_modified and last_sync_modified >= source_modified:
                _close_log(db, log_id, status="skipped", rows_upserted=0, rows_deleted=0)
                log.info("cms_sync: CMS dataset unchanged since last sync (%s) — skipped",
                         last_sync_modified)
                return {"status": "skipped", "source_modified": source_modified}

        if not source_url:
            raise ValueError("Could not resolve CMS CSV download URL from metadata")

        # ── Step 3: stream download + upsert ─────────────────────────────────
        log.info("cms_sync: downloading %s …", source_url)
        rows_upserted = await _download_and_upsert(source_url, db, sync_start)

        # ── Step 4: delete stale providers (mark-and-sweep) ──────────────────
        rows_deleted = _sweep_stale(db, sync_start)

        # ── Step 5: close log ─────────────────────────────────────────────────
        _close_log(db, log_id, status="success",
                   rows_upserted=rows_upserted, rows_deleted=rows_deleted)

        log.info("cms_sync: done — %d upserted, %d deleted", rows_upserted, rows_deleted)
        return {
            "status": "success",
            "rows_upserted": rows_upserted,
            "rows_deleted":  rows_deleted,
            "source_modified": source_modified,
        }

    except Exception as exc:
        _close_log(db, log_id, status="error", error=str(exc))
        log.exception("cms_sync: failed — %s", exc)
        return {"status": "error", "error": str(exc)}


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _fetch_metadata() -> dict:
    """Return dict with 'download_url' and 'modified' from CMS metadata API."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(METADATA_URL)
        resp.raise_for_status()
        meta = resp.json()

    modified   = meta.get("modified")
    distributions = meta.get("distribution", [])
    download_url: Optional[str] = None

    for dist in distributions:
        data = dist.get("data", {})
        if data.get("mediaType") == "text/csv":
            download_url = data.get("downloadURL") or data.get("accessURL")
            if download_url:
                break

    return {"download_url": download_url, "modified": modified}


async def _download_and_upsert(url: str, db, sync_start: datetime) -> int:
    """Stream-download the CMS CSV and upsert rows in batches.  Returns row count."""
    upserted = 0
    batch: list[dict] = []
    buf = io.StringIO()

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            header_done = False
            reader: Optional[csv.DictReader] = None
            partial = ""

            async for raw_chunk in resp.aiter_bytes(chunk_size=CHUNK_BYTES):
                text  = partial + raw_chunk.decode("utf-8", errors="replace")
                lines = text.split("\n")
                partial = lines.pop()    # Last line may be incomplete

                if not header_done:
                    # Build reader from header + first real lines
                    combined = "\n".join(lines)
                    buf = io.StringIO(combined)
                    reader = csv.DictReader(buf)
                    header_done = True
                else:
                    buf = io.StringIO("\n".join(lines))
                    buf_reader = csv.reader(buf)
                    rows_text = list(buf_reader)
                    # Re-parse using the original header
                    if reader and reader.fieldnames:
                        for cols in rows_text:
                            if not cols:
                                continue
                            row_dict = dict(zip(reader.fieldnames, cols))
                            rec = _build_row(row_dict, sync_start)
                            if rec is None:
                                continue
                            batch.append(rec)
                            if len(batch) >= BATCH_SIZE:
                                _upsert_batch(db, batch)
                                upserted += len(batch)
                                batch = []

            # Flush remainder
            if partial and reader and reader.fieldnames:
                cols = next(csv.reader([partial]), [])
                if cols:
                    row_dict = dict(zip(reader.fieldnames, cols))
                    rec = _build_row(row_dict, sync_start)
                    if rec:
                        batch.append(rec)

    if batch:
        _upsert_batch(db, batch)
        upserted += len(batch)

    return upserted


def _build_row(row: dict, sync_start: datetime) -> Optional[dict]:
    """Map a CMS CSV row → cms_providers record.  Returns None to skip.

    CMS updated DAC column names to human-readable labels (circa 2024).
    Also strips trailing whitespace from all keys (some headers contain \\t padding).
    """
    # Strip whitespace from all header keys (e.g. "Cred\t\t\t" → "Cred")
    row = {k.strip(): v for k, v in row.items()}

    npi = (row.get("NPI") or "").strip()
    if not npi:
        return None

    first = (row.get("Provider First Name") or "").strip()
    last  = (row.get("Provider Last Name")  or "").strip()
    cred  = (row.get("Cred")               or "").strip()
    org   = (row.get("Facility Name")       or "").strip()

    full_name = " ".join(p for p in [cred, first, last] if p).strip()
    display   = full_name or org
    if not display:
        return None

    line1   = (row.get("adr_ln_1") or "").strip()
    line2   = (row.get("adr_ln_2") or "").strip()
    address = ", ".join(p for p in [line1, line2] if p) or None
    zip_raw = (row.get("ZIP Code") or "").strip()

    return {
        "npi":          npi,
        "display_name": display,
        "first_name":   first or None,
        "last_name":    last  or None,
        "org_name":     org   or None,
        "credential":   cred  or None,
        "specialty":    (row.get("pri_spec") or "").strip() or None,
        "address":      address,
        "city":         (row.get("City/Town")        or "").strip() or None,
        "state_abbr":   (row.get("State")             or "").strip() or None,
        "zip":          zip_raw[:5] or None,
        "phone":        (row.get("Telephone Number") or "").strip() or None,
        "updated_at":   sync_start.isoformat(),   # Used for sweep
    }


def _upsert_batch(db, batch: list[dict], retries: int = 3) -> None:
    # Deduplicate within batch (CMS CSV has duplicate NPI rows)
    deduped: dict[str, dict] = {}
    for row in batch:
        deduped[row["npi"]] = row
    clean_batch = list(deduped.values())

    for attempt in range(retries):
        try:
            db.table("cms_providers").upsert(clean_batch, on_conflict="npi").execute()
            return
        except Exception as exc:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                log.warning("cms_sync: batch upsert failed after %d retries: %s", retries, exc)


def _sweep_stale(db, sync_start: datetime) -> int:
    """Delete cms_providers rows not seen in this sync (NPI was removed from CMS)."""
    try:
        result = (
            db.table("cms_providers")
            .delete()
            .lt("updated_at", sync_start.isoformat())
            .execute()
        )
        return len(result.data or [])
    except Exception as exc:
        log.warning("cms_sync: sweep failed — %s", exc)
        return 0


# ── Sync log helpers ──────────────────────────────────────────────────────────

def _open_log(db, dataset: str) -> str:
    result = db.table("cms_sync_log").insert({"dataset": dataset}).execute()
    return result.data[0]["id"]


def _update_log(db, log_id: str, **kwargs) -> None:
    db.table("cms_sync_log").update(kwargs).eq("id", log_id).execute()


def _close_log(db, log_id: str, status: str,
               rows_upserted: int = 0, rows_deleted: int = 0,
               error: Optional[str] = None) -> None:
    db.table("cms_sync_log").update({
        "status":        status,
        "finished_at":   datetime.now(tz=timezone.utc).isoformat(),
        "rows_upserted": rows_upserted,
        "rows_deleted":  rows_deleted,
        "error":         error,
    }).eq("id", log_id).execute()


def _last_sync_modified(db, dataset: str) -> Optional[str]:
    """Return the source_modified value from the last successful sync."""
    result = (
        db.table("cms_sync_log")
        .select("source_modified")
        .eq("dataset", dataset)
        .eq("status", "success")
        .order("started_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0]["source_modified"] if rows else None


def _sync_already_running(db) -> bool:
    """Return True if a sync started in the last 2 hours is still 'running'."""
    from datetime import timedelta
    cutoff = (datetime.now(tz=timezone.utc) - timedelta(hours=2)).isoformat()
    result = (
        db.table("cms_sync_log")
        .select("id")
        .eq("dataset", DATASET_NAME)
        .eq("status", "running")
        .gte("started_at", cutoff)
        .limit(1)
        .execute()
    )
    return bool(result.data)
