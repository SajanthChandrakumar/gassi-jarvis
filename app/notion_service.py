import os
import requests # <-- NEU: Unser direkter HTTP-Client
from datetime import datetime
from notion_client import Client
from dotenv import load_dotenv

load_dotenv()
notion = Client(auth=os.getenv("NOTION_API_KEY"))
database_id = os.getenv("NOTION_PAGE_ID")

def save_protocol_to_notion(title: str, content: str, category: str) -> bool:
    """
    Erstellt einen strukturierten Eintrag in der Notion-Datenbank.
    """
    try:
        if not database_id:
            print("[WARN] Notion Page ID fehlt!")
            return False

        heute_iso = datetime.now().isoformat()

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
    Durchsucht die Notion-Datenbank. Holt immer die neuesten Einträge zuerst.
    """
    try:
        if not database_id:
            return "Fehler: Notion Page ID fehlt!"

        api_key = os.getenv("NOTION_API_KEY")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28"
        }
        
        url = f"https://api.notion.com/v1/databases/{database_id}/query"
        
        # 1. Die Sortierung (Immer das Neueste zuerst!)
        payload = {
            "sorts": [{"timestamp": "created_time", "direction": "descending"}]
        }

        # 2. Die Filter (nur hinzufügen, wenn Jarvis wirklich was sucht)
        filters = {"and": []}
        if query_text:
            filters["and"].append({"property": "Inhalt", "rich_text": {"contains": query_text}})
        if category:
            filters["and"].append({"property": "Kategorie", "multi_select": {"contains": category}})

        if filters["and"]:
            payload["filter"] = filters

        # API Request abfeuern
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code != 200:
            print(f"[ERROR] Raw API Fehler: {response.text}")
            return f"Fehler bei der Datenbank-Suche: Code {response.status_code}"

        results = response.json()
        
        if not results.get("results"):
            return "Das Gedächtnis ist leer oder es wurde nichts Passendes gefunden."

        # Token sparen: Wir holen nur die letzten 3 Einträge
        formatted_results = []
        for page in results["results"][:3]: 
            props = page.get("properties", {})
            
            title_prop = props.get("Name", {}).get("title", [])
            title = title_prop[0]["text"]["content"] if title_prop else "Ohne Titel"
            
            content_prop = props.get("Inhalt", {}).get("rich_text", [])
            content = content_prop[0]["text"]["content"] if content_prop else ""
            
            cat_prop = props.get("Kategorie", {}).get("multi_select", [])
            cat = cat_prop[0].get("name", "Keine") if cat_prop else "Keine"
            
            formatted_results.append(f"- [{cat}] {title}: {content}")

        return "Hier sind die neuesten/passenden Notizen aus deinem Gedächtnis:\n" + "\n".join(formatted_results)

    except Exception as e:
        print(f"[ERROR] Eigener Search API Fehler: {e}")
        return f"Fehler bei der Datenbank-Suche: {str(e)}"
    except Exception as e:
        print(f"[ERROR] Eigener Search API Fehler: {e}")
        return f"Fehler bei der Datenbank-Suche: {str(e)}"