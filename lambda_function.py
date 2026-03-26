import os
import json
import boto3
import requests

def _load_secrets() -> None:
    client = boto3.client("secretsmanager")
    secret = client.get_secret_value(SecretId="prod/cta-smokers-bot")
    data = json.loads(secret["SecretString"])
    for key, value in data.items():
        os.environ[key] = value

_load_secrets()

BLUESKY_API = "https://bsky.social/xrpc"

def _bluesky_token() -> str:
    resp = requests.post(
        f"{BLUESKY_API}/com.atproto.server.createSession",
        json={
            "identifier": os.environ["BLUESKY_HANDLE"],
            "password": os.environ["BLUESKY_APP_PASSWORD"],
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["accessJwt"]

def twitter_post(text: str) -> dict:
    from requests_oauthlib import OAuth1
    auth = OAuth1(
        os.environ["TWITTER_CONSUMER_KEY"],
        os.environ["TWITTER_CONSUMER_SECRET"],
        os.environ["TWITTER_ACCESS_TOKEN"],
        os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
    )
    resp = requests.post(
        "https://api.twitter.com/2/tweets",
        auth=auth,
        json={"text": text},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def threads_post(text: str) -> dict:
    user_id = os.environ["THREADS_USER_ID"]
    token = os.environ["THREADS_ACCESS_TOKEN"]

    # Step 1: create media container
    container = requests.post(
        f"https://graph.threads.net/v1.0/{user_id}/threads",
        params={"media_type": "TEXT", "text": text, "access_token": token},
        timeout=10,
    )
    container.raise_for_status()
    container_id = container.json()["id"]

    # Step 2: publish
    publish = requests.post(
        f"https://graph.threads.net/v1.0/{user_id}/threads_publish",
        params={"creation_id": container_id, "access_token": token},
        timeout=10,
    )
    publish.raise_for_status()
    return publish.json()


def mastodon_post(text: str) -> dict:
    resp = requests.post(
        "https://mastodon.social/api/v1/statuses",
        headers={"Authorization": f"Bearer {os.environ['MASTODON_ACCESS_TOKEN']}"},
        json={"status": text},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def bluesky_post(text: str) -> dict:
    token = _bluesky_token()
    resp = requests.post(
        f"{BLUESKY_API}/com.atproto.repo.createRecord",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "repo": os.environ["BLUESKY_HANDLE"],
            "collection": "app.bsky.feed.post",
            "record": {
                "$type": "app.bsky.feed.post",
                "text": text,
                "createdAt": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            },
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()

# --- Station name cache (populated once at cold start) ---
_station_cache: dict[str, str] = {}

TRAIN_LINE_LABELS = {
    "RED": "Red",
    "BLUE": "Blue",
    "BROWN": "Brown",
    "GREEN": "Green",
    "ORANGE": "Orange",
    "PINK": "Pink",
    "PURPLE": "Purple",
    "YELLOW": "Yellow",
}

CTA_STOPS_URL = "https://data.cityofchicago.org/resource/8pix-ypme.json"


def get_station_name(map_id: str) -> str:
    if not _station_cache:
        _load_station_cache()
    return _station_cache.get(map_id, f"station {map_id}")


def _load_station_cache() -> None:
    try:
        resp = requests.get(CTA_STOPS_URL, params={"$limit": 10000}, timeout=10)
        resp.raise_for_status()
        for stop in resp.json():
            mid = stop.get("map_id")
            name = stop.get("station_name")
            if mid and name:
                _station_cache[str(mid)] = name
        print(f"Loaded {len(_station_cache)} stations into cache")
    except Exception as e:
        print(f"Warning: could not load station cache: {e}")


def build_post(report: dict) -> str:
    line_key = report.get("line", "")
    line_label = TRAIN_LINE_LABELS.get(line_key.upper(), line_key.title())

    next_station_id = report.get("nextStationId", "")
    station_name = get_station_name(next_station_id)

    destination_id = report.get("destinationId", "")
    destination_name = get_station_name(destination_id) if destination_id else None

    car_number = report.get("carNumber", "unknown")
    run_number = report.get("runNumber")

    header = f"🚬 {line_label} Line to {destination_name}" if destination_name else f"🚬 {line_label} Line"
    post = f"{header}\n\nNext Stop: {station_name}\nCar: {car_number}"
    if run_number:
        post += f" · Run: {run_number}"

    return post


def lambda_handler(event, context):
    for record in event.get("Records", []):
        if record.get("eventName") != "INSERT":
            continue

        new_image = record.get("dynamodb", {}).get("NewImage", {})
        if not new_image:
            continue

        report = deserialize_dynamo_image(new_image)
        print(f"Processing report: {json.dumps(report)}")

        post_text = build_post(report)

        try:
            response = twitter_post(post_text)
            print(f"Twitter post created, id={response['data']['id']}")
        except Exception as e:
            print(f"Failed to post to Twitter: {e}")

        try:
            response = bluesky_post(post_text)
            print(f"Bluesky post created, uri={response['uri']}")
        except Exception as e:
            print(f"Failed to post to Bluesky: {e}")

        try:
            response = mastodon_post(post_text)
            print(f"Mastodon post created, id={response['id']}")
        except Exception as e:
            print(f"Failed to post to Mastodon: {e}")

        try:
            response = threads_post(post_text)
            print(f"Threads post created, id={response['id']}")
        except Exception as e:
            print(f"Failed to post to Threads: {e}")


def deserialize_dynamo_image(image: dict) -> dict:
    """Flatten a DynamoDB NewImage (typed attribute map) into plain Python values."""
    result = {}
    for key, typed_val in image.items():
        result[key] = _unwrap(typed_val)
    return result


def _unwrap(typed_val: dict):
    if "S" in typed_val:
        return typed_val["S"]
    if "N" in typed_val:
        val = typed_val["N"]
        return int(val) if "." not in val else float(val)
    if "BOOL" in typed_val:
        return typed_val["BOOL"]
    if "NULL" in typed_val:
        return None
    if "L" in typed_val:
        return [_unwrap(v) for v in typed_val["L"]]
    if "M" in typed_val:
        return {k: _unwrap(v) for k, v in typed_val["M"].items()}
    return None
