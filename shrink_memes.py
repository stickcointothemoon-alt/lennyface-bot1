# shrink_memes.py
import os
from PIL import Image

folder = "memes"
max_width = 800     # maximal 800 Pixel Breite
quality = 75        # Kompressionsqualität

for file in os.listdir(folder):
    path = os.path.join(folder, file)
    if not os.path.isfile(path):
        continue
    ext = os.path.splitext(file)[1].lower()
    if ext not in [".jpg", ".jpeg", ".png"]:
        continue
    try:
        img = Image.open(path).convert("RGB")
        w, h = img.size
        if w > max_width:
            nh = int(h * (max_width / w))
            img = img.resize((max_width, nh), Image.LANCZOS)
        img.save(path, "JPEG", quality=quality, optimize=True)
        print("✅", file)
    except Exception as e:
        print("⚠️", file, e)
