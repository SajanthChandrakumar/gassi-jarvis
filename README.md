# Gassi-Jarvis 🐕🧠 (AI Strategic Assistant)

> **Vision:** Turning "dead time" during daily dog walks into high-performance strategy sessions. 
> An autonomous, voice-controlled AI sparring partner for dynamic Q&A and strategic discussions.

## 🎯 The "Unicorn" Purpose
This project is a technical showcase of a modern AI-agent architecture. It bridges the gap between raw LLM reasoning and professional software engineering standards.
* **API Contract Design:** Strict JSON validation using Pydantic to ensure data integrity.
* **Stateful AI Integration:** Custom in-memory session management to maintain context during 60-minute walk sessions.
* **Modern Stack:** Built on the latest Google Gemini 2.5 infrastructure for high-speed reasoning.

## 🏗 System Architecture
The project follows a decoupled 5-layer architecture. 

1. **Layer 1: Sensory (Frontend)** - *[In Progress]* Voice-first mobile interface.
2. **Layer 2: Gateway (Backend)** - **[Active]** FastAPI server for validation and session routing.
3. **Layer 3: Orchestrator (Agent)** - *[Planned]* Advanced tool-calling and planning logic.
4. **Layer 4: Brain (LLM)** - **[Active]** `gemini-2.5-flash` with dedicated system instructions.
5. **Layer 5: Tools (External)** - *[Planned]* Notion, Calendar, and Slack integrations.

## 🚀 Tech Stack
* **Language:** Python 3.12
* **Framework:** FastAPI / Uvicorn
* **Validation:** Pydantic v2
* **AI SDK:** `google-genai` (Official Google SDK)
* **Environment:** Homebrew managed Python environments

## ⚙️ Initial Setup & Installation (Full Guide)

### 1. Prepare your Mac (Homebrew & Python 3.12)
If you don't have the correct Python version or Package Manager, run these commands:

```bash
# Install Homebrew (if missing)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Stable Python 3.12
brew install python@3.12
```

### 2.Project Initialization
```bash
# Clone and enter the project
git clone https://github.com/YOUR_USERNAME/openjarvis.git
cd openjarvis

# Create a clean Virtual Environment with Python 3.12
python3.12 -m venv venv
source venv/bin/activate

# Upgrade Pip and install core dependencies
pip install --upgrade pip
pip install fastapi uvicorn pydantic google-genai python-dotenv
```

### 3.Fire up the Engine
```bash
uvicorn main:app --reload
```

Open http://localhost:8000/docs to access the interactive Swagger UI and test the API contracts.

## 🔌 API Contract (The "Jarvis" Protocol)
All communication happens via the /api/chat endpoint.

Request Structure: 
JSON
```json
{
  "session_id": "unique_session_id",
  "timestamp": "2026-04-16T20:00:00Z",
  "payload": {
    "type": "text",
    "content": "Jarvis, ich bin Sajanth. Merke dir das."
  }
}
```

Response Structure:
JSON
```json
{
  "status": "success",
  "jarvis_response": "Sajanth. Verstanden. Fokus auf die Strategie.",
  "action_taken": "gemini_api_call"
}
```

## 🗺️ Project Roadmap
[x] Phase 1: Setup FastAPI Gateway & Pydantic JSON validation.

[x] Phase 2: Connect gemini-2.5-pro with In-Memory Memory sessions.

[ ] Phase 3: Implement Voice-to-Text (STT) and Text-to-Voice (TTS) streams.

[ ] Phase 4: Containerization with Docker for cloud deployment.

[ ] Phase 5: Notion API Integration for automated strategy protocols.
