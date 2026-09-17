# Browser and API Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify the existing Jarvis PWA and API end to end and make explicit task-inbox prompts reliable when Gemini returns an empty response.

**Architecture:** Keep all existing LLM and deterministic research paths intact. Add one narrow fallback at the chat endpoint's empty-response boundary, backed by endpoint-level tests using the real inbox implementation and a temporary file.

**Tech Stack:** FastAPI, Pydantic v2, pytest, vanilla JavaScript PWA, Gemini, deterministic research providers.

**Spec:** `docs/superpowers/specs/2026-09-10-browser-api-readiness-audit.md`

## Global Constraints

- No financial recommendations, trading, portfolio actions, fabricated values, or LLM-calculated authoritative metrics.
- Preserve provenance, freshness, quality, missing values, and partial/failure warnings.
- Live verification uses temporary copies of user state.
- Do not trigger screenshots, microphone capture, or application opening without explicit consent.

---

### Task 1: Empty-response task fallback

**Files:**
- Modify: `app/main.py`
- Create: `tests/test_chat_task_fallback.py`

**Interfaces:**
- Consumes: `inbox.add_task(task: str) -> str`, `inbox.list_tasks() -> str`
- Produces: `_fallback_inbox_response(user_text: str) -> tuple[str, str] | None`

- [ ] **Step 1: Write endpoint regression tests**

Create an empty Gemini response fixture. Verify `List my open tasks.` returns
`action_taken == "task_list"`; verify `Merke als Aufgabe: Browser-Endpunkte
prüfen` returns `task_captured` and creates a checkbox in the temporary inbox;
verify an unrelated empty response keeps the generic fallback.

- [ ] **Step 2: Run the focused test and verify failure**

Run: `GOOGLE_API_KEY=test-only-key .venv/bin/python -m pytest -q tests/test_chat_task_fallback.py`

Expected: the two explicit task cases fail with `text_response` while the unrelated case passes.

- [ ] **Step 3: Implement the minimal fallback**

Add a small parser for explicit German/English task-list and task-capture
phrases. Invoke it only after Gemini produced neither a function call nor text.
Return the existing inbox functions' output and stable action names.

- [ ] **Step 4: Run the focused tests and verify success**

Run: `GOOGLE_API_KEY=test-only-key .venv/bin/python -m pytest -q tests/test_chat_task_fallback.py tests/test_inbox.py`

Expected: all focused tests pass.

### Task 2: Full automated verification

**Files:**
- Verify: `app/static/app.js`
- Verify: `deploy/launchd/com.gassi.jarvis.mac-agent.plist`
- Verify: `deploy/launchd/install.sh`
- Verify: `deploy/launchd/run-mac-agent.sh`

**Interfaces:**
- Consumes: repository test and static assets
- Produces: fresh test, JavaScript, plist, and shell validation evidence

- [ ] **Step 1: Run the complete isolated suite**

Run the full pytest suite with `GOOGLE_API_KEY=test-only-key` and all mutable
runtime paths redirected to `/private/tmp`.

- [ ] **Step 2: Validate non-Python artifacts**

Run `node --check app/static/app.js`, `plutil -lint` on the launchd plist, and
`sh -n` on both launchd shell scripts.

### Task 3: Live API and browser contract audit

**Files:**
- Verify: `app/main.py`
- Verify: `app/device/routes.py`
- Verify: `app/static/index.html`
- Verify: `app/static/app.js`

**Interfaces:**
- Consumes: local Uvicorn server with temporary state and real configured read-only providers
- Produces: endpoint matrix and user-facing browser verification notes

- [ ] **Step 1: Start isolated local server**

Use temporary Chroma, session, inbox, and device-database paths plus dedicated
local audit tokens on `127.0.0.1:8001`.

- [ ] **Step 2: Verify every OpenAPI route**

Check successful and expected error states for static assets, authentication,
memory, providers, macro context, all four research workflows, chat, and device
routes. Record partial/unavailable states without treating them as successes.

- [ ] **Step 3: Verify the visible PWA**

Exercise authorization, chat, research forms, structured results, watchlist,
saved research, export actions, clearing a session, responsive layout, and PWA
asset loading through the connected browser. Report any browser-control or
permission boundary explicitly.

### Task 4: Final evidence and documentation

**Files:**
- Modify if resolved: configured Jarvis Obsidian project note
- Verify: Git diff and status

**Interfaces:**
- Consumes: automated and live test evidence
- Produces: concise readiness matrix with remaining configuration and manual checks

- [ ] **Step 1: Inspect the final diff**

Confirm only the task fallback, its tests, and approved documentation changed.

- [ ] **Step 2: Re-run final focused verification**

Repeat the task prompts against the live server and confirm both actions and
temporary inbox side effects.

- [ ] **Step 3: Update project memory if the vault path is resolvable**

Append a credential-free summary of the material audit result and limitations.

- [ ] **Step 4: Report readiness**

Classify every feature as working, working with explicit limitations, not
configured, or not testable without user permission.
