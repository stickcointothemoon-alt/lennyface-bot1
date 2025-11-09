import os
import zipfile
import requests
from io import BytesIO

url = os.getenv("MEMES_ZIP_URL")
target_dir = "memes"

if not url:
    print("❌ Kein MEMES_ZIP_URL gesetzt!")
    exit(1)

print(f"📦 Lade Memes von {url} ...")
r = requests.get(url)
if r.status_code != 200:
    print(f"❌ Download fehlgeschlagen: {r.status_code}")
    exit(1)

os.makedirs(target_dir, exist_ok=True)

with zipfile.ZipFile(BytesIO(r.content)) as zip_ref:
    zip_ref.extractall(target_dir)

print(f"✅ Memes erfolgreich nach '{target_dir}' entpackt.")
