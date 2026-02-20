"""
Epic MyChart / SMART on FHIR integration service.

Implements the full SMART App Launch Framework (v1 + v2 compatible) for
patient-facing standalone launch against Epic EHR systems.

Flow:
  1. User picks hospital → we look up its FHIR base URL from Epic's directory
  2. We fetch the .well-known/smart-configuration to get authorization/token endpoints
  3. Frontend generates PKCE code_verifier + code_challenge (SHA-256, base64url)
  4. We return the full Epic authorization URL → frontend redirects user to MyChart
  5. User logs in and authorises → Epic redirects to our /epic/callback
  6. Frontend sends us the auth code + code_verifier → we exchange for tokens
  7. We store encrypted tokens and Epic patient FHIR ID in epic_connections
  8. We sync the patient's records (medications, conditions, appointments, etc.)
     and upsert them into our patient_records / appointments tables

FHIR Resources fetched on sync:
  • Patient               — demographics
  • MedicationRequest     — prescriptions / active meds
  • Condition             — diagnoses
  • AllergyIntolerance    — allergies
  • Appointment           — upcoming + past appointments
  • Encounter             — visit history
  • Observation (labs)    — lab results
  • Observation (vitals)  — vital signs
  • DocumentReference     — clinical documents

Developer registration (open.epic.com):
  See EPIC_DEVELOPER_REGISTRATION.md in the project root for full instructions.
"""

import hashlib
import json
import logging
import os
import time
from base64 import urlsafe_b64encode
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel

from config import get_settings

settings = get_settings()
log = logging.getLogger("wellbridge.epic")

# ── Endpoint directory cache ──────────────────────────────────────────────────
# Refreshed at most once per 24 h to avoid hammering Epic's servers.
_ENDPOINT_CACHE: list[dict] = []
_ENDPOINT_CACHE_TS: float = 0.0
_ENDPOINT_CACHE_TTL: float = 86400.0  # 24 hours

# Local Brands Bundle file (place epic_endpoint_DSTU2.json in the backend folder)
_LOCAL_BUNDLE_PATH = Path(__file__).parent.parent / "epic_endpoint_DSTU2.json"

# Epic's public FHIR R4 endpoint bundle — used only if local file is absent
EPIC_ENDPOINT_BUNDLE_URL = "https://open.epic.com/Endpoints/R4"

# Scopes to request — covers all patient data we need
SMART_SCOPES = (
    "openid fhirUser offline_access "
    "patient/Patient.read "
    "patient/MedicationRequest.read "
    "patient/Condition.read "
    "patient/Appointment.read "
    "patient/Encounter.read "
    "patient/AllergyIntolerance.read "
    "patient/Observation.read "
    "patient/DocumentReference.read"
)


# ── Data models ───────────────────────────────────────────────────────────────

class EpicEndpoint(BaseModel):
    organization_name: str
    fhir_base_url: str


class SmartConfig(BaseModel):
    authorization_endpoint: str
    token_endpoint: str
    scopes_supported: list[str] = []


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    scope: str
    patient: Optional[str] = None       # Epic's patient FHIR ID
    refresh_token: Optional[str] = None


# ── Token encryption ──────────────────────────────────────────────────────────

