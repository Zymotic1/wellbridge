"""
Google Calendar service — creates calendar events from confirmed appointments.

Requires a service account JSON or OAuth credentials configured via the
GOOGLE_CALENDAR_CREDENTIALS_JSON environment variable (base64-encoded JSON).

For OAuth (user's own calendar), the credentials should be obtained via
the /auth/google/calendar flow (not implemented here — out of MVP scope;
for MVP, service account or manual OAuth tokens are acceptable).
"""

import base64
import json
from typing import Optional

from config import get_settings

settings = get_settings()


async def create_calendar_event(
    summary: str,
    date: str,          # ISO 8601 date (YYYY-MM-DD)
    description: str = "",
    location: Optional[str] = None,
    duration_minutes: int = 30,
) -> Optional[str]:
    """
    Create a Google Calendar event.

    Returns the Google Calendar event ID on success, or None if not configured.
    Raises RuntimeError if Calendar API returns an error.
    """
    if not settings.google_calendar_credentials_json:
        return None  # Calendar integration not configured

    try:
        creds_json = json.loads(
            base64.b64decode(settings.google_calendar_credentials_json).decode()
        )
    except Exception as exc:
        raise RuntimeError(f"Invalid GOOGLE_CALENDAR_CREDENTIALS_JSON: {exc}") from exc

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        credentials = service_account.Credentials.from_service_account_info(
            creds_json,
            scopes=["https://www.googleapis.com/auth/calendar"],
        )

        service = build("calendar", "v3", credentials=credentials)

        # Build event with date + 30-minute duration
        start_datetime = f"{date}T09:00:00"  # Default: 9am local
        end_dt_hour = 9 + (duration_minutes // 60)
        end_dt_min = duration_minutes % 60
        end_datetime = f"{date}T{end_dt_hour:02d}:{end_dt_min:02d}:00"

        event = {
            "summary": summary,
            "description": description,
            "start": {
                "dateTime": start_datetime,
                "timeZone": "America/New_York",
            },
            "end": {
                "dateTime": end_datetime,
                "timeZone": "America/New_York",
            },
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": 60 * 24},  # 24h before
                    {"method": "popup", "minutes": 60},        # 1h before
                ],
            },
        }

        if location:
            event["location"] = location

        result = (
            service.events()
            .insert(calendarId="primary", body=event)
            .execute()
        )

        return result.get("id")

    except Exception as exc:
        raise RuntimeError(f"Google Calendar API error: {exc}") from exc
