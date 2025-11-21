def should_attach_meme(text: str, is_mention: bool = False) -> bool:
    """
    Entscheidet, ob ein Meme angehängt wird.

    - Respektiert AUTO_MEME_MODE (Dashboard Toggle)
    - Basis: MEME_PROBABILITY
    - Smart-Boost je nach Keywords im Text
    - Mentions bekommen leicht höhere Chance als KOL-Tweets
    """
    if not AUTO_MEME_MODE:
        log.info("should_attach_meme: AUTO_MEME_MODE=0 → no meme")
        return False

    # Basis-Wahrscheinlichkeit aus ENV
    try:
        base_prob = float(MEME_PROBABILITY)
    except Exception:
        base_prob = 0.3

    # Smart-Boost aus Keywords
    boost = _meme_boost_score(text)

    # Mentions dürfen etwas mehr Meme-Power haben
    try:
        extra = float(AUTO_MEME_EXTRA_CHANCE)
    except Exception:
        extra = 0.5

    if is_mention:
        boost += extra * 0.5

    prob = base_prob + boost

    # Sicherheits-Cap
    if prob > 0.95:
        prob = 0.95
    if prob < 0.0:
        prob = 0.0

    r = random.random()
    decision = r < prob

    log.info(
        "should_attach_meme: base=%.2f boost=%.2f is_mention=%s → prob=%.2f roll=%.3f → %s",
        base_prob,
        boost,
        is_mention,
        prob,
        r,
        "YES" if decision else "NO",
    )

    return decision
