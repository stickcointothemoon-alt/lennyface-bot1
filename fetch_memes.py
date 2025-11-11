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
        print("❌ FETCH_MEMES_URL fehlt (Config Var).")
        return

    MEME_DIR.mkdir(parents=True, exist_ok=True)

    print(f"📦 Lade Memes von {URL} ...")
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
            # einfache Größenbremse (z. B. 8 MB)
            if len(data) > 8 * 1024 * 1024:
                continue
            (MEME_DIR / name).write_bytes(data)
            copied += 1

    if copied:
        print(f"✅ {copied} Meme-Datei(en) nach 'memes' kopiert.")
        # Liste kurz andeuten
        for i, p in enumerate(sorted(MEME_DIR.iterdir())):
            if p.is_file() and p.suffix.lower() in VALID_EXT:
                if i < 8:
                    print(f"   • {p.name}")
                elif i == 8:
                    rest = len([x for x in MEME_DIR.iterdir() if x.is_file() and x.suffix.lower() in VALID_EXT]) - 8
                    if rest > 0:
                        print(f"   … (+{rest} weitere)")
                        break
    else:
        print(⚠️ Keine passenden Memes im ZIP gefunden.")

if __name__ == "__main__":
    main()
