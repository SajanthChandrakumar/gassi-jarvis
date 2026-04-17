import os
from dotenv import load_dotenv
from google import genai

load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")

print(f"Teste Key (endet auf '{api_key[-4:]}')...")

try:
    client = genai.Client(api_key=api_key)
    models = client.models.list()
    
    print("\n✅ Key funktioniert! Du hast Zugriff auf folgende Modelle:")
    for m in models:
        # Wir filtern hier nach Modellen, die 'gemini' im Namen haben
        if "gemini" in m.name.lower():
            print(f"- {m.name}")
            
except Exception as e:
    print(f"\n❌ FEHLER: {e}")