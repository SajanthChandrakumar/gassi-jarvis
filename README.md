# Gassi-Jarvis 🐕🧠 (AI Strategic Assistant)

> **Vision:** Turning "dead time" during daily dog walks into high-performance strategy sessions. 
> An autonomous, voice-controlled AI sparring partner for technical product management, architecture reviews, and career planning.

## 🎯 The "Unicorn" Purpose
This project serves as a technical showcase demonstrating the bridge between raw LLM reasoning and real-world system architecture. It highlights:
* **API Contract Design:** Strict JSON validation and discrepancy resolution.
* **Stateful AI Integration:** Custom in-memory session management for continuous conversation flows.
* **Modern Stack:** Built on the bleeding edge of Google's Gemini 2.5 infrastructure.

## 🏗 System Architecture (Layered Design)
The project is designed in a scalable, 5-layer architecture. **Currently implemented are Layer 2 (Gateway) and Layer 4 (Brain).**

1. **Layer 1: The Sensory System (Frontend)** - *[In Progress]* PWA for mobile voice streaming.
2. **Layer 2: The Gateway (Custom Backend)** - **[Active]** FastAPI server acting as the strict JSON contract validator and session manager.
3. **Layer 3: The Orchestrator (Agent)** - *[Planned]* OpenJarvis / LangChain for tool usage.
4. **Layer 4: The Brain (LLM Engine)** - **[Active]** Google `gemini-2.5-pro` with persistent chat history.
5. **Layer 5: Tools (External APIs)** - *[Planned]* Notion & Google Calendar integrations.

## 🚀 Tech Stack
* **Language:** Python 3.12
* **Framework:** FastAPI, Uvicorn, Pydantic (Strict Data Validation)
* **AI SDK:** `google-genai` (Official Google GenAI SDK)
* **Model:** `gemini-2.5-flash`

## ⚙️ Local Setup & Installation

1. **Clone the repository:**
   ```bash
   git clone [https://github.com/YOUR_USERNAME/gassi-jarvis.git](https://github.com/YOUR_USERNAME/gassi-jarvis.git)
   cd gassi-jarvis