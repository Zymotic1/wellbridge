"""
OpenAI function calling tool definitions for the brain LLM.

These define what tools the brain can call, their parameters, and descriptions.
The brain LLM uses these to decide when to fetch records, check appointments, etc.
"""

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "fetch_patient_records",
            "description": (
                "Search the patient's stored medical records by semantic similarity. "
                "Use this when the patient asks about their specific medical history, "
                "visit notes, test results, medications they were prescribed, or anything "
                "documented by their healthcare providers. Returns relevant record excerpts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query — what to look for in the records",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_patient_records",
            "description": (
                "List all patient records on file (dates, providers, types). "
                "Use this when you need to know what records exist before searching, "
                "or when the patient asks 'what records do you have?'"
            ),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_appointments",
            "description": (
                "Get the patient's upcoming appointments. Use this when the patient "
                "asks about their schedule, upcoming visits, or when you need to know "
                "their next appointment for context (e.g., preparing questions)."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]
