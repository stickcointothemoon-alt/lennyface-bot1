# fetch_memes.py
import os, sys, shutil, zipfile, tempfile, glob
from urllib.request import urlopen, Request

URL = os.getenv("FETCH_MEMES_URL", "").strip()
TARGET_DIR = "memes"
OK_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

def download(url, out_path):
    req = Request(url, headers={"User-Agent":"Mozilla/5.0"})
    with urlopen(req) as r, open(out_path, "wb") as f:
        shutil.copyfileobj(r, f)

def main():
    if not URL:
        print("❌ FETCH_MEMES_URL fehlt (Config Var).")
        sys.exit(1)
    os.makedirs(TARGET_DIR, exist_ok=True)

    # temp-ZIP
    tmpdir = tempfile.mkdtemp()
    zippath = os.path.join(tmpdir, "memes.zip")

    print(f"📦 Lade Memes von {URL} ...")
    download(URL, zippath)

    # entpacken nach temp
    extract_dir = os.path.join(tmpdir, "extract")
    os.makedirs(extract_dir, exist_ok=True)
    with zipfile.ZipFile(zippath, "r") as z:
        z.extractall(extract_dir)

    # alle Bilddateien finden (egal, ob die ZIP einen Unterordner hat)
    moved = 0
    for root, _, files in os.walk(extract_dir):
        for name in files:
            ext = os.path.splitext(name)[1].lower()
            if ext in OK_EXT:
                src = os.path.join(root, name)
                # Kollisionssicheren Zielnamen erzeugen
                base = os.path.basename(name)
                dst = os.path.join(TARGET_DIR, base)
                i = 1
                while os.path.exists(dst):
                    stem, e = os.path.splitext(base)
                    dst = os.path.join(TARGET_DIR, f"{stem}_{i}{e}")
                    i += 1
                shutil.move(src, dst)
                moved += 1

    # placeholder entfernen, wenn wir echte Dateien haben
    ph = os.path.join(TARGET_DIR, "placeholder.txt")
    if moved > 0 and os.path.exists(ph):
        os.remove(ph)

    print(f"✅ {moved} Meme-Datei(en) nach '{TARGET_DIR}' kopiert.")
    # kurz zeigen, was drin liegt
    files = sorted(glob.glob(os.path.join(TARGET_DIR, "*")))
    for f in files[:8]:
        print("   •", os.path.basename(f))
    if len(files) > 8:
        print(f"   … (+{len(files)-8} weitere)")

if __name__ == "__main__":
    main()

