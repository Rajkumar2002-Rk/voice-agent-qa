"""Tool schemas handed to Retell.

Identical across both prompt arms — the prompt is the only thing that varies.
`url` is filled in at provision time from the public tunnel URL.
"""

from __future__ import annotations

from typing import Any


def tool_schemas(base_url: str) -> list[dict[str, Any]]:
    base = base_url.rstrip("/")
    return [
        {
            "type": "custom",
            "name": "check_availability",
            "description": (
                "Look up open appointment slots for a specific calendar date. "
                "Must be called before telling the caller any specific time. "
                "Returns the exact list of available times."
            ),
            "url": f"{base}/check_availability",
            "method": "POST",
            "speak_during_execution": True,
            "speak_after_execution": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": (
                            "The calendar date to check, as YYYY-MM-DD. Resolve "
                            "relative phrases like 'next Tuesday' to an explicit "
                            "date before calling."
                        ),
                    }
                },
                "required": ["date"],
            },
        },
        {
            "type": "custom",
            "name": "book_appointment",
            "description": (
                "Commit the appointment. Only call this after reading all four "
                "details back to the caller and getting confirmation."
            ),
            "url": f"{base}/book_appointment",
            "method": "POST",
            "speak_during_execution": False,
            "speak_after_execution": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_name": {"type": "string", "description": "Full name of the patient."},
                    "date": {"type": "string", "description": "Appointment date as YYYY-MM-DD."},
                    "time": {"type": "string", "description": "Appointment time as 24-hour HH:MM."},
                    "reason": {"type": "string", "description": "Why the patient is coming in."},
                    "phone": {"type": "string", "description": "Callback number, if given."},
                },
                "required": ["patient_name", "date", "time", "reason"],
            },
        },
    ]
