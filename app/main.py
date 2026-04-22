import os
import io 
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Dict, Any
from google import genai
from google.genai import types # WICHTIG: Für die Config und System-Instructions
from dotenv import load_dotenv
import base64
import edge_tts
from fastapi.responses import FileResponse

# 1. Den Service importieren
from app.notion_service import save_protocol_to_notion

# 2. Das Werkzeug (Tool) als Wrapper definieren
def save_to_notion(content_to_save: str) -> str:
    """
    Speichert eine Information im Notion-Protokoll.
    
    Args:
        content_to_save: Die zu speichernde Information. MUSS zwingend als saubere, professionelle 
                         Zusammenfassung in Stichpunktform formuliert sein. Filtere jeglichen 
                         Smalltalk heraus. Keine wörtliche Rede des Users kopieren.
    """
    print(f"[AGENT] Führe Tool aus: save_to_notion mit Inhalt:\n{content_to_save}")
    success = save_protocol_to_notion("Jarvis (Auto-Notiz)", content_to_save)
    return "Erfolgreich in Notion gespeichert" if success else "Fehler beim Speichern"

load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    raise ValueError("Kein GOOGLE_API_KEY in der .env gefunden!")

client = genai.Client(api_key=api_key)
app = FastAPI(title="Gassi-Jarvis Gateway")

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
        print(f"[LOG] Erstelle neue AGENT-Session für: {session_id}")
        
        # FIX: Hier war die Einrückung vorher verschoben
        system_instruction = (
            "Du bist Jarvis, ein kritischer Sparring-Partner. "
            "Du analysierst die Aussagen des Users scharf und präzise. "
            "REGELN FÜR WERKZEUGE: Nutze 'save_to_notion' NUR, wenn eine echte Erkenntnis, "
            "eine Idee oder ein To-Do vorliegt. Nutze es NICHT für Begrüßungen oder Smalltalk. "
            "ANTWORT-STIL: Antworte maximal in 2-3 Sätzen. Wenn du etwas gespeichert hast, "
            "bestätige es mit einem kurzen, trockenen Kommentar."
        )
        
        # 3. Den Agenten mit seinen Werkzeugen instanziieren
        active_sessions[session_id] = client.chats.create(
            model="gemini-2.0-flash", # Hinweis: Achte darauf, dass der Modellname korrekt ist (meist 2.0 statt 2.5)
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                tools=[save_to_notion], # <-- Hier übergeben wir Jarvis seine Hände
                temperature=0.4 # Niedrige Temperatur: ist präzise
            )
        )

    chat_session = active_sessions[session_id]
    
    try:
        # 4. Magie: Das SDK prüft jetzt automatisch, ob das Tool aufgerufen werden muss
        response = chat_session.send_message(user_text)

        print("[LOG] Generiere Azure-Audio-Stream...")
        communicate = edge_tts.Communicate(response.text, "de-DE-KillianNeural")
        
        audio_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]

        audio_b64 = base64.b64encode(audio_data).decode('utf-8')

        return JarvisResponse(
            status="success",
            jarvis_response=response.text,
            audio_base64=audio_b64,
            action_taken="agent_call_completed"
        )
    except Exception as e:
        print(f"[ERROR] Interner Fehler: {e}") 
        raise HTTPException(status_code=500, detail=f"Brain connection lost: {str(e)}")