"""
Gassi-Jarvis — Vision Module (Project Argus)

Handles taking macOS screenshots and compressing them for Gemini Vision.
"""
import os
import io
import subprocess
from PIL import Image

def capture_and_compress_screen() -> bytes:
    """
    Takes a silent screenshot of the macOS desktop, compresses it heavily,
    and returns the JPEG bytes.
    
    Raises:
        PermissionError if macOS screen recording permissions are missing.
        FileNotFoundError if the temporary screenshot file was not created.
    """
    tmp_path = "/tmp/jarvis_vision.png"
    
    try:
        # -x: silent (no shutter sound)
        subprocess.run(
            ["screencapture", "-x", tmp_path],
            capture_output=True,
            text=True,
            check=True
        )
    except subprocess.CalledProcessError as e:
        raise PermissionError(
            "Fehler beim Erstellen des Screenshots. Bitte überprüfe die "
            "macOS-Berechtigungen für 'Bildschirmaufnahme' (Screen Recording) "
            "für dein Terminal oder deine IDE."
        ) from e

    if not os.path.exists(tmp_path):
        raise FileNotFoundError(
            "Screenshot konnte nicht unter /tmp/jarvis_vision.png gespeichert werden."
        )

    # Compress using Pillow
    try:
        with Image.open(tmp_path) as img:
            # Convert to RGB to drop alpha channels (transparency)
            if img.mode != "RGB":
                img = img.convert("RGB")
            
            # Scale down to save tokens and latency
            img.thumbnail((1024, 1024))
            
            # Save to buffer as JPEG
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=75)
            
            return buffer.getvalue()
    finally:
        # Clean up temporary file
        try:
            os.remove(tmp_path)
        except OSError:
            pass
