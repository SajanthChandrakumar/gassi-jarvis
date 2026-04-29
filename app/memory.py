import chromadb
from datetime import datetime

# 1. Initialisiere den lokalen Speicher (erstellt automatisch einen Ordner auf deinem Mac)
chroma_client = chromadb.PersistentClient(path="./jarvis_brain")

# 2. Erstelle oder lade das Notizbuch (Collection)
collection = chroma_client.get_or_create_collection(name="long_term_memory")

def save_memory(text: str) -> str:
    """Speichert einen neuen Fakt oder eine Beobachtung ab."""
    # Wir generieren eine einzigartige ID basierend auf der Uhrzeit
    doc_id = f"mem_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    collection.add(
        documents=[text],
        metadatas=[{"timestamp": datetime.now().isoformat()}],
        ids=[doc_id]
    )
    print(f"[MEMORY] Gespeichert: {text}")
    return "Erinnerung erfolgreich im Langzeitgedächtnis verankert."

def recall_memory(query: str, n_results: int = 5) -> str:
    """Sucht nach den semantisch ähnlichsten Erinnerungen im Langzeitgedächtnis."""
    print(f"[MEMORY] Suche im Unterbewusstsein nach: {query}")
    results = collection.query(
        query_texts=[query],
        n_results=n_results
    )
    
    if not results['documents'] or not results['documents'][0]:
        return "Ich habe dazu absolut keine passenden Erinnerungen gefunden."
    
    # Wir bauen einen strukturierten Kontext-Block für das LLM
    formatted_memories = []
    for i in range(len(results['documents'][0])):
        text = results['documents'][0][i]
        meta = results['metadatas'][0][i]
        # Das LLM bekommt jetzt den Text PLUS den genauen Speicher-Zeitpunkt
        formatted_memories.append(f"- [{meta.get('timestamp')[:10]}] {text}")
        
    memory_block = "\n".join(formatted_memories)
    return f"Gefundene Erinnerungen (mit Datum):\n{memory_block}"

def get_memory_stats() -> str:
    """Gibt die Anzahl der gespeicherten Fragmente im Langzeitgedächtnis zurück."""
    count = collection.count()
    return f"Mein Langzeitgedächtnis umfasst aktuell {count} gespeicherte Wissensfragmente."