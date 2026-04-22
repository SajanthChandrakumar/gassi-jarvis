import os
from notion_client import Client
from dotenv import load_dotenv

load_dotenv()
notion = Client(auth=os.getenv("NOTION_API_KEY"))
database_id = os.getenv("NOTION_PAGE_ID")

def web_search(query: str) -> str:
    """
    Durchsucht das Live-Internet nach aktuellen News, Kursen (Bitcoin, Aktien),
    Wetter oder Fakten, die du nicht auswendig weißt.
    Nutze dies IMMER, bevor du sagst, dass du etwas nicht weißt!
    """
    print(f"[AGENT] Websuche gestartet: {query}")
    try:
        results = DDGS().text(query, max_results=3)
        if not results:
            return "Keine aktuellen Informationen im Internet gefunden."

        # Wir formatieren die Top 3 Ergebnisse als sauberen Text für Jarvis
        formatted_results = []
        for r in results:
            formatted_results.append(f"- {r.get('title')}: {r.get('body')}")

        return "Web-Ergebnisse:\n" + "\n".join(formatted_results)
    except Exception as e:
        print(f"[ERROR] Websuche fehlgeschlagen: {e}")
        return f"Fehler bei der Websuche: {str(e)}"

def save_protocol_to_notion(title: str, content: str, category: str) -> bool:
    """
    Erstellt einen strukturierten Eintrag in der Notion-Datenbank.
    """
    try:
        if not database_id:
            print("[WARN] Notion Page ID fehlt!")
            return False

        notion.pages.create(
            parent={"database_id": database_id},
            properties={
                "Name": {
                    "title": [{"text": {"content": title}}]
                },

                "Kategorie": {
                    "multi_select": [{"name": category}]
                },

                "Inhalt": {
                    "rich_text": [{"text": {"content": content}}]
                },

                "Date": {
                    "date": {"start": heute_iso}
                }
            }
        )

        return True
    except Exception as e:
        print(f"[ERROR] Notion API Fehler beim Speichern: {e}")
        return False

def search_notion_memory(query_text: str = "", category: str = "") -> str:
    """
    Durchsucht die Notion-Datenbank nach einem Suchbegriff und/oder Kategorie.
    """
    try:
        if not database_id:
            return "Fehler: Notion Page ID fehlt!"

        filters = {"and": []}

        if query_text:
            filters["and"].append({
                "property": "Inhalt",
                "rich_text": {"contains": query_text}
            })

        # FIX 2: Auch die Suchanfrage muss auf multi_select angepasst werden
        if category:
            filters["and"].append({
                "property": "Kategorie",
                "multi_select": {"contains": category}
            })

        if not filters["and"]:
            return "Fehler: Es muss ein Suchbegriff oder eine Kategorie übergeben werden."

        # Durch den Downgrade auf Version 2.x funktioniert dieser Befehl wieder!
        results = notion.databases.query(database_id=database_id, filter=filters)

        if not results["results"]:
            return "Keine passenden Einträge in Notion gefunden."

        formatted_results = []
        for page in results["results"]:
            title_prop = page["properties"].get("Name", {}).get("title", [])
            title = title_prop[0]["text"]["content"] if title_prop else "Ohne Titel"

            content_prop = page["properties"].get("Inhalt", {}).get("rich_text", [])
            content = content_prop[0]["text"]["content"] if content_prop else ""

            # FIX 3: Auslesen als Liste
            cat_prop = page["properties"].get("Kategorie", {}).get("multi_select", [])
            cat = cat_prop[0].get("name", "Keine") if cat_prop else "Keine"

            formatted_results.append(f"- [{cat}] {title}: {content}")

        return "Gefundene Notizen:\n" + "\n".join(formatted_results)

    except Exception as e:
        print(f"[ERROR] Notion Search API Fehler: {e}")
        return f"Fehler bei der Datenbank-Suche: {str(e)}"