def _get_fernet() -> Fernet:
    key = settings.epic_token_encryption_key
    if not key:
        raise RuntimeError(
            "EPIC_TOKEN_ENCRYPTION_KEY is not set. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_token(token: str) -> str:
    """Encrypt a token string for DB storage."""
    return _get_fernet().encrypt(token.encode()).decode()


def decrypt_token(encrypted: str) -> str:
    """Decrypt a stored token. Raises InvalidToken if key or data is wrong."""
    return _get_fernet().decrypt(encrypted.encode()).decode()


# ── Endpoint directory ────────────────────────────────────────────────────────

def _parse_bundle_entries(bundle: dict) -> list[dict]:
    """Extract active Endpoint resources from a FHIR Bundle."""
    endpoints: list[dict] = []
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        if resource.get("resourceType") != "Endpoint":
            continue
        if resource.get("status") != "active":
            continue
        name = resource.get("name") or resource.get("id", "Unknown")
        address = resource.get("address", "")
        if address:
            endpoints.append({"organization_name": name, "fhir_base_url": address})
    return endpoints


def _load_local_bundle() -> list[dict] | None:
    """
    Load and parse the local Brands Bundle JSON file.
    Returns the endpoint list, or None if the file is absent / unreadable.
    The file is large (~85 MB) so we parse once at startup and cache the result.
    """
    if not _LOCAL_BUNDLE_PATH.exists():
        return None
    try:
        with _LOCAL_BUNDLE_PATH.open("r", encoding="utf-8") as fh:
            bundle = json.load(fh)
        endpoints = _parse_bundle_entries(bundle)
        log.info(
            "epic: loaded %d endpoints from local bundle %s",
            len(endpoints),
            _LOCAL_BUNDLE_PATH.name,
        )
        return endpoints
    except Exception as exc:
        log.warning("epic: failed to read local bundle — %s", exc)
        return None


async def get_endpoints(search: str = "") -> list[EpicEndpoint]:
    """
    Return Epic FHIR R4 endpoints matching the search string (hospital name).

    Loading priority:
      1. Local Brands Bundle file (epic_endpoint_DSTU2.json in backend/) — loaded
         once and cached for the process lifetime (24 h TTL still guards re-reads).
      2. Network fetch from Epic's public R4 bundle URL — used only when the local
         file is absent or failed to parse.

    Results are cached in memory for 24 hours.
    """
    global _ENDPOINT_CACHE, _ENDPOINT_CACHE_TS

    # Refresh cache if stale
    if time.time() - _ENDPOINT_CACHE_TS > _ENDPOINT_CACHE_TTL:
        # 1. Try local file first (fast, no network required)
        endpoints = _load_local_bundle()

        # 2. Fall back to network fetch if local file not available
        if endpoints is None:
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    resp = await client.get(
                        EPIC_ENDPOINT_BUNDLE_URL,
                        headers={"Accept": "application/json"},
                        follow_redirects=True,
                    )
                    resp.raise_for_status()
                    bundle = resp.json()
                endpoints = _parse_bundle_entries(bundle)
                log.info("epic: loaded %d endpoints from Epic network bundle", len(endpoints))
            except Exception as exc:
                log.warning("epic: failed to load endpoint directory from network — %s", exc)
                endpoints = []

        if endpoints:
            _ENDPOINT_CACHE = endpoints
            _ENDPOINT_CACHE_TS = time.time()

    # Filter by search term
    query = search.strip().lower()
    if not query:
        return [EpicEndpoint(**e) for e in _ENDPOINT_CACHE[:50]]

    matches = [
        EpicEndpoint(**e)
        for e in _ENDPOINT_CACHE
        if query in e["organization_name"].lower()
        or query in e["fhir_base_url"].lower()
    ]
    return matches[:20]


# ── SMART configuration discovery ─────────────────────────────────────────────

async def get_smart_config(fhir_base_url: str) -> SmartConfig:
    """
    Fetch .well-known/smart-configuration from the FHIR server.
    Falls back to metadata endpoint if smart-configuration is not found.
    """
    base = fhir_base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=15.0) as client:
        # Try SMART configuration endpoint first
        try:
            resp = await client.get(
                f"{base}/.well-known/smart-configuration",
                headers={"Accept": "application/json"},
                follow_redirects=True,
            )
            resp.raise_for_status()
            data = resp.json()
            return SmartConfig(
                authorization_endpoint=data["authorization_endpoint"],
                token_endpoint=data["token_endpoint"],
                scopes_supported=data.get("scopes_supported", []),
            )
        except Exception:
            pass

        # Fallback: FHIR metadata / CapabilityStatement
        resp = await client.get(
            f"{base}/metadata",
            headers={"Accept": "application/json"},
            follow_redirects=True,
        )
        resp.raise_for_status()
        meta = resp.json()
        security = (
            meta.get("rest", [{}])[0]
            .get("security", {})
            .get("extension", [])
        )
        auth_endpoint = token_endpoint = ""
        for ext in security:
            for sub in ext.get("extension", []):
                if sub.get("url") == "authorize":
                    auth_endpoint = sub.get("valueUri", "")
                if sub.get("url") == "token":
                    token_endpoint = sub.get("valueUri", "")

        if not auth_endpoint or not token_endpoint:
            raise ValueError(
                f"Could not discover SMART endpoints for {fhir_base_url}. "
                "This system may not support SMART on FHIR."
            )

        return SmartConfig(
            authorization_endpoint=auth_endpoint,
            token_endpoint=token_endpoint,
        )


