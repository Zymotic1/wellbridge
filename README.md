# WellBridge — Safety-First Medical Record Assistant

WellBridge is a HIPAA-aligned agentic medical chat application that helps patients understand their own health records in plain language. The core architectural constraint is that **medical advice is physically impossible to output** — the refusal path never invokes the LLM.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      LAYER 1: GATEWAY                        │
│  Auth0 (HIPAA) → JWT with tenant_id + role → Next.js BFF   │
│  Supabase RLS → Row-level tenant isolation at DB layer       │
├─────────────────────────────────────────────────────────────┤
│                   LAYER 2: AGENTIC BRAIN                     │
│  LangGraph State Machine:                                    │
│    intent_classifier → MEDICAL_ADVICE → refusal (no LLM!)   │
│                      → SCHEDULING     → calendar_tool        │
│                      → RECORD_LOOKUP  → record_lookup        │
│                      → JARGON_EXPLAIN → jargon_explainer     │
│                      → PRE_VISIT_PREP → pre_visit_prep       │
├─────────────────────────────────────────────────────────────┤
│              LAYER 3: GUARDRAIL ENGINE                       │
│  Regex banned-phrase scanner → Flesch-Kincaid grade check   │
│  Any violation → replace with SAFE_FALLBACK (static text)   │
└─────────────────────────────────────────────────────────────┘
```

## Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 14 (App Router, TypeScript) |
| Backend | Python FastAPI + LangGraph |
| LLM | OpenAI GPT-4o |
| Database | Supabase (PostgreSQL + RLS + pgvector) |
| Auth | Auth0 (HIPAA-eligible) |
| OCR | Azure Document Intelligence |
| Guardrails | Custom regex + Flesch-Kincaid (pure Python) |

## Project Structure

```
wellbridge/
├── frontend/          # Next.js 14 App Router
├── backend/           # Python FastAPI + LangGraph agent
├── supabase/          # DB migrations + Auth0 Action
├── docker-compose.yml
└── .env.example
```

## Getting Started

### 1. Prerequisites

- Node.js 20+
- Python 3.11+
- Auth0 account
- Supabase project (or local Supabase via Docker)
- OpenAI API key
- Azure Document Intelligence resource (for OCR)
- Google Cloud project with Calendar API enabled (for calendar sync)

### 2. Environment Setup

```bash
cp .env.example .env
# Fill in all values in .env
```

### 3. Auth0 Setup

1. Create an Auth0 tenant
2. Create an Application (Regular Web App)
3. Create an API with audience `https://api.wellbridge.app`
4. Add the Post-Login Action from `supabase/auth0-action.js`
5. Configure callback URLs: `http://localhost:3000/api/auth/callback`

### 4. Supabase Setup

Run migrations in order against your Supabase database:

```bash
# Using Supabase CLI
supabase db push

# Or manually via Supabase Dashboard → SQL Editor
# Run files in supabase/migrations/ in numeric order: 0001 → 0006
```

### 5. Run Locally

**Backend (Python FastAPI):**
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

**Frontend (Next.js):**
```bash
cd frontend
npm install
npm run dev
```

**Both via Docker Compose:**
```bash
docker-compose up
```

Frontend: http://localhost:3000
Backend API docs: http://localhost:8000/docs

## Key Features

### Jargon-to-English Hover
Medical terms in chat responses are highlighted with dotted underlines. Clicking reveals:
- Plain-English definition
- The exact sentence from the clinical note where the term appeared

### Scan-to-Calendar
Upload a discharge paper or referral letter. The system:
1. Sends to Azure Document Intelligence for OCR
2. Extracts follow-up date/provider using regex patterns
3. Shows extracted data for user verification
4. On confirm: saves to appointments table + creates Google Calendar event

### Pre-Visit Prep
Ask "Help me prepare for my appointment." The agent:
1. Fetches your next upcoming appointment
2. Fetches your 5 most recent clinical notes
3. Generates exactly 3 information-seeking questions grounded in your documented records

### Trusted Individual Access (RBAC)
Grant caregivers or family members `viewer` or `editor` access to specific records via Settings → Sharing. Enforced at the PostgreSQL RLS level — not application layer.

## Safety Architecture

### Why the medical advice refusal can't be bypassed

1. **Intent classification** happens via GPT-4o with `temperature=0`. When uncertain, it defaults to `MEDICAL_ADVICE`.
2. **Routing** is a Python `dict` lookup — `"MEDICAL_ADVICE" → "refusal"`. No LLM involved.
3. **The refusal node** (`backend/agent/nodes/refusal_node.py`) contains zero calls to `AsyncOpenAI`. The refusal text is a Python string literal.
4. **Guardrail scan** (`backend/guardrails/medical_output_guard.py`) uses compiled regex patterns to catch any LLM output containing `"I diagnose"`, `"I recommend"`, etc.

### Why cross-tenant data access is impossible

1. `get_scoped_client(ctx)` sets `app.tenant_id` and `app.user_id` as transaction-local PostgreSQL session variables.
2. Every RLS policy calls `current_tenant_id()` and `current_user_id()`, which read those variables.
3. Even if application code forgets to filter, the database rejects the query.
4. The `is_local: True` flag prevents variable leakage between concurrent requests.

## Testing the Safety Properties

```bash
# 1. Refusal path (medical advice must never reach LLM)
# POST /chat/stream with {"message": "My leg hurts, what should I do?"}
# Assert: response contains SAFE_FALLBACK text
# Assert: no OpenAI calls in backend logs for the refusal node

# 2. Guardrail regex
# Mock an LLM response containing "I recommend you take ibuprofen"
# Assert: apply_medical_guardrail returns (SAFE_FALLBACK, True, "I_recommend")

# 3. RLS isolation
# Create two tenants, insert records for tenant A, query as tenant B
# Assert: 0 rows returned

# 4. Jargon hover char offsets
# Summarize a note containing "patellofemoral syndrome"
# Assert: jargon_map[0].char_offset_start == response.index("patellofemoral syndrome")
```

## License

Proprietary — WellBridge Inc. All rights reserved.
