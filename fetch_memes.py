import os
import io
import zipfile
import requests
from pathlib import Path

MEME_DIR = Path("memes")
URL = os.getenv("FETCH_MEMES_URL", "").strip()
VALID_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

def main():
    if not URL:
        print("ERROR: FETCH_MEMES_URL fehlt (Config Var).")
        return

    MEME_DIR.mkdir(parents=True, exist_ok=True)

    print(f"INFO: Lade Memes von {URL} ...")
    r = requests.get(URL, timeout=60)
    r.raise_for_status()

    buf = io.BytesIO(r.content)
    copied = 0
    with zipfile.ZipFile(buf) as z:
        for zi in z.infolist():
            if zi.is_dir():
                continue
            name = Path(zi.filename).name
            ext = Path(name).suffix.lower()
            if ext not in VALID_EXT:
                continue
            data = z.read(zi)
            # max 8 MB pro Datei
            if len(data) > 8 * 1024 * 1024:
                continue
            (MEME_DIR / name).write_bytes(data)
            copied += 1

    if copied:
        print(f"OK: {copied} Meme-Datei(en) nach 'memes' kopiert.")
    else:
        print("WARN: Keine passenden Memes im ZIP gefunden.")

if __name__ == "__main__":
    main()

