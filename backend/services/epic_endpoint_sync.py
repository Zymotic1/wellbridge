"""
Epic SMART on FHIR endpoint directory sync.

Source: open.epic.com — public lists of Epic-connected health systems.
  R4   endpoint list: https://open.epic.com/Endpoints/R4
  DSTU2 endpoint list: https://open.epic.com/Endpoints/DSTU2

Each entry represents a healthcare organization (hospital, clinic system, etc.)
that supports Epic's SMART on FHIR for patient record access.  This powers
the "Connect to your health system" flow where a patient picks their hospital
from a searchable list.

The datasets are small (~1,000–2,000 orgs total), so we do a full replace
each run:  upsert all current entries, then delete any that disappeared.

Update frequency: Epic updates these lists periodically (no fixed schedule).
We check weekly; the `last_seen_at` column handles the sweep.
"""

import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from services.supabase_client import get_admin_client

log = logging.getLogger("epic_endpoint_sync")

EPIC_ENDPOINTS = {
    "r4":    "https://open.epic.com/Endpoints/R4",
    "dstu2": "https://open.epic.com/Endpoints/DSTU2",
}
DATASET_NAME = "epic_r4"


# ── Public entry point ────────────────────────────────────────────────────────

async def run_sync(force: bool = False) -> dict:
    """
    Fetch both the Epic R4 and DSTU2 endpoint lists, upsert all orgs, and
    sweep any that are no longer present.  Returns a summary dict.
    """
    db  = get_admin_client()
    log_id = _open_log(db, DATASET_NAME)
    sync_start = datetime.now(tz=timezone.utc)

    try:
        all_entries: list[dict] = []

        async with httpx.AsyncClient(timeout=30) as client:
            for version, url in EPIC_ENDPOINTS.items():
                try:
                    resp = await client.get(url, headers={"Accept": "application/json"})
                    resp.raise_for_status()
                    data = resp.json()
                    all_entries.extend(_parse_entries(data, version, sync_start))
                    log.info("epic_sync: fetched %d entries from %s", len(data), url)
                except Exception as exc:
                    log.warning("epic_sync: failed to fetch %s — %s", url, exc)

        if not all_entries:
            _close_log(db, log_id, status="error", error="No entries fetched from Epic")
            return {"status": "error", "error": "No entries fetched"}

        # Upsert all current entries
        upserted = _upsert_all(db, all_entries)

        # Sweep: delete entries not seen in this sync
        deleted = _sweep_stale(db, sync_start)

        _close_log(db, log_id, status="success",
                   rows_upserted=upserted, rows_deleted=deleted)
        log.info("epic_sync: done — %d upserted, %d deleted", upserted, deleted)
        return {"status": "success", "rows_upserted": upserted, "rows_deleted": deleted}

    except Exception as exc:
        _close_log(db, log_id, status="error", error=str(exc))
        log.exception("epic_sync: failed — %s", exc)
        return {"status": "error", "error": str(exc)}


# ── Parsing ───────────────────────────────────────────────────────────────────

def _parse_entries(data, version: str, sync_start: datetime) -> list[dict]:
    """
    Convert the raw JSON from open.epic.com into epic_endpoint_directory rows.

    Epic's endpoint lists return a JSON array.  Each element is a FHIR
    Endpoint resource (or a simplified variant).  The fields we care about:

      R4 / DSTU2 format (simplified):
        "OrganizationName"  or  resource.managingOrganization.display
        "Address"           or  resource.address  — the FHIR base URL
        "Status"            — "active" | "off"

    Because both formats appear across Epic's published lists, we check
    multiple field paths and fall back gracefully.
    """
    entries = []
    for item in (data if isinstance(data, list) else []):
        # Organization name
        name = (
            item.get("OrganizationName")
            or item.get("resourceType") and _dig(item, "managingOrganization", "display")
            or ""
        ).strip()

        # FHIR base URL
        url = (item.get("Address") or item.get("address") or "").strip()

        if not name or not url:
            continue

        # Stable ID: hash of the FHIR URL (URL is effectively the PK)
        entry_id = hashlib.sha1(url.encode()).hexdigest()[:20]

        is_active = str(item.get("Status") or item.get("status") or "active").lower() == "active"

        entry: dict = {
            "id":               entry_id,
            "organization_name": name,
            "is_production":    is_active,
            "last_seen_at":     sync_start.isoformat(),
        }

        if version == "r4":
            entry["fhir_r4_url"]   = url
        else:
            entry["fhir_dstu2_url"] = url

        # State: some entries include "StateAbbr" or similar
        state = (item.get("StateAbbr") or item.get("state") or "").strip().upper()
        if state and len(state) == 2:
            entry["state_abbr"] = state

        entries.append(entry)

    return entries


def _dig(d: dict, *keys) -> Optional[str]:
    """Safe nested dict access."""
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d if isinstance(d, str) else None


# ── Database helpers ──────────────────────────────────────────────────────────

def _upsert_all(db, entries: list[dict]) -> int:
    BATCH = 200
    total = 0
    for i in range(0, len(entries), BATCH):
        batch = entries[i : i + BATCH]
        db.table("epic_endpoint_directory").upsert(
            batch, on_conflict="id"
        ).execute()
        total += len(batch)
    return total


def _sweep_stale(db, sync_start: datetime) -> int:
    try:
        result = (
            db.table("epic_endpoint_directory")
            .delete()
            .lt("last_seen_at", sync_start.isoformat())
            .execute()
        )
        return len(result.data or [])
    except Exception as exc:
        log.warning("epic_sync: sweep failed — %s", exc)
        return 0


def _open_log(db, dataset: str) -> str:
    result = db.table("cms_sync_log").insert({"dataset": dataset}).execute()
    return result.data[0]["id"]


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
