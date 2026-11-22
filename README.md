# Clearline — Corporate Spend & Policy Auditor

Clearline is a Streamlit-based expense and policy auditing workspace for Finance Controllers. It prioritizes flagged expenses in a synchronized triage queue and pairs **receipt preview**, **plain-language review findings**, **detailed checks**, **controller decision controls with required audit notes**, and **local SQLite audit logging**.

---

## Key Features

- **Spend Compliance Queue:** Search, filter, and sort expenses by exception status, priority, amount, or risk score, with synchronized selection between the queue and detail inspector.
- **Deterministic Policy & Risk Pipeline:** Evaluates receipt arithmetic (`MATH-001`), duplicate receipts/transactions (`DUP-001`, including cross-employee duplicate validation), currency conversion (`FX-001`), and spend/policy rules (`POL-001`) alongside unsupervised anomaly scoring (`Isolation Forest`) and follow-up drafts.
- **Execution Modes (`Replay Mode` vs. `External AI` vs. Non-AI Fallback):**
  - **Replay Mode:** Uses offline sample fixtures without calling external AI for reproducible reviews and UI/rule verification.
  - **External AI (Gemini):** Extracts structured receipt fields from uploaded PDFs and images when `Replay Mode` is off and external AI is enabled, then routes results through deterministic validation, policy, and risk checks.
  - **Non-AI Fallback:** Bypasses external AI calls when disabled and routes unverified or missing receipt fields safely for controller review.
- **Controller Overrides & Audit Log:** Requires an **Audit note** before saving queue status or approval changes, persisting every override in local SQLite and displaying history in both the detail inspector and the **Audit Log** tab.
- **Baseline Ledger Seeding:** Initializes the local SQLite database and seeds baseline expense records on startup, with a **Seed Baseline Ledger** button in the sidebar.

---

## Architecture & Design Decisions

- **AI Extraction vs. Deterministic Rules:** `GeminiReceiptExtractor` extracts structured fields from unstructured receipts when enabled, but AI outputs are treated as inputs to verify rather than final authority. Deterministic rules (`MATH-001`, `DUP-001`, `FX-001`, `POL-001`) handle repeatable math, cross-employee duplicate detection, currency conversion, and policy checks with clear auditability—and work even in `Replay Mode` or non-AI fallback.
- **Unsupervised Anomaly Scoring (`Isolation Forest`):** Complements deterministic rules by flagging unusual multi-signal patterns without requiring labeled fraud data upfront.
- **Local SQLite Persistence (`AuditStore`):** Keeps expense records, baseline ledger history, and controller override logs (with mandatory audit notes) local, simple, and self-contained.
- **PII Masking (`mask_sensitive_text`):** Uses regex masking in `services/intake.py` for text patterns (card numbers keeping the last 4 digits, emails, and phone numbers); it operates on text rather than redacting pixels inside raw receipt images or PDFs.
- **Why RAG Is Deferred to Production:** This prototype avoids vector database and RAG infrastructure to stay focused and fast to run locally. For production deployments with multi-page policy documents and layered exceptions, indexing policy clauses as embeddings in a vector DB with RAG is the planned next step alongside deterministic checks.

---

## Project Structure

```text
clearline/
├── app.py                      # Main Streamlit app, sidebar toggles, intake/submission form, tabs
├── config.py                   # Paths (DB_FILE, LEDGER_FILE, SAMPLES_DIR) & runtime settings
├── requirements.txt            # Python dependencies
├── .env.example                # Example environment variables (e.g., GEMINI_API_KEY)
├── .gitignore                  # Ignores virtualenvs, caches, .env, and local DB artifacts
├── README.md                   # Project overview, architecture, structure, and setup/run guide
├── writeup.md                  # Product & engineering summary
│
├── models/
│   ├── __init__.py
│   └── domain.py               # DecisionRecord, ExtractedReceipt, Finding, Disposition, ApprovalStatus, ControllerOverride
│
├── persistence/
│   ├── __init__.py
│   └── store.py                # SQLite AuditStore, schema setup, baseline seeding, override log
│
├── services/
│   ├── __init__.py
│   ├── pipeline.py             # End-to-end expense review orchestration
│   ├── intake.py               # File validation, size/page/dimension checks, SHA-256 hashing, PII masking
│   ├── extraction.py           # Receipt extraction (Replay fixtures, Gemini API, non-AI fallback)
│   ├── validation.py           # Receipt financial & arithmetic validation
│   ├── policy_engine.py        # Spend & policy rule evaluation
│   ├── risk_engine.py          # Duplicate detection & anomaly/risk scoring
│   └── decision_engine.py      # Disposition, approval status, summary & follow-up drafting
│
├── ui/
│   ├── __init__.py
│   ├── styles.py               # High-contrast theme, badges, cards, button/input/uploader styles
│   ├── queue_view.py           # KPI strip, search/filter/sort controls, and queue cards
│   └── detail_view.py          # Receipt preview, review findings, full-width checks & controller decision, technical JSON
│
├── data/
│   ├── baseline_ledger.csv     # Baseline expense records for duplicate & historical checks
│   └── samples/                # Sample receipt files (PDF, PNG, JPG, JPEG)
│
└── tests/                      # Unit & integration tests
    └── test_pipeline.py

```

---

## How to Run Locally

### 1. Create a Virtual Environment

```bash
cd clearline
python3 -m venv .venv
source .venv/bin/activate

```

On Windows (PowerShell):

```powershell
cd clearline
python -m venv .venv
.venv\Scripts\Activate.ps1

```

### 2. Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt

```

### 3. Configure Environment Variables (Optional for Live Gemini Extraction)

Export your Gemini API key in your shell (or set it in `.env` if your config loads `.env`):

```bash
export GEMINI_API_KEY="your_gemini_api_key_here"

```

On Windows (PowerShell):

```powershell
$env:GEMINI_API_KEY="your_gemini_api_key_here"

```

*(You can run the app without `GEMINI_API_KEY` by enabling **Replay Mode** in the sidebar or using the non-AI fallback.)*

### 4. Start the Streamlit App

```bash
streamlit run app.py

```

Open the local URL shown in the terminal (usually `http://localhost:8501`) in your browser.

### 5. Run Tests (Optional)

```bash
pytest

```

```

```