# ── Authorization URL builder ─────────────────────────────────────────────────

def build_auth_url(
    smart_config: SmartConfig,
    state: str,
    code_challenge: str,
    fhir_base_url: str,
) -> str:
    """
    Build the Epic authorization URL to redirect the user to MyChart login.

    PKCE (code_challenge) is generated by the frontend and passed here.
    The frontend stores the matching code_verifier in sessionStorage for
    use in the token exchange step.
    """
    params = {
        "response_type": "code",
        "client_id": settings.epic_client_id,
        "redirect_uri": settings.epic_redirect_uri,
        "scope": SMART_SCOPES,
        "state": state,
        "aud": fhir_base_url,          # Required by SMART — tells Epic which FHIR server
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{smart_config.authorization_endpoint}?{urlencode(params)}"


# ── Token exchange ────────────────────────────────────────────────────────────

async def exchange_code(
    token_endpoint: str,
    code: str,
    code_verifier: str,
) -> TokenResponse:
    """Exchange an authorization code for access + refresh tokens."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.epic_redirect_uri,
                "client_id": settings.epic_client_id,
                "code_verifier": code_verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if not resp.is_success:
            raise ValueError(
                f"Token exchange failed ({resp.status_code}): {resp.text[:500]}"
            )
        return TokenResponse(**resp.json())


async def refresh_access_token(
    token_endpoint: str,
    refresh_token: str,
) -> TokenResponse:
    """Use a refresh token to get a new access token."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            token_endpoint,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": settings.epic_client_id,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        return TokenResponse(**resp.json())


# ── FHIR resource fetchers ────────────────────────────────────────────────────

async def _fhir_get(client: httpx.AsyncClient, url: str, token: str) -> dict:
    """Make an authenticated FHIR GET request, return JSON."""
    resp = await client.get(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/fhir+json",
        },
        follow_redirects=True,
    )
    resp.raise_for_status()
    return resp.json()


async def _bundle_entries(client: httpx.AsyncClient, url: str, token: str) -> list[dict]:
    """Fetch a FHIR searchset Bundle and return all resource entries."""
    data = await _fhir_get(client, url, token)
    entries = []
    for entry in data.get("entry", []):
        resource = entry.get("resource", {})
        if resource:
            entries.append(resource)
    return entries


async def fetch_patient_data(
    fhir_base_url: str,
    access_token: str,
    patient_id: str,
) -> dict:
    """
    Fetch all relevant patient FHIR resources in parallel.
    Returns a dict keyed by resource type.
    """
    base = fhir_base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=30.0) as client:
        import asyncio

        async def safe_fetch(url):
            try:
                return await _bundle_entries(client, url, access_token)
            except Exception as exc:
                log.warning("epic: fetch failed for %s — %s", url, exc)
                return []

        (
            medications,
            conditions,
            appointments,
            encounters,
            allergies,
            labs,
            vitals,
        ) = await asyncio.gather(
            safe_fetch(f"{base}/MedicationRequest?patient={patient_id}&_count=100"),
            safe_fetch(f"{base}/Condition?patient={patient_id}&category=problem-list-item&_count=100"),
            safe_fetch(f"{base}/Appointment?patient={patient_id}&_count=50"),
            safe_fetch(f"{base}/Encounter?patient={patient_id}&_count=50"),
            safe_fetch(f"{base}/AllergyIntolerance?patient={patient_id}&_count=100"),
            safe_fetch(f"{base}/Observation?patient={patient_id}&category=laboratory&_count=100"),
            safe_fetch(f"{base}/Observation?patient={patient_id}&category=vital-signs&_count=50"),
        )

    return {
        "medications": medications,
        "conditions": conditions,
        "appointments": appointments,
        "encounters": encounters,
        "allergies": allergies,
        "labs": labs,
        "vitals": vitals,
    }


