import os
import io 
import base64
from datetime import datetime
import edge_tts
from datetime import datetime
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from google import genai
from google.genai import types
from dotenv import load_dotenv
from fastapi.responses import FileResponse
from ddgs import DDGS

# 1. Den Service importieren
from app.notion_service import save_protocol_to_notion, search_notion_memory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 2. Die Werkzeuge (Tools) definieren
def save_to_notion(title: str, content: str, category: str) -> str:
    """Speichert eine strukturierte Notiz in Notion."""
    print(f"[AGENT] Tool-Einsatz: {category} - {title}")
    success = save_protocol_to_notion(title, content, category)
    return f"Erfolgreich als {category} gespeichert." if success else "Fehler beim Speichern."

def search_notion(query: str, category: str) -> str:
    """Durchsucht das Notion-Gedächtnis nach alten Notizen, Ideen oder To-Dos."""
    print(f"[AGENT] Gedächtnis-Scan: Kategorie='{category}', Query='{query}'")
    return search_notion_memory(query, category)

def web_search(query: str) -> str:
    """
    Durchsucht das Live-Internet nach aktuellen News, Kursen (Bitcoin, Aktien),
    Wetter oder Fakten, die du nicht auswendig weißt.
    """
    print(f"[AGENT] Websuche gestartet: {query}")
    try:
        results = DDGS().text(query, max_results=3)
        if not results:
            return "Keine aktuellen Informationen im Internet gefunden."

        formatted_results = []
        for r in results:
            formatted_results.append(f"- {r.get('title')}: {r.get('body')}")

        return "Web-Ergebnisse:\n" + "\n".join(formatted_results)
    except Exception as e:
        print(f"[ERROR] Websuche fehlgeschlagen: {e}")
        return f"Fehler bei der Websuche: {str(e)}"

# 3. Server Setup
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

# 4. Routen
@app.get("/")
async def get_index():
    index_path = os.path.join(BASE_DIR, "static", "index.html")
    if not os.path.exists(index_path):
        return {"error": "index.html nicht im Ordner app/static gefunden!"}
    return FileResponse(index_path)

@app.post("/api/chat", response_model=JarvisResponse)
async def chat_with_jarvis(request: JarvisRequest):
    user_text = request.payload.content.strip()
    session_id = request.session_id
    
    if session_id not in active_sessions:
        print(f"[LOG] Erstelle neue AGENT-Session für: {session_id}")
        
        now = datetime.now()
        aktuelles_datum = now.strftime("%A, der %d. %B %Y")
        aktuelle_uhrzeit = now.strftime("%H:%M Uhr")

        system_instruction = (
            f"Du bist Jarvis, ein erfahrener Senior-Developer und Mentor. "
            f"HEUTE IST: {aktuelles_datum}, es ist {aktuelle_uhrzeit}. "
            "WERKZEUGE: "
            "1. Nutze 'save_to_notion' für Wissen oder Ideen. "
            "2. Nutze 'search_notion', wenn der User nach euren vergangenen Gesprächen fragt. "
            "3. Nutze 'web_search' für aktuelle Daten, Kurse, Wetter oder Fakten aus dem echten Internet. "
            "ANTWORT-REGELN: Sei direkt, professionell und erkläre Konzepte gut. Bestätige Werkzeug-Einsätze kurz."
        )

        active_sessions[session_id] = client.chats.create(
            model="gemini-2.5-flash",
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                tools=[save_to_notion, search_notion, web_search],
                temperature=0.3
            )
        )

    chat_session = active_sessions[session_id]
    
    current_history = chat_session.get_history()

    if len(current_history) > 10:
        print("[LOG] Token-Hygiene aktiv: Schneide alten Kontext ab.")
        chat_session._history = current_history[-4:]

    try:
        response = chat_session.send_message(user_text)

        print("[LOG] Generiere Audio-Stream...")
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