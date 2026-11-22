## Architecture & Design Decisions

### 1. Division of Responsibility: AI vs. Deterministic Rules
- **AI Extraction (`GeminiReceiptExtractor`):** Parses unstructured receipt images and PDFs into structured fields when `Replay Mode` is off and external AI is enabled. Because LLMs can misread values or introduce ambiguity, extracted fields are treated as inputs to verify—not final authority.
- **Deterministic Rules (`MATH-001`, `DUP-001`, `FX-001`, `POL-001`):** Enforce repeatable, explainable checks for receipt math, duplicates (including cross-employee receipt reuse), currency conversion, and policy limits. They guarantee consistent behavior, clear audit explanations, and safe operation in `Replay Mode` or non-AI fallback.

### 2. Unsupervised Anomaly Detection (Isolation Forest)
- **Why Isolation Forest:** Real-world expense auditing lacks cleanly labeled fraud/violation datasets upfront and must adapt to unusual multi-signal combinations. Isolation Forest isolates outliers with shorter average path lengths in random trees, producing an anomaly/risk score alongside deterministic rule findings without requiring labeled training data.

### 3. Local Persistence & Auditability (SQLite + `AuditStore`)
- Stores expense decisions, baseline ledger records, and controller overrides locally in SQLite.
- Enforces an audit reason/note on disposition/approval overrides so every manual decision is traceable in the detail view and **Audit Log** tab.

### 4. PII Handling Boundary
- `mask_sensitive_text` in `services/intake.py` provides regex-based masking for card numbers (retaining the last 4 digits), email addresses, and phone numbers on text strings.
- Text-level masking does not redact sensitive pixels embedded inside raw receipt images or PDFs, and wiring text masking across all downstream text/chaser paths is tracked explicitly.

### 5. Why RAG Is Deferred to Production
- **Prototype Scope:** A vector database and RAG pipeline over multi-page policy documents adds chunking, embedding, retrieval tuning, and infrastructure complexity that is unnecessary for validating the core intake, deterministic rule, risk scoring, and controller override workflow.
- **Production Path:** For multi-page corporate policy handbooks with layered exceptions and regional rules, production should index policy sections as embeddings in a **vector database** and use **RAG** to retrieve grounded policy citations for controllers while keeping numeric validation, duplicate checks, and final approval workflows deterministic.