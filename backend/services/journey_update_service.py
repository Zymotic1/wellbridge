"""
Journey update service — keeps the patient's Journey timeline in sync after
a document is uploaded and analyzed.

Called after note_analysis_service.analyze_note() completes. Takes the
structured NoteAnalysisResult and upserts medications and appointments into
the database, with deduplication so the same medication or appointment is
never listed twice.

Deduplication rules:
  Medications:   keyed by lowercase medication name within a patient's records.
                 If a prescription record already exists for that medication,
                 update the content (newer upload may have an updated dose).
                 If not, insert a new prescription record.

  Appointments:  keyed by (provider_name + appointment_date calendar day) for
                 the patient. If an appointment already exists on that day with
                 the same provider, skip it. If not, insert.

  Referrals:     stored as clinical_note records so the patient can see them in
                 the Documents filter. No dedup — each referral is distinct.

The Journey page (frontend/app/(app)/journey/page.tsx) auto-assembles from:
  - patient_records → "document" (clinical_note) and "medication" (prescription)
  - appointments    → "visit"

So inserting correctly typed records here is all that's needed for the Journey
to reflect the upload.
"""

import logging
from datetime import date, datetime
from typing import Any

from services.note_analysis_service import NoteAnalysisResult, Prescription, FollowUpAppointment
from middleware.tenant import TenantContext
from services.supabase_client import get_admin_client

log = logging.getLogger("wellbridge.journey")


async def update_journey_from_analysis(
    analysis: NoteAnalysisResult,
    ctx: TenantContext,
) -> dict[str, Any]:
    """
    Upsert prescriptions and appointments extracted from a clinical note.

    Returns a summary dict with counts of inserted/updated items.
    Raises on unexpected errors — caller should catch and treat as non-blocking.
    """
    # Admin client bypasses RLS — security enforced by explicit tenant/user
    # filters already present on every query in this function.
    db = get_admin_client()
    today = date.today().isoformat()

    meds_inserted = 0
    meds_updated = 0
    appts_inserted = 0
    appts_skipped = 0

    # ── Medications (prescriptions) ────────────────────────────────────────────
    for rx in analysis.prescriptions:
        if not rx.medication:
            continue

        med_name = rx.medication.strip()
        content = _format_prescription_content(rx)

        try:
            # Check if a prescription record already exists for this medication
            existing = (
                db.table("patient_records")
                .select("id")
                .eq("tenant_id", ctx.tenant_id)
                .eq("patient_user_id", ctx.user_id)
                .eq("record_type", "prescription")
                .ilike("provider_name", f"%{med_name}%")
                .limit(1)
                .execute()
            )

            if existing.data:
                # Update — newer upload supersedes old dose/frequency
                record_id = existing.data[0]["id"]
                db.table("patient_records").update({
                    "content": content,
                    "note_date": today,
                }).eq("id", record_id).execute()
                log.info("journey: updated prescription record for '%s' (id=%s)", med_name, record_id)
                meds_updated += 1
            else:
                # Insert new prescription record
                db.table("patient_records").insert({
                    "tenant_id": ctx.tenant_id,
                    "patient_user_id": ctx.user_id,
                    "record_type": "prescription",
                    "provider_name": med_name,   # medication name in provider_name for Journey title
                    "note_date": today,
                    "content": content,
                }).execute()
                log.info("journey: inserted prescription record for '%s'", med_name)
                meds_inserted += 1

        except Exception as exc:
            log.warning("journey: failed to upsert prescription '%s' — %s", med_name, exc)

    # ── Appointments ───────────────────────────────────────────────────────────
    for appt in analysis.follow_up_appointments:
        appt_date = _parse_appointment_date(appt.date_or_timeframe)
        if not appt_date:
            # Can't store without a parseable date — skip
            log.debug("journey: skipping appointment with no parseable date: %s", appt)
            appts_skipped += 1
            continue

        provider = (appt.provider_name or appt.specialty or "").strip()

        try:
            # Check if this appointment already exists (same provider + same calendar day)
            query = (
                db.table("appointments")
                .select("id")
                .eq("tenant_id", ctx.tenant_id)
                .eq("patient_user_id", ctx.user_id)
                .gte("appointment_date", appt_date + "T00:00:00")
                .lte("appointment_date", appt_date + "T23:59:59")
            )
            if provider:
                query = query.ilike("provider_name", f"%{provider}%")

            existing = query.limit(1).execute()

            if existing.data:
                log.info("journey: appointment already exists for provider='%s' date=%s — skipping", provider, appt_date)
                appts_skipped += 1
            else:
                notes_parts = []
                if appt.specialty:
                    notes_parts.append(f"Specialty: {appt.specialty}")
                if appt.reason:
                    notes_parts.append(f"Reason: {appt.reason}")
                if appt.location:
                    notes_parts.append(f"Location: {appt.location}")

                db.table("appointments").insert({
                    "tenant_id": ctx.tenant_id,
                    "patient_user_id": ctx.user_id,
                    "provider_name": provider or None,
                    "facility_name": appt.location or None,
                    "appointment_date": appt_date + "T09:00:00",  # Default to 9am if no time
                    "notes": "\n".join(notes_parts) or None,
                    "source": "manual",
                }).execute()
                log.info("journey: inserted appointment for provider='%s' date=%s", provider, appt_date)
                appts_inserted += 1

        except Exception as exc:
            log.warning("journey: failed to upsert appointment for '%s' on %s — %s", provider, appt_date, exc)

    return {
        "medications_inserted": meds_inserted,
        "medications_updated": meds_updated,
        "appointments_inserted": appts_inserted,
        "appointments_skipped": appts_skipped,
    }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _format_prescription_content(rx: Prescription) -> str:
    """Build a human-readable content string for a prescription record."""
    parts = [f"Medication: {rx.medication}"]
    if rx.dose:
        parts.append(f"Dose: {rx.dose}")
    if rx.frequency:
        parts.append(f"When to take: {rx.frequency}")
    if rx.instructions:
        parts.append(f"Instructions: {rx.instructions}")
    if rx.duration:
        parts.append(f"Duration: {rx.duration}")
    return "\n".join(parts)


def _parse_appointment_date(date_or_timeframe: str | None) -> str | None:
    """
    Try to parse a date string or relative timeframe into an ISO date string.

    Handles:
      - ISO dates: "2026-03-10"
      - US dates: "3/10/2026", "03/10/26"
      - Written dates: "March 10, 2026"
      - Relative: "in 3 months", "in 2 weeks" — computed from today

    Returns ISO date string ("YYYY-MM-DD") or None if unparseable.
    """
    if not date_or_timeframe:
        return None

    text = date_or_timeframe.strip()

    # Try standard date parsing with dateutil
    try:
        from dateutil import parser as dateutil_parser
        parsed = dateutil_parser.parse(text, fuzzy=True)
        return parsed.date().isoformat()
    except Exception:
        pass

    # Relative timeframes: "in N months", "in N weeks", "in N days"
    import re
    m = re.search(r"in\s+(\d+)\s+(day|week|month)s?", text, re.IGNORECASE)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        today_dt = datetime.today()
        try:
            from dateutil.relativedelta import relativedelta
            if unit == "day":
                future = today_dt + relativedelta(days=n)
            elif unit == "week":
                future = today_dt + relativedelta(weeks=n)
            else:
                future = today_dt + relativedelta(months=n)
            return future.date().isoformat()
        except Exception:
            pass

    return None
