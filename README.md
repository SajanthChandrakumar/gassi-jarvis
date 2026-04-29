# Gassi-Jarvis 🐕🧠 (AI Strategic Assistant & LAM)

> **Vision:** Turning "dead time" during daily dog walks into high-performance strategy sessions.  
> An autonomous, voice-controlled AI sparring partner for dynamic Q&A, strategic discussions, and local macOS automation (Large Action Model approach).

---

## 🎯 The Purpose

This project is a technical showcase of a modern AI-agent architecture. It bridges the gap between raw LLM reasoning and professional software engineering standards.

- **API Contract Design:** Strict JSON validation using Pydantic to ensure data integrity.  
- **Stateful AI & RAG:** Custom in-memory session management combined with a persistent ChromaDB vector store for long-term memory retrieval.  
- **Function Calling:** Autonomous execution of Python tools (Notion API, OS Commands, Web Search) driven by the LLM.  
- **Modern Stack:** Built on the Google Gemini infrastructure for high-speed reasoning and Edge-TTS for low-latency voice output.  

---

## 🏗 System Architecture

The project follows a decoupled 5-layer architecture:

1. **Layer 1: Sensory (Frontend)** - **[Active]** Voice-first HTML/JS mobile interface with Chat-Fallback and UI state management.  
2. **Layer 2: Gateway (Backend)** - **[Active]** FastAPI server for validation, TTS generation, and session routing.  
3. **Layer 3: Orchestrator (Agent)** - **[Active]** Advanced tool-calling and planning logic using GenAI's function declarations.  
4. **Layer 4: Brain (LLM)** - **[Active]** `gemini-2.5-pro` (or flash) with strict, proactive system instructions.  
5. **Layer 5: Tools & Storage** - **[Active]** Notion API for protocolling, ChromaDB for the "Subconscious", macOS `osascript` for local control.  

---

## 🚀 Tech Stack

- **Language:** Python 3.12  
- **Framework:** FastAPI / Uvicorn  
- **Validation:** Pydantic v2  
- **AI & NLP:** `google-genai`, `edge-tts`  
- **Vector Database:** `chromadb`  
- **Environment:** Homebrew managed Python environments on Apple Silicon (M-Series)  

---

## ⚙️ Initial Setup & Installation (Full Guide)

### 1. Prepare your Mac (Homebrew & Python 3.12)

~~~
# Install Homebrew (if missing)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Stable Python 3.12
brew install python@3.12
~~~

### 2. Project Initialization

~~~
# Clone and enter the project
git clone https://github.com/YOUR_USERNAME/openjarvis.git
cd openjarvis

# Create a clean Virtual Environment with Python 3.12
python3.12 -m venv venv
source venv/bin/activate

# Upgrade Pip and install core dependencies
pip install --upgrade pip
pip install fastapi uvicorn pydantic google-genai python-dotenv chromadb edge-tts
~~~

### 3. Environment Variables

~~~
GOOGLE_API_KEY=your_gemini_key
NOTION_API_KEY=your_notion_integration_secret
NOTION_DATABASE_ID=your_database_id
~~~

### 4. Fire up the Engine

~~~
uvicorn app.main:app --reload
~~~

Open: http://localhost:8000/docs  
Access the interactive Swagger UI and test the API contracts.

---

## 🔌 API Contract (The "Jarvis" Protocol)

All communication happens via the `/api/chat` endpoint.

### Request Structure

~~~
{
  "session_id": "unique_session_id",
  "timestamp": "2026-04-16T20:00:00Z",
  "payload": {
    "type": "text",
    "content": "Jarvis, ich bin Sajanth. Merke dir das."
  }
}
~~~

### Response Structure (with TTS)

~~~
{
  "status": "success",
  "jarvis_response": "Verstanden. Ich habe mir das gemerkt.",
  "audio_base64": "UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIh...",
  "action_taken": "tool_call_save_memory"
}
~~~

---

## 🗺️ Project Roadmap

- [x] Phase 1: Setup FastAPI Gateway & Pydantic JSON validation  
- [x] Phase 2: Connect Gemini with In-Memory sessions  
- [x] Phase 3: Implement Voice-to-Text (STT) and Text-to-Voice (TTS) via Edge-TTS  
- [x] Phase 4: Notion API Integration for automated strategy protocols  
- [x] Phase 5: Persistent Long-Term Memory via local ChromaDB (RAG Pipeline)  

---

## 🚧 Next Sprints

- [ ] Sprint 1: Local Wake-Word Integration (Porcupine)  
- [ ] Sprint 2: Audio Streaming via WebSockets  
- [ ] Sprint 3: macOS Automation via AppleScript & Python  
