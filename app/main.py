import os
import io 
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Dict, Any
from google import genai
from dotenv import load_dotenv
import base64
import edge_tts
from fastapi.responses import FileResponse
from app.notion_service import save_protocol_to_notion


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
    audio_base64: Optional[str] = None
    action_taken: Optional[str] = None

@app.get("/")
async def get_index():
    return FileResponse("app/static/index.html")

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
        # 1. Nachricht an die KI schicken
        response = chat_session.send_message(user_text)

        # 1.5 Notion-Trigger prüfen
        # Wenn der User "protokoll", "notier" oder "speicher" sagt, legen wir es in Notion ab.
        trigger_words = ["protokoll", "notier", "speicher", "festhalten"]
        if any(word in user_text.lower() for word in trigger_words):
            print("[LOG] Notion-Trigger erkannt! Speichere Protokoll...")
            save_protocol_to_notion(user_text, response.text)

        # 2. Text in realistische Sprache umwandeln (Edge-TTS)
        print("[LOG] Generiere Azure-Audio-Stream...")
        
        # 'de-DE-KillianNeural' männliche deutsche Stimme. 
        communicate = edge_tts.Communicate(response.text, "de-DE-KillianNeural")
        
        # Wir sammeln die Audio-Chunks direkt im Arbeitsspeicher
        audio_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]

        # 3. Das gesammelte Audio in Base64 umwandeln
        audio_b64 = base64.b64encode(audio_data).decode('utf-8')

        return JarvisResponse(
            status="success",
            jarvis_response=response.text,
            audio_base64=audio_b64,
            action_taken="gemini_api_call_with_edge_tts"
        )
    except Exception as e:
        print(f"[ERROR] Interner Fehler: {e}") 
        raise HTTPException(status_code=500, detail=f"Brain connection lost: {str(e)}")