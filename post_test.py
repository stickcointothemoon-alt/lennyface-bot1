import os
import logging
import tweepy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger(__name__)


def make_client():
    """Erstellt einen Tweepy v2 Client mit deinen ENV Keys."""
    client = tweepy.Client(
        bearer_token=os.environ["X_BEARER_TOKEN"],
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_SECRET"],
        wait_on_rate_limit=True,
    )
    return client


def main():
    log.info("Starting Lenny post_test.py …")

    # Optional: eigenen Handle nur fürs Log anzeigen
    try:
        client = make_client()
        me = client.get_me()
        handle = f"@{me.data.username}"
        log.info("Logged in as %s (id=%s)", handle, me.data.id)
    except Exception as e:
        log.error("❌ Could not init client or fetch /me: %s", e)
        return

    # Text kannst du auch über ENV steuern, sonst Default:
    text = os.environ.get(
        "TEST_TWEET_TEXT",
        "Lenny test post ( ͡° ͜ʖ ͡°) – just checking if posting works! #Lenny",
    )

    try:
        resp = client.create_tweet(text=text)
        log.info("✅ Tweet created successfully.")
        log.info("Response: %s", resp.data)
        print("✅ DONE: Tweet created with id:", resp.data.get("id"))
    except tweepy.TweepyException as e:
        log.error("❌ Tweepy error while posting tweet: %s", e)
        print("❌ Tweepy error:", e)
    except Exception as e:
        log.error("❌ General error while posting tweet: %s", e)
        print("❌ General error:", e)


if __name__ == "__main__":
    main()
