def decorate_with_lenny_face(text: str, cmd_used: str | None) -> str:
    """
    Hängt ein passendes Lennyface an den Reply an – abhängig vom Command
    UND von der aktuellen Season (Xmas, Easter, ...).

    LOGIK:
    - In Xmas/Easter: IMMER ein Season-Lenny anhängen (🎄/🎅 bzw. 🥕/🐣),
      auch wenn schon ein normales ( ͡° ͜ʖ ͡°) im Text ist.
    - Außerhalb von Seasons: wenn schon ein ( ͡ im Text ist → nichts doppelt.
    """

    if not text:
        return text

    # Aktuelle Season bestimmen: 'xmas', 'easter' oder None
    season = current_season()  # du hast current_season schon weiter oben definiert

    # -----------------------------
    # SEASON-MODUS (XMAS / EASTER)
    # -----------------------------
    if season in ("xmas", "easter"):
        # Wenn schon ein Season-Emoji drin ist, nichts mehr tun
        if season == "xmas":
            season_markers = ["🎄", "🎅"]
        else:
            season_markers = ["🥕", "🐣"]

        if any(m in text for m in season_markers):
            return text  # Season ist schon im Text

        # Mood = Season-Faces
        mood = season

        # Season-Lenny immer hinten anhängen – auch wenn schon ( ͡° ͜ʖ ͡°) im Text ist
        face = pick_lenny_face(mood)

        if text.endswith(("!", "?", ".")):
            return text + " " + face
        return text + " " + face

    # -----------------------------
    # NORMALER MODUS (KEINE SEASON)
    # -----------------------------
    # Wenn schon irgendein Lennyface drin ist → nichts doppelt reinhauen
    if "( ͡" in text:
        return text

    # Mood je nach Command
    if cmd_used in ("gm", "alpha"):
        mood = "hype"
    elif cmd_used == "roast":
        mood = "cope"
    elif cmd_used == "price":
        lower = text.lower()
        if any(k in lower for k in ["dump", "down", "red", "-%"]):
            mood = "sad"
        else:
            mood = "hype"
    elif cmd_used == "shill":
        mood = random.choice(["base", "hype"])
    else:
        mood = "base"

    face = pick_lenny_face(mood)

    # Schön ans Ende anhängen
    if text.endswith(("!", "?", ".")):
        return text + " " + face
    return text + " " + face
