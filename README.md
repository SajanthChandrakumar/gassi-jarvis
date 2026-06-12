# Gassi-Jarvis (AI Strategic Assistant & LAM)

> **Vision:** Turning "dead time" during daily dog walks into high-performance strategy sessions.  
> An autonomous, voice-controlled AI sparring partner for dynamic Q&A, strategic discussions, and local macOS automation (Large Action Model approach).

---

## The Purpose

This project is a technical showcase of a modern AI-agent architecture. It bridges the gap between raw LLM reasoning and professional software engineering standards.

- **API Contract Design:** Strict JSON validation using Pydantic to ensure data integrity.  
- **Stateful AI & RAG:** Custom in-memory session management combined with a persistent ChromaDB vector store for long-term memory retrieval.  
- **Function Calling & LAM:** Autonomous execution of Python tools (Notion API, OS Commands) driven by the LLM.  
- **Layered Command Safety:** A Human-in-the-Loop (HitL) security router classifies every shell command by threat level, blocks reads from sensitive paths (SSH keys, `.env`, `.aws/credentials`, …), and gates anything destructive behind explicit voice approval.
- **Modern Stack:** Built on the Google Gemini infrastructure for high-speed reasoning and Edge-TTS for low-latency voice output.  

---

## System Architecture

The project follows a decoupled microservice architecture:
1. **Gateway & Controller (`main.py`)**: Manages the API lifecycle and HitL interception.
2. **LLM Orchestrator (`agent.py`)**: Gemini 2.5 integration, tool declarations, and NLP intent analysis.
3. **Session & RAG (`memory.py`)**: Local ChromaDB vector database and session state management.
4. **Security Router (`security.py`)**: Threat-level classification for sandboxed shell execution.
5. **Knowledge Base (`notion_service.py`)**: External Notion API integration.
6. **Vision Module (`vision.py`)**: macOS desktop screenshot capture and Pillow-based image compression for multimodal visual analysis.

For a deep dive, see the [Architecture Documentation](architecture.md).

---

## Tech Stack

- **Language:** Python 3.13  
- **Framework:** FastAPI / Uvicorn  
- **Validation:** Pydantic v2  
- **AI & NLP:** `google-genai`, `edge-tts`  
- **Vector Database:** `chromadb`  
- **Environment:** Homebrew managed Python environments on Apple Silicon (M-Series)  

---

## Initial Setup & Installation

### 1. Prepare your Mac (Homebrew & Python 3.13)

```bash
# Install Homebrew (if missing)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Stable Python 3.13
brew install python@3.13
```

### 2. Project Initialization

```bash
# Clone and enter the project
git clone https://github.com/SajanthChandrakumar/gassi-jarvis.git
cd gassi-jarvis

# Create a clean Virtual Environment with Python 3.13
python3.13 -m venv venv
source venv/bin/activate

# Upgrade Pip and install core dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Environment Variables

Create a `.env` file in the root directory:

```bash
GOOGLE_API_KEY=your_gemini_key
NOTION_API_KEY=your_notion_integration_secret
NOTION_PAGE_ID=your_database_id

# Optional: working directory for sandboxed shell execution.
# Defaults to the current user's $HOME. Point this at a scratch directory
# if you'd rather Jarvis never touch your home folder by default.
# JARVIS_SHELL_CWD=/Users/you/jarvis-sandbox
```

### 4. Fire up the Engine

```bash
uvicorn app.main:app --reload
```

Open: http://localhost:8000/docs  
Access the interactive Swagger UI and test the API contracts.

---

## API Contract (The "Jarvis" Protocol)

All communication happens via the `/api/chat` endpoint.

### Request Structure

```json
{
  "session_id": "unique_session_id",
  "timestamp": "2026-05-22T20:00:00Z",
  "payload": {
    "type": "text",
    "content": "Jarvis, ich bin Sajanth. Merke dir das."
  }
}
```

### Response Structure (with TTS)

```json
{
  "status": "success",
  "jarvis_response": "Verstanden. Ich habe mir das gemerkt.",
  "audio_base64": "UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIh...",
  "action_taken": "tool_call_save_memory"
}
```

---

## Project Roadmap

- [x] Phase 1: Setup FastAPI Gateway & Pydantic JSON validation  
- [x] Phase 2: Connect Gemini with In-Memory sessions  
- [x] Phase 3: Implement Voice-to-Text (STT) and Text-to-Voice (TTS) via Edge-TTS  
- [x] Phase 4: Notion API Integration for automated strategy protocols  
- [x] Phase 5: Persistent Long-Term Memory via local ChromaDB (RAG Pipeline)  
- [x] Phase 6: Refactor backend into modules and implement layered HitL Security Router for macOS execution (LAM)
- [x] Phase 7: Project Argus - Multimodal Vision capabilities (macOS screenshots & Gemini Vision integration)

---

## Next Sprints

- [ ] Sprint 1: Local Wake-Word Integration (Porcupine/Picovoice)  
- [ ] Sprint 2: Audio Streaming via WebSockets (Low Latency Interrupts)  
- [x] Sprint 3: The Kill-Switch (Interruptibility) - Frontend AbortController and UI state management for instant audio interruptions.
