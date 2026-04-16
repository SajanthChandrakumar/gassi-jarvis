import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Dict, Any
from google import genai
from dotenv import load_dotenv

# 1. API Setup & Authentifizierung
load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    raise ValueError("Kein GOOGLE_API_KEY in der .env gefunden!")

client = genai.Client(api_key=api_key)

app = FastAPI(title="Gassi-Jarvis Gateway")

# 2. In-Memory Memory
active_sessions: Dict[str, Any] = {}

class Payload(BaseModel):
    type: str
    content: str

class JarvisRequest(BaseModel):
    session_id: str
    timestamp: datetime
    payload: Payload

class JarvisResponse(BaseModel):
    status: str
    jarvis_response: str
    action_taken: Optional[str] = None

@app.post("/api/chat", response_model=JarvisResponse)
async def chat_with_jarvis(request: JarvisRequest):
    user_text = request.payload.content.strip()
    session_id = request.session_id
    
    if not user_text:
        raise HTTPException(status_code=400, detail="Payload content darf nicht leer sein.")

    print(f"[LOG] Session {session_id} sagt: {user_text}")

    if session_id not in active_sessions:
        print(f"[LOG] Erstelle neue Memory-Session für: {session_id}")
        system_instruction = "Du bist Jarvis, ein kritischer Senior-Developer und Sparring-Partner. Antworte in 1-2 Sätzen."
        
        active_sessions[session_id] = client.chats.create(
            model="gemini-2.5-flash",
            config=genai.types.GenerateContentConfig(
                system_instruction=system_instruction,
            )
        )

    chat_session = active_sessions[session_id]
    
    try:
        response = chat_session.send_message(user_text)
        return JarvisResponse(
            status="success",
            jarvis_response=response.text,
            action_taken="gemini_api_call"
        )
    except Exception as e:
        print(f"[ERROR] API Call fehlgeschlagen: {e}")
        raise HTTPException(status_code=500, detail="Brain connection lost.")