import os
from notion_client import Client
from datetime import datetime

def save_protocol_to_notion(user_text: str, jarvis_text: str):
    """Speichert einen Dialog als sauberes Protokoll in Notion."""
    
    notion_key = os.getenv("NOTION_API_KEY")
    page_id = os.getenv("NOTION_PAGE_ID")
    
    if not notion_key or not page_id:
        print("[WARN] Notion Credentials fehlen in der .env!")
        return False

    # Notion Client initialisieren
    notion = Client(auth=notion_key)
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    
    try:
        # Wir hängen neue Blöcke (Text, Überschriften) an deine existierende Seite an
        notion.blocks.children.append(
            block_id=page_id,
            children=[
                {
                    "object": "block",
                    "type": "heading_3",
                    "heading_3": {
                        "rich_text": [{"type": "text", "text": {"content": f"💡 Protokoll: {now}"}}]
                    }
                },
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {"type": "text", "text": {"content": "Du: "}, "annotations": {"bold": True}},
                            {"type": "text", "text": {"content": user_text}}
                        ]
                    }
                },
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {"type": "text", "text": {"content": "Jarvis: "}, "annotations": {"bold": True}},
                            {"type": "text", "text": {"content": jarvis_text}}
                        ]
                    }
                },
                {
                    "object": "block",
                    "type": "divider",
                    "divider": {}
                }
            ]
        )
        print("[LOG] Erfolgreich in Notion gespeichert!")
        return True
    except Exception as e:
        print(f"[ERROR] Notion API Fehler: {e}")
        return False