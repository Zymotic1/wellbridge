"""
Appointments router — list, create, delete, and provider search.

Provider search strategy (in priority order):
  1. cms_providers table (local Supabase) — fast trigram search, populated by
     running  python scripts/import_cms_providers.py  once.  Handles partial
     names like "Monmou" → "Monmouth Medical Center" via pg_trgm.
  2. CMS Provider Data live API (data.cms.gov) — free, no key required.
     Searched when the local table is empty or returns nothing.
     Queries org_name OR last_name in parallel; also handles city partial-match.
  3. CMS NPI Registry live API (npiregistry.cms.hhs.gov) — used as last resort
     for providers not in the DAC dataset (e.g. newly enrolled providers).
"""

import asyncio
import httpx
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional

from middleware.tenant import get_tenant_context, TenantContext
from services.supabase_client import get_admin_client

router = APIRouter(prefix="/appointments", tags=["appointments"])

NPI_API = "https://npiregistry.cms.hhs.gov/api/"
CMS_DAC_API = "https://data.cms.gov/provider-data/api/1/datastore/query/mj5m-pzi6/0"


# ── Models ────────────────────────────────────────────────────────────────────

class AppointmentCreate(BaseModel):
    provider_name: Optional[str] = None
    facility_name: Optional[str] = None
    appointment_date: datetime
    duration_minutes: int = 30
    notes: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    npi: Optional[str] = None


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("/")
async def list_appointments(
    ctx: TenantContext = Depends(get_tenant_context),
    include_past: bool = False,
):
    """List upcoming (or all) appointments for the authenticated patient."""
    try:
        db = get_admin_client()
        query = (
            db.table("appointments")
            .select(
                "id, provider_name, facility_name, appointment_date, "
                "duration_minutes, notes, source, phone, address"
            )
            .eq("tenant_id", ctx.tenant_id)
            .eq("patient_user_id", ctx.user_id)
            .order("appointment_date")
        )
        if not include_past:
            query = query.gte("appointment_date", datetime.utcnow().isoformat())

        result = query.limit(50).execute()
        return {"appointments": result.data or []}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_appointment(
    body: AppointmentCreate,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Manually create an appointment."""
    try:
        db = get_admin_client()
        payload: dict = {
            "tenant_id": ctx.tenant_id,
            "patient_user_id": ctx.user_id,
            "provider_name": body.provider_name,
            "facility_name": body.facility_name,
            "appointment_date": body.appointment_date.isoformat(),
            "duration_minutes": body.duration_minutes,
            "notes": body.notes,
            "source": "manual",
        }
        if body.phone:
            payload["phone"] = body.phone
        if body.address:
            payload["address"] = body.address
        if body.npi:
            payload["npi"] = body.npi

        result = db.table("appointments").insert(payload).execute()
        return result.data[0]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/{appointment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_appointment(
    appointment_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Delete an appointment (ownership enforced by explicit tenant/user filter)."""
    try:
        db = get_admin_client()
        result = (
            db.table("appointments")
            .delete()
            .eq("id", appointment_id)
            .eq("tenant_id", ctx.tenant_id)
            .eq("patient_user_id", ctx.user_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Appointment not found.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Provider search ───────────────────────────────────────────────────────────

@router.get("/search-provider")
async def search_provider(
    q: str = Query(..., min_length=2, description="Provider or practice name to search"),
    state: List[str] = Query(default=[], description="State filter(s) — repeat for multiple, e.g. state=NJ&state=NY"),
    specialty: List[str] = Query(default=[], description="Specialty filter(s) — repeat for multiple"),
    _ctx: TenantContext = Depends(get_tenant_context),
):
    """
    Search for healthcare providers.

    Priority:
      1. Local cms_providers table (pg_trgm — fast, handles partials like 'Monmou')
      2. CMS data.cms.gov live API (if local table is empty)
      3. CMS NPI Registry (last resort)

    Optional filters applied at each tier:
      state     — two-letter state abbreviation(s); repeat param for multiple (e.g. state=NJ&state=NY)
      specialty — CMS specialty string(s); repeat param for multiple
    """
    # ── 1. Local cms_providers (pg_trgm) ────────────────────────────────────
    local_results = await _search_local(q, state, specialty)
    if local_results:
        return {"results": local_results, "source": "local"}

    # ── 2. CMS DAC API (live) ────────────────────────────────────────────────
    cms_results = await _search_cms_api(q, state, specialty)
    if cms_results:
        return {"results": cms_results, "source": "cms_api"}

    # ── 3. NPI Registry (last resort) ────────────────────────────────────────
    npi_results = await _search_npi_registry(q, state, specialty)
    return {"results": npi_results, "source": "npi"}


# ── Search helpers ────────────────────────────────────────────────────────────

async def _search_local(q: str, states: List[str], specialties: List[str]) -> list[dict]:
    """Query the local cms_providers table via the search_cms_providers RPC."""
    try:
        db = get_admin_client()
        result = db.rpc(
            "search_cms_providers",
            {
                "q": q,
                "states":      [s.upper() for s in states]      if states      else None,
                "specialties": [s.upper() for s in specialties]  if specialties else None,
                "lim": 15,
            },
        ).execute()

        rows = result.data or []
        return [
            {
                "npi":       r["npi"],
                # If the query matched on org_name, show it prominently
                "name":      r["display_name"],
                "facility":  r.get("org_name") or "",
                "specialty": r.get("specialty") or "",
                "address":   r.get("address") or "",
                "phone":     r.get("phone") or "",
                "city":      r.get("city") or "",
                "state":     r.get("state_abbr") or "",
            }
            for r in rows
        ]
    except Exception:
        return []


async def _search_cms_api(q: str, states: List[str], specialties: List[str]) -> list[dict]:
    """
    Query the CMS Doctors & Clinicians dataset API directly.

    Runs two parallel requests:
      - Search by org_nm (practice/facility name)  — handles 'Monmouth Medical'
      - Search by lst_nm (individual last name)     — handles 'Smith', 'Monmouth' (rare last name)
    Both use LIKE with surrounding wildcards so partial input always matches.
    State and specialty filters are added as additional AND conditions when provided.
    Note: the CMS DAC API only supports single-value filters; when multiple are
    selected the first value is used for this fallback tier.
    """
    # Single-value fallbacks for the CMS API (multi-value handled by local RPC)
    state     = states[0]     if states     else None
    specialty = specialties[0] if specialties else None

    def _cms_params(field: str) -> dict:
        p: dict = {
            "conditions[0][property]": field,
            "conditions[0][value]":    f"%{q}%",
            "conditions[0][operator]": "LIKE",
            "limit": "10",
        }
        idx = 1
        if state:
            p[f"conditions[{idx}][property]"] = "st"
            p[f"conditions[{idx}][value]"]    = state.upper()
            p[f"conditions[{idx}][operator]"] = "="
            idx += 1
        if specialty:
            p[f"conditions[{idx}][property]"] = "pri_spec"
            p[f"conditions[{idx}][value]"]    = specialty.upper()
            p[f"conditions[{idx}][operator]"] = "="
        return p

    def _parse_cms_row(row: dict) -> dict:
        # CMS API returns old-style column names
        first = (row.get("frst_nm") or row.get("Provider First Name") or "").strip()
        last  = (row.get("lst_nm")  or row.get("Provider Last Name")  or "").strip()
        cred  = (row.get("Cred")    or "").strip()
        org   = (row.get("org_nm")  or row.get("Facility Name")       or "").strip()

        full_name = " ".join(p for p in [cred, first, last] if p).strip()
        name = full_name or org or "Unknown"

        line1 = (row.get("adr_ln_1") or "").strip()
        line2 = (row.get("adr_ln_2") or "").strip()
        addr  = ", ".join(p for p in [line1, line2] if p)

        return {
            "npi":       (row.get("NPI") or "").strip(),
            "name":      name,
            "facility":  org,
            "specialty": (row.get("pri_spec") or "").strip(),
            "address":   addr,
            "phone":     (row.get("phn_numbr") or row.get("Telephone Number") or "").strip(),
            "city":      (row.get("cty") or row.get("City/Town") or "").strip(),
            "state":     (row.get("st")  or row.get("State")     or "").strip(),
        }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            org_res, ind_res = await asyncio.gather(
                client.get(CMS_DAC_API, params=_cms_params("org_nm")),
                client.get(CMS_DAC_API, params=_cms_params("lst_nm")),
                return_exceptions=True,
            )

        results: list[dict] = []
        seen: set[str] = set()

        for res in [org_res, ind_res]:
            if isinstance(res, Exception):
                continue
            try:
                data = res.json()
            except Exception:
                continue
            for row in (data.get("results") or []):
                r = _parse_cms_row(row)
                npi = r["npi"]
                if npi and npi not in seen:
                    seen.add(npi)
                    results.append(r)

        return results[:12]
    except Exception:
        return []


async def _search_npi_registry(q: str, states: List[str], specialties: List[str]) -> list[dict]:
    """
    Last-resort search via the CMS NPI Registry API.
    Searches individual providers (display_name) and organizations in parallel.
    NPI Registry uses taxonomy descriptions for specialty — we pass the value directly.
    Note: NPI Registry only supports single-value filters; when multiple are
    selected the first value is used for this fallback tier.
    """
    params_base: dict = {"version": "2.1", "limit": "7", "skip": "0"}
    if states:
        params_base["state"] = states[0].upper()
    if specialties:
        # NPI Registry accepts taxonomy_description for specialty filtering
        params_base["taxonomy_description"] = specialties[0]

    params_ind = {**params_base, "search_type": "NPI-1", "display_name": q}
    params_org = {**params_base, "search_type": "NPI-2", "organization_name": q}

    def _parse(res) -> list[dict]:
        if isinstance(res, Exception):
            return []
        try:
            data = res.json()
        except Exception:
            return []
        out = []
        for r in (data.get("results") or []):
            basic      = r.get("basic", {})
            addresses  = r.get("addresses", [])
            taxonomies = r.get("taxonomies", [])

            location = next(
                (a for a in addresses if a.get("address_purpose") == "LOCATION"),
                addresses[0] if addresses else {},
            )
            primary_tax = next(
                (t for t in taxonomies if t.get("primary")),
                taxonomies[0] if taxonomies else {},
            )

            if basic.get("organization_name"):
                name = basic["organization_name"]
            else:
                parts = [
                    basic.get("credential", ""),
                    basic.get("first_name", ""),
                    basic.get("middle_name", ""),
                    basic.get("last_name", ""),
                ]
                name = " ".join(p for p in parts if p).strip() or "Unknown"

            addr_parts = [
                location.get("address_1", ""),
                location.get("address_2", ""),
                location.get("city", ""),
                location.get("state", ""),
                (location.get("postal_code") or "")[:5],
            ]
            address = ", ".join(p for p in addr_parts if p)

            out.append({
                "npi":       r.get("number", ""),
                "name":      name,
                "specialty": primary_tax.get("desc", ""),
                "address":   address,
                "phone":     location.get("telephone_number", ""),
                "city":      location.get("city", ""),
                "state":     location.get("state", ""),
            })
        return out

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            ind_res, org_res = await asyncio.gather(
                client.get(NPI_API, params=params_ind),
                client.get(NPI_API, params=params_org),
                return_exceptions=True,
            )

        seen: set[str] = set()
        results: list[dict] = []
        for r in _parse(ind_res) + _parse(org_res):
            npi = r["npi"]
            if npi not in seen:
                seen.add(npi)
                results.append(r)
        return results[:10]
    except Exception:
        return []
