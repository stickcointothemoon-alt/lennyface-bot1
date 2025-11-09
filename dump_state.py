import json, os

# Pfade prüfen – lokal und in Heroku
possible_paths = ["/app/state.json", "/tmp/state.json", "state.json"]

for p in possible_paths:
    if os.path.exists(p):
        data = json.load(open(p))
        print(f"✅ Gefunden: {p}")
        print(','.join(data))
        break
else:
    print("⚠️ Keine state.json gefunden.")