# ── FHIR → WellBridge data mapping ────────────────────────────────────────────

def _extract_medication_name(med_resource: dict) -> Optional[str]:
    """Extract medication display name from a MedicationRequest resource."""
    # medicationCodeableConcept.text is the most readable
    concept = med_resource.get("medicationCodeableConcept", {})
    if concept.get("text"):
        return concept["text"]
    for coding in concept.get("coding", []):
        if coding.get("display"):
            return coding["display"]
    return med_resource.get("medicationReference", {}).get("display")


def _extract_dosage(med_resource: dict) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (dose_text, frequency_text, instructions) from a MedicationRequest."""
    dosages = med_resource.get("dosageInstruction", [])
    if not dosages:
        return None, None, None
    d = dosages[0]
    dose = d.get("doseAndRate", [{}])[0].get("doseQuantity", {})
    dose_str = f"{dose.get('value', '')} {dose.get('unit', '')}".strip() or None
    freq = d.get("timing", {}).get("repeat", {})
    freq_str = None
    if freq.get("frequency") and freq.get("period") and freq.get("periodUnit"):
        freq_str = f"{freq['frequency']}x per {freq['period']} {freq['periodUnit']}"
    instructions = d.get("text") or d.get("patientInstruction")
    return dose_str, freq_str, instructions


def _fhir_date_to_iso(date_str: Optional[str]) -> Optional[str]:
    """Normalize a FHIR date/dateTime to ISO 8601 date string."""
    if not date_str:
        return None
    return date_str[:10]  # YYYY-MM-DD


def sync_fhir_data_to_db(
    fhir_data: dict,
    tenant_id: str,
    user_id: str,
    db,
) -> dict:
    """
    Upsert FHIR resources into WellBridge's patient_records and appointments tables.

    This is a sync operation (not async) — called from a sync context or
    wrapped in asyncio.to_thread if needed.

    Returns a summary of what was inserted/updated.
    """
    summary = {
        "medications": 0,
        "conditions": 0,
        "appointments": 0,
        "encounters": 0,
        "allergies": 0,
    }

    today = datetime.now(timezone.utc).date().isoformat()

    # ── Medications ──────────────────────────────────────────────────────────
    for med in fhir_data.get("medications", []):
        if med.get("status") not in ("active", "intended", "on-hold"):
            continue
        name = _extract_medication_name(med)
        if not name:
            continue
        dose, freq, instructions = _extract_dosage(med)
        content_parts = [f"Medication: {name}"]
        if dose:
            content_parts.append(f"Dose: {dose}")
        if freq:
            content_parts.append(f"Frequency: {freq}")
        if instructions:
            content_parts.append(f"Instructions: {instructions}")

        try:
            # Upsert: delete existing active prescription with same name, then insert
            db.table("patient_records").delete().eq(
                "tenant_id", tenant_id
            ).eq(
                "patient_user_id", user_id
            ).eq("record_type", "prescription").ilike(
                "provider_name", f"%{name}%"
            ).execute()

            db.table("patient_records").insert({
                "tenant_id": tenant_id,
                "patient_user_id": user_id,
                "record_type": "prescription",
                "provider_name": name,
                "note_date": today,
                "content": "\n".join(content_parts),
            }).execute()
            summary["medications"] += 1
        except Exception as exc:
            log.warning("epic sync: medication insert failed — %s", exc)

    # ── Conditions ───────────────────────────────────────────────────────────
    for cond in fhir_data.get("conditions", []):
        if cond.get("clinicalStatus", {}).get("coding", [{}])[0].get("code") not in (
            "active", "recurrence", "relapse"
        ):
            continue
        name = (
            cond.get("code", {}).get("text")
            or cond.get("code", {}).get("coding", [{}])[0].get("display")
        )
        if not name:
            continue
        onset = _fhir_date_to_iso(
            cond.get("onsetDateTime") or cond.get("recordedDate")
        ) or today

        try:
            db.table("patient_records").insert({
                "tenant_id": tenant_id,
                "patient_user_id": user_id,
                "record_type": "clinical_note",
                "provider_name": "Epic — Active Condition",
                "facility_name": "MyChart Sync",
                "note_date": onset,
                "content": f"Active condition: {name}",
            }).execute()
            summary["conditions"] += 1
        except Exception as exc:
            log.warning("epic sync: condition insert failed — %s", exc)

    # ── Appointments ─────────────────────────────────────────────────────────
    for appt in fhir_data.get("appointments", []):
        if appt.get("status") in ("cancelled", "noshow"):
            continue
        start = appt.get("start")
        if not start:
            continue
        participant = next(
            (
                p.get("actor", {}).get("display")
                for p in appt.get("participant", [])
                if p.get("actor", {}).get("type", "").lower() in ("practitioner", "")
                and "Patient" not in p.get("actor", {}).get("type", "Patient")
            ),
            None,
        )
        reason = (
            appt.get("reasonCode", [{}])[0].get("text")
            or appt.get("serviceType", [{}])[0].get("text")
            or appt.get("appointmentType", {}).get("text")
            or "Visit"
        )

        try:
            db.table("appointments").insert({
                "tenant_id": tenant_id,
                "patient_user_id": user_id,
                "provider_name": participant,
                "appointment_date": start,
                "duration_minutes": appt.get("minutesDuration", 30),
                "notes": reason,
                "source": "google_calendar",  # reuse existing source type
            }).execute()
            summary["appointments"] += 1
        except Exception as exc:
            log.warning("epic sync: appointment insert failed — %s", exc)

    # ── Encounters (visit history as clinical notes) ──────────────────────────
    for enc in fhir_data.get("encounters", []):
        if enc.get("status") not in ("finished", "completed"):
            continue
        enc_date = _fhir_date_to_iso(
            enc.get("period", {}).get("start") or enc.get("actualPeriod", {}).get("start")
        )
        if not enc_date:
            continue
        provider = enc.get("participant", [{}])[0].get("individual", {}).get("display")
        location = enc.get("location", [{}])[0].get("location", {}).get("display")
        reason = (
            enc.get("reasonCode", [{}])[0].get("text")
            or enc.get("type", [{}])[0].get("text")
            or "Outpatient Visit"
        )
        content = f"Visit: {reason}"
        if provider:
            content += f"\nProvider: {provider}"
        if location:
            content += f"\nLocation: {location}"

        try:
            db.table("patient_records").insert({
                "tenant_id": tenant_id,
                "patient_user_id": user_id,
                "record_type": "clinical_note",
                "provider_name": provider or "Epic — Visit",
                "facility_name": location,
                "note_date": enc_date,
                "content": content,
            }).execute()
            summary["encounters"] += 1
        except Exception as exc:
            log.warning("epic sync: encounter insert failed — %s", exc)

    # ── Allergies ────────────────────────────────────────────────────────────
    for allergy in fhir_data.get("allergies", []):
        if allergy.get("clinicalStatus", {}).get("coding", [{}])[0].get("code") != "active":
            continue
        substance = (
            allergy.get("code", {}).get("text")
            or allergy.get("code", {}).get("coding", [{}])[0].get("display")
        )
        if not substance:
            continue
        reactions = [
            r.get("manifestation", [{}])[0].get("text", "")
            for r in allergy.get("reaction", [])
        ]
        reaction_str = ", ".join(r for r in reactions if r)
        content = f"Allergy: {substance}"
        if reaction_str:
            content += f"\nReaction: {reaction_str}"

        try:
            db.table("patient_records").insert({
                "tenant_id": tenant_id,
                "patient_user_id": user_id,
                "record_type": "clinical_note",
                "provider_name": "Epic — Allergy",
                "note_date": today,
                "content": content,
            }).execute()
            summary["allergies"] += 1
        except Exception as exc:
            log.warning("epic sync: allergy insert failed — %s", exc)

    return summary
