# fetch_memes.py
import os, io, sys, zipfile, shutil, tempfile
from urllib.parse import urlparse
import requests
from PIL import Image

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
OUT_DIR = "memes"

def log(msg):
    print(msg, flush=True)

def ensure_out_dir():
    if not os.path.isdir(OUT_DIR):
        os.makedirs(OUT_DIR, exist_ok=True)

def safe_ext(name: str) -> str:
    name = name.lower()
    for ext in ALLOWED_EXT:
        if name.endswith(ext):
            return ext
    return ""

def normalize_image(in_bytes: bytes, orig_name: str) -> (bytes, str):
    """
    - Öffnet via Pillow
    - Konvertiert WEBP → PNG
    - Konvertiert CMYK → RGB
    - Gibt (bytes, neue_ext) zurück
    """
    with Image.open(io.BytesIO(in_bytes)) as im:
        fmt = (im.format or "").upper()
        mode = im.mode
        # CMYK → RGB
        if mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA" if "A" in mode else "RGB")

        # WEBP → PNG, sonst Originalformat bevorzugen
        if fmt == "WEBP":
            buf = io.BytesIO()
            im.save(buf, format="PNG", optimize=True)
            return buf.getvalue(), ".png"
        elif fmt in ("PNG", "GIF", "JPEG", "JPG"):
            # Bei JPEG → als JPEG speichern
            target_fmt = "JPEG" if fmt in ("JPEG", "JPG") else fmt
            buf = io.BytesIO()
            if target_fmt == "JPEG":
                # JPEG darf kein Alpha haben
                if im.mode == "RGBA":
                    im = im.convert("RGB")
                im.save(buf, format="JPEG", quality=90, optimize=True)
                return buf.getvalue(), ".jpg"
            else:
                im.save(buf, format=target_fmt, optimize=True)
                return buf.getvalue(), f".{target_fmt.lower()}"
        else:
            # Unbekannt → PNG
            buf = io.BytesIO()
            im.save(buf, format="PNG", optimize=True)
            return buf.getvalue(), ".png"

def main():
    url = os.getenv("FETCH_MEMES_URL", "").strip()
    if not url:
        log("❌ FETCH_MEMES_URL fehlt (Config Var).")
        sys.exit(1)

    ensure_out_dir()

    log(f"📦 Lade Memes von {url} ...")
    try:
        r = requests.get(url, timeout=120)
        r.raise_for_status()
    except Exception as e:
        log(f"❌ Download fehlgeschlagen: {e}")
        sys.exit(1)

    # Versuche ZIP
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.write(r.content)
    tmp.flush()
    tmp.close()

    added = []
    try:
        with zipfile.ZipFile(tmp.name, "r") as zf:
            for zi in zf.infolist():
                if zi.is_dir():
                    continue
                name = os.path.basename(zi.filename)
                if not name:
                    continue
                ext = safe_ext(name)
                if not ext:
                    continue  # nicht unterstützter Typ

                data = zf.read(zi)

                # Normalisieren (WEBP → PNG, CMYK → RGB)
                try:
                    data, new_ext = normalize_image(data, name)
                except Exception:
                    # Wenn Pillow scheitert, nur erlaubte Mime als Rohdaten probieren
                    # → Wir erzwingen PNG Fallback
                    try:
                        with Image.open(io.BytesIO(data)) as im:
                            if im.mode not in ("RGB", "RGBA"):
                                im = im.convert("RGB")
                            buf = io.BytesIO()
                            im.save(buf, format="PNG", optimize=True)
                            data = buf.getvalue()
                            new_ext = ".png"
                    except Exception:
                        continue

                base = os.path.splitext(name)[0]
                out_name = f"{base}{new_ext}"
                out_path = os.path.join(OUT_DIR, out_name)

                # Kollisionssicherer Name
                n = 1
                while os.path.exists(out_path):
                    out_name = f"{base}_{n}{new_ext}"
                    out_path = os.path.join(OUT_DIR, out_name)
                    n += 1

                with open(out_path, "wb") as f:
                    f.write(data)
                added.append(out_name)
    except zipfile.BadZipFile:
        # Kein ZIP? Dann versuchen wir direkte Bilddatei
        ext = safe_ext(urlparse(url).path)
        if not ext:
            log("❌ Kein ZIP und unbekannte Dateiendung – bitte ZIP-Link verwenden.")
            os.unlink(tmp.name)
            sys.exit(1)
        # Speichere als Einzeldatei
        # Normalisieren:
        try:
            data, new_ext = normalize_image(r.content, url)
        except Exception as e:
            log(f"❌ Konnte Bild nicht normalisieren: {e}")
            os.unlink(tmp.name)
            sys.exit(1)
        base = "meme"
        out_path = os.path.join(OUT_DIR, f"{base}{new_ext}")
        n = 1
        while os.path.exists(out_path):
            out_path = os.path.join(OUT_DIR, f"{base}_{n}{new_ext}")
            n += 1
        with open(out_path, "wb") as f:
            f.write(data)
        added.append(os.path.basename(out_path))
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass

    if added:
        log(f"✅ {len(added)} Meme-Datei(en) nach '{OUT_DIR}' kopiert.")
        for i, name in enumerate(added[:8], 1):
            log(f"   • {name}")
        if len(added) > 8:
            log(f"   … (+{len(added)-8} weitere)")
    else:
        log("⚠️ Keine neuen Memes gefunden (evtl. waren sie schon vorhanden).")

if __name__ == "__main__":
    main()
