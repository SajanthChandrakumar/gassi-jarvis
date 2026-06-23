"""
Gassi-Jarvis — Vision Module (Project Argus)

Handles taking macOS screenshots and compressing them for Gemini Vision.
"""
import os
import io
import subprocess
import tempfile
from PIL import Image

def capture_and_compress_screen() -> bytes:
    """
    Takes a silent screenshot of the macOS desktop, compresses it heavily,
    and returns the JPEG bytes.

    Raises:
        PermissionError if macOS screen recording permissions are missing.
        FileNotFoundError if the temporary screenshot file was not created.
    """
    # mkstemp returns an exclusively-created file with a random name, so a
    # symlink planted at a predictable path can't redirect the screenshot write.
    fd, tmp_path = tempfile.mkstemp(prefix="jarvis_vision_", suffix=".png")
    os.close(fd)

    try:
        # -x: silent (no shutter sound)
        subprocess.run(
            ["screencapture", "-x", tmp_path],
            capture_output=True,
            text=True,
            check=True
        )
    except subprocess.CalledProcessError as e:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise PermissionError(
            "Fehler beim Erstellen des Screenshots. Bitte überprüfe die "
            "macOS-Berechtigungen für 'Bildschirmaufnahme' (Screen Recording) "
            "für dein Terminal oder deine IDE."
        ) from e

    if not os.path.exists(tmp_path):
        raise FileNotFoundError(
            "Screenshot konnte nicht gespeichert werden."
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
