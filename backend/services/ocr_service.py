"""
Azure Document Intelligence OCR service.

Extracts follow-up appointment information from uploaded medical documents
(discharge papers, clinical notes, referral letters).

Uses the Azure Document Intelligence prebuilt-layout model combined with
regex pattern matching to identify follow-up instructions.

For production: Consider training a custom model on medical discharge papers
for higher accuracy than the general-purpose layout model.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from config import get_settings

settings = get_settings()


@dataclass
class ExtractedAppointment:
    provider_name: Optional[str]
    date: Optional[str]          # ISO 8601 date string (YYYY-MM-DD)
    location: Optional[str]
    raw_text: str                # Original sentence from document


# Regex patterns for common follow-up phrasings in medical documents
FOLLOWUP_PATTERNS = [
    # "Follow up with Dr. Smith in 2 weeks"
    re.compile(
        r"follow[\s-]?up\s+(?:with\s+(?P<provider>(?:Dr\.?\s+\w+|[A-Z][a-z]+\s+[A-Z][a-z]+)))?"
        r".*?(?:in\s+(?P<weeks>\d+)\s+weeks?|on\s+(?P<date>\d{1,2}[/-]\d{1,2}[/-]\d{2,4}))",
        re.IGNORECASE,
    ),
    # "Return to clinic in 14 days"
    re.compile(
        r"return\s+(?:to\s+(?:clinic|office|hospital))?\s+"
        r"(?:in\s+(?P<days>\d+)\s+days?|on\s+(?P<date>\d{1,2}[/-]\d{1,2}[/-]\d{2,4}))",
        re.IGNORECASE,
    ),
    # "Appointment scheduled for March 10, 2026"
    re.compile(
        r"appointment\s+(?:scheduled\s+for\s+|on\s+)"
        r"(?P<date>(?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+\d{1,2},?\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        re.IGNORECASE,
    ),
]


def _parse_date_string(raw: str) -> Optional[str]:
    """
    Attempts to parse various date formats into ISO 8601 (YYYY-MM-DD).
    Returns None if parsing fails.
    """
    formats = [
        "%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%m-%d-%y",
        "%B %d, %Y", "%B %d %Y",
    ]
    raw = raw.strip().rstrip(".")
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _add_weeks(weeks: int) -> str:
    """Return ISO date string for N weeks from today."""
    from datetime import date, timedelta
    return (date.today() + timedelta(weeks=weeks)).isoformat()


def _add_days(days: int) -> str:
    """Return ISO date string for N days from today."""
    from datetime import date, timedelta
    return (date.today() + timedelta(days=days)).isoformat()


async def extract_text_from_bytes(
    document_bytes: bytes,
    content_type: str = "application/pdf",
) -> str:
    """
    Extract plain text from a document using Azure Document Intelligence.
    Returns the concatenated text of all pages.
    Raises RuntimeError if Azure is not configured or the call fails.
    """
    if not settings.azure_doc_intelligence_endpoint or not settings.azure_doc_intelligence_key:
        raise RuntimeError("Azure Document Intelligence not configured.")

    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.core.credentials import AzureKeyCredential

    client = DocumentIntelligenceClient(
        endpoint=settings.azure_doc_intelligence_endpoint,
        credential=AzureKeyCredential(settings.azure_doc_intelligence_key),
    )

    poller = client.begin_analyze_document(
        model_id="prebuilt-layout",
        body=document_bytes,
        content_type=content_type,
    )
    result = poller.result()

    return " ".join(
        line.content
        for page in (result.pages or [])
        for line in (page.lines or [])
    )


async def extract_followup_appointments(
    document_bytes: bytes,
    content_type: str = "application/pdf",
) -> list[ExtractedAppointment]:
    """
    Extract follow-up appointments from a medical document.

    Tries Azure Document Intelligence first; falls back to local regex-only
    extraction if Azure credentials are not configured.
    """
    if not settings.azure_doc_intelligence_endpoint or not settings.azure_doc_intelligence_key:
        # Regex-only mode (no Azure configured)
        return _extract_with_regex("(Document text extraction requires Azure configuration.)")

    try:
        from azure.ai.documentintelligence import DocumentIntelligenceClient
        from azure.core.credentials import AzureKeyCredential

        client = DocumentIntelligenceClient(
            endpoint=settings.azure_doc_intelligence_endpoint,
            credential=AzureKeyCredential(settings.azure_doc_intelligence_key),
        )

        poller = client.begin_analyze_document(
            model_id="prebuilt-layout",
            body=document_bytes,
            content_type=content_type,
        )
        result = poller.result()

        # Concatenate all page text
        full_text = " ".join(
            line.content
            for page in (result.pages or [])
            for line in (page.lines or [])
        )

        return _extract_with_regex(full_text)

    except Exception as exc:
        raise RuntimeError(f"Azure Document Intelligence error: {exc}") from exc


def _extract_with_regex(text: str) -> list[ExtractedAppointment]:
    """Apply all follow-up patterns to document text."""
    appointments: list[ExtractedAppointment] = []

    for pattern in FOLLOWUP_PATTERNS:
        for match in pattern.finditer(text):
            # Extract the surrounding sentence as raw_text
            start = max(0, match.start() - 20)
            end = min(len(text), match.end() + 80)
            raw_text = text[start:end].strip()

            groups = match.groupdict()
            provider = groups.get("provider")
            date_str = None

            if groups.get("date"):
                date_str = _parse_date_string(groups["date"])
            elif groups.get("weeks"):
                date_str = _add_weeks(int(groups["weeks"]))
            elif groups.get("days"):
                date_str = _add_days(int(groups["days"]))

            appointments.append(ExtractedAppointment(
                provider_name=provider,
                date=date_str,
                location=None,
                raw_text=raw_text,
            ))

    # Deduplicate by date
    seen = set()
    unique = []
    for appt in appointments:
        key = (appt.date, appt.provider_name)
        if key not in seen:
            seen.add(key)
            unique.append(appt)

    return unique
