import os
import io
import zipfile
import logging
import pathlib
import requests
from tempfile import NamedTemporaryFile

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
LOG = logging.getLogger("fetch_memes")

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

def main():
    url = os.getenv("FETCH_MEMES_URL", "").strip()
    memes_dir = pathlib.Path("memes")
    memes_dir.mkdir(exist_ok=True)

    if not url:
        LOG.warning("FETCH_MEMES_URL fehlt. Überspringe Download.")
        return

    LOG.info(f"Lade Memes von {url} ...")
    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()

        with NamedTemporaryFile(delete=False) as tmp:
            tmp.write(resp.content)
            tmp_path = tmp.name

        copied = []
        with zipfile.ZipFile(tmp_path, "r") as zf:
            for info in zf.infolist():
                name = info.filename
                if name.endswith("/"):
                    continue
                ext = pathlib.Path(name).suffix.lower()
                if ext in ALLOWED_EXT:
                    data = zf.read(name)
                    out = memes_dir / pathlib.Path(name).name
                    with open(out, "wb") as f:
                        f.write(data)
                    copied.append(out.name)

        if copied:
            LOG.info(f"OK: {len(copied)} Meme-Datei(en) nach 'memes' kopiert.")
            for n in copied[:8]:
                LOG.info(f"   • {n}")
            if len(copied) > 8:
                LOG.info(f"   … (+{len(copied)-8} weitere)")
        else:
            LOG.warning("Keine passenden Meme-Dateien im ZIP gefunden.")
    except Exception as e:
        LOG.error(f"Fehler beim Meme-Download: {e}")

if __name__ == "__main__":
    main()
