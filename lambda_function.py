import os
import re
import json
import datetime
import logging
import time
import boto3
import requests
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _load_secrets() -> None:
    client = boto3.client("secretsmanager")
    secret = client.get_secret_value(SecretId=os.environ["SECRETS_MANAGER_SECRET_ID"])
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


class PlatformError(RuntimeError):
    """A platform call failed. The message is built to be safe to log: no URLs, tokens or request params."""


_ACCESS_TOKEN_PARAM_RE = re.compile(r"access_token=[^&\s\"']+")


def _redact(text: str) -> str:
    """Strip the Threads access token (as a value or as a query parameter) from text headed for the logs."""
    token = os.environ.get("THREADS_ACCESS_TOKEN")
    if token:
        text = text.replace(token, "[redacted]")
    return _ACCESS_TOKEN_PARAM_RE.sub("access_token=[redacted]", text)


def _threads_error(step: str, resp: requests.Response) -> PlatformError:
    """Describe a failed Threads call using the Graph API error fields."""
    try:
        payload = resp.json()
    except ValueError:
        payload = None
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict) and error:
        detail = (
            f"type={error.get('type')} code={error.get('code')} subcode={error.get('error_subcode')} "
            f"message={error.get('message')!r} fbtrace_id={error.get('fbtrace_id')}"
        )
    else:
        detail = f"body={resp.text[:200]!r}"
    return PlatformError(f"Threads {step} failed: HTTP {resp.status_code}: {_redact(detail)}")


def _threads_request(step: str, url: str, params: dict) -> dict:
    """POST to the Threads API. Failures carry the step name and the Graph API error, never the token."""
    started = time.monotonic()
    try:
        resp = requests.post(url, params=params, timeout=10)
    except requests.RequestException as e:
        elapsed = time.monotonic() - started
        raise PlatformError(f"Threads {step} request failed after {elapsed:.1f}s: {type(e).__name__}") from None
    elapsed = time.monotonic() - started
    if not resp.ok:
        raise _threads_error(step, resp)
    logger.info("Threads %s ok: HTTP %d in %.1fs", step, resp.status_code, elapsed)
    return resp.json()


def threads_post(text: str) -> dict:
    user_id = os.environ["THREADS_USER_ID"]
    token = os.environ["THREADS_ACCESS_TOKEN"]
    base = f"https://graph.threads.net/v1.0/{user_id}"

    container = _threads_request(
        "container creation",
        f"{base}/threads",
        {"media_type": "TEXT", "text": text, "access_token": token},
    )
    container_id = container["id"]
    return _threads_request(
        "publish",
        f"{base}/threads_publish",
        {"creation_id": container_id, "access_token": token},
    )


_THREADS_REFRESH_THRESHOLD_DAYS = 50


def _refresh_threads_token() -> None:
    token = os.environ["THREADS_ACCESS_TOKEN"]
    try:
        resp = requests.get(
            "https://graph.threads.net/refresh_access_token",
            params={"grant_type": "th_refresh_token", "access_token": token},
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        response = getattr(e, "response", None)
        status = getattr(response, "status_code", None)
        body = getattr(response, "text", "")[:200]
        detail = f"HTTP {status}: {body}" if status else type(e).__name__
        raise RuntimeError(f"Threads token refresh failed: {detail}") from None
    new_token = resp.json()["access_token"]
    refreshed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    os.environ["THREADS_ACCESS_TOKEN"] = new_token
    os.environ["THREADS_TOKEN_LAST_REFRESHED"] = refreshed_at

    try:
        client = boto3.client("secretsmanager")
        secret = client.get_secret_value(SecretId=os.environ["SECRETS_MANAGER_SECRET_ID"])
        data = json.loads(secret["SecretString"])
        data["THREADS_ACCESS_TOKEN"] = new_token
        data["THREADS_TOKEN_LAST_REFRESHED"] = refreshed_at
        client.put_secret_value(
            SecretId=os.environ["SECRETS_MANAGER_SECRET_ID"],
            SecretString=json.dumps(data),
        )
    except Exception as e:
        logger.warning("Could not persist refreshed Threads token to Secrets Manager: %s: %s", type(e).__name__, e)

    logger.info("Threads token refreshed")


def _maybe_refresh_threads_token() -> None:
    last_refreshed = os.environ.get("THREADS_TOKEN_LAST_REFRESHED")
    if last_refreshed:
        try:
            last_dt = datetime.datetime.fromisoformat(last_refreshed.replace("Z", "+00:00"))
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=datetime.timezone.utc)
            age = datetime.datetime.now(datetime.timezone.utc) - last_dt
            if age.days < _THREADS_REFRESH_THRESHOLD_DAYS:
                return
            logger.info("Threads token is %d days old, refreshing", age.days)
        except ValueError:
            logger.warning("Could not parse THREADS_TOKEN_LAST_REFRESHED (%r), refreshing as a precaution", last_refreshed)
    else:
        logger.info("THREADS_TOKEN_LAST_REFRESHED not set, refreshing to establish baseline")
    try:
        _refresh_threads_token()
    except Exception as e:
        logger.warning("Could not refresh Threads token: %s", e)


def mastodon_post(text: str) -> dict:
    resp = requests.post(
        "https://mastodon.social/api/v1/statuses",
        headers={"Authorization": f"Bearer {os.environ['MASTODON_ACCESS_TOKEN']}"},
        json={"status": text},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def discord_post(text: str) -> dict:
    resp = requests.post(
        os.environ["DISCORD_WEBHOOK_URL"],
        json={"content": text},
        timeout=10,
    )
    resp.raise_for_status()
    return {}


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
                "createdAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            },
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()

# --- Station name cache (filled on demand, per container) ---
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

class RetryableError(Exception):
    """A dependency failed. Raised so Lambda retries the record instead of dropping or duplicating it."""


class DedupeUnavailable(RetryableError):
    """The dedupe table could not be used. Raised so the batch is retried rather than risk a duplicate."""


class StationLookupUnavailable(RetryableError):
    """The stations table could not be queried. Raised so the batch is retried rather than drop the report."""


LOOP_DESTINATION_ID = "0"


def get_station_name(map_id: str) -> str | None:
    """Look up a station name by map ID (the stations table's partition key), caching hits."""
    map_id = str(map_id)
    if map_id in _station_cache:
        return _station_cache[map_id]
    try:
        # Every stop under a mapId carries the same station name, so one item is enough.
        page = _dynamodb().query(
            TableName=os.environ["STATIONS_TABLE_NAME"],
            KeyConditionExpression="mapId = :m",
            ExpressionAttributeValues={":m": {"S": map_id}},
            ProjectionExpression="#n",
            ExpressionAttributeNames={"#n": "name"},
            Limit=1,
        )
    except Exception as e:
        # A failed lookup is not an unknown station: raise so the record is retried, not dropped.
        raise StationLookupUnavailable(f"station {map_id}: {type(e).__name__}: {e}") from e
    items = page.get("Items", [])
    name = items[0].get("name", {}).get("S") if items else None
    if name:
        _station_cache[map_id] = name
    return name


def _dynamodb():
    return boto3.client("dynamodb")


def build_post(report: dict) -> str | None:
    line_key = report.get("line", "")
    line_label = TRAIN_LINE_LABELS.get(line_key.upper(), line_key.title())

    next_station_id = report.get("nextStationId", "")
    station_name = get_station_name(next_station_id)
    if station_name is None:
        return None

    destination_id = report.get("destinationId")
    if str(destination_id) == LOOP_DESTINATION_ID:
        destination_name = "Loop"
    elif destination_id:
        destination_name = get_station_name(destination_id)
    else:
        destination_name = None

    car_number = report.get("carNumber", "unknown")
    run_number = report.get("runNumber")

    header = f"🚬 {line_label} Line to {destination_name}" if destination_name else f"🚬 {line_label} Line"
    post = f"{header}\n\nNext Stop: {station_name}\nCar: {car_number}"
    if run_number:
        post += f" · Run: {run_number}"

    return post


_RECEIPT_TTL_SECONDS = 7 * 24 * 60 * 60


def _claim(receipt_key: str) -> bool:
    """Atomically record that this report/platform is being posted. False if already claimed."""
    ttl = int(datetime.datetime.now(datetime.timezone.utc).timestamp()) + _RECEIPT_TTL_SECONDS
    try:
        _dynamodb().put_item(
            TableName=os.environ["PROCESSED_REPORTS_TABLE_NAME"],
            Item={"reportKey": {"S": receipt_key}, "ttl": {"N": str(ttl)}},
            ConditionExpression="attribute_not_exists(reportKey)",
        )
        return True
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise DedupeUnavailable(f"{type(e).__name__}: {e}") from e
    except Exception as e:
        raise DedupeUnavailable(f"{type(e).__name__}: {e}") from e


def _release(receipt_key: str) -> None:
    try:
        _dynamodb().delete_item(
            TableName=os.environ["PROCESSED_REPORTS_TABLE_NAME"],
            Key={"reportKey": {"S": receipt_key}},
        )
    except Exception as e:
        logger.error("Could not release receipt %s, a retry will skip this platform: %s", receipt_key, type(e).__name__)


def _describe_error(e: Exception) -> str:
    """Error summary safe to log: exception type and HTTP status only, or a PlatformError's own message.

    requests puts the full URL in its messages, and some URLs are secrets
    (Discord webhook, Threads access_token query param).
    """
    if isinstance(e, PlatformError):
        return str(e)
    status = getattr(getattr(e, "response", None), "status_code", None)
    return f"{type(e).__name__} (HTTP {status})" if status else type(e).__name__


def _post_once(report_key_: str, platform: str, post_fn, describe, text: str) -> None:
    """Claim a receipt, then post. A crash after the claim drops a post but never duplicates one."""
    receipt_key = f"{report_key_}#{platform}"
    if not _claim(receipt_key):
        logger.info("Skipping %s: already posted %s", platform, receipt_key)
        return
    try:
        response = post_fn(text)
    except Exception as e:
        logger.error("Failed to post to %s: %s", platform, _describe_error(e))
        _release(receipt_key)
        return
    # The post succeeded: never release the receipt past this point, or a retry would repost.
    try:
        detail = describe(response)
    except Exception:
        detail = "response details unavailable"
    logger.info("%s post created, %s", platform, detail)


def _parse_reported_at(report: dict) -> datetime.datetime | None:
    """Return reportedAt as an aware datetime, or None if missing or malformed."""
    value = report.get("reportedAt")
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def report_key(report: dict) -> str:
    """Stable identifier for a report: carNumberLine plus reportedAt."""
    return f"{report.get('carNumberLine')}#{report.get('reportedAt')}"


def _is_new_report(record: dict) -> bool:
    """INSERT is new. MODIFY is new only when reportedAt changed. REMOVE (TTL or manual) never is."""
    event_name = record.get("eventName")
    ddb = record.get("dynamodb", {})
    if event_name == "INSERT":
        return True
    if event_name == "MODIFY":
        new_reported_at = ddb.get("NewImage", {}).get("reportedAt")
        old_reported_at = ddb.get("OldImage", {}).get("reportedAt")
        return new_reported_at != old_reported_at
    return False


def _process_record(record: dict) -> None:
    if not _is_new_report(record):
        return

    new_image = record.get("dynamodb", {}).get("NewImage", {})
    if not new_image:
        return

    report = deserialize_dynamo_image(new_image)
    if _parse_reported_at(report) is None:
        logger.warning("Skipping report with missing or malformed reportedAt: %s", json.dumps(report))
        return

    key = report_key(report)
    logger.info("Processing report %s: %s", key, json.dumps(report))

    post_text = build_post(report)
    if post_text is None:
        logger.warning("Skipping report %s with unknown station: %s", key, json.dumps(report))
        return

    platforms = [
        ("twitter", twitter_post, lambda r: f"id={r['data']['id']}"),
        ("bluesky", bluesky_post, lambda r: f"uri={r['uri']}"),
        ("mastodon", mastodon_post, lambda r: f"id={r['id']}"),
        ("threads", threads_post, lambda r: f"id={r['id']}"),
        ("discord", discord_post, lambda r: ""),
    ]
    for platform, post_fn, describe in platforms:
        _post_once(key, platform, post_fn, describe, post_text)


def lambda_handler(event, context):
    """Process stream records, reporting partial batch failures.

    Needs ReportBatchItemFailures in the event source mapping's FunctionResponseTypes,
    otherwise Lambda ignores the response and treats the batch as successful.
    """
    _maybe_refresh_threads_token()

    failures = []
    for record in event.get("Records", []):
        # One bad record must not fail the batch: a failed invocation is retried
        # in full, which would re-post records that already succeeded.
        try:
            _process_record(record)
        except RetryableError as e:
            sequence_number = record.get("dynamodb", {}).get("SequenceNumber")
            if not sequence_number:
                # Cannot report a record without a sequence number; fail the whole batch instead.
                raise
            # Lambda retries from the lowest failed sequence number. Records after it may be
            # redelivered, which is safe because receipts stop any re-post.
            logger.error("Dependency unavailable, retrying sequence %s: %s", sequence_number, e)
            failures.append({"itemIdentifier": sequence_number})
        except Exception as e:
            logger.error("Skipping record after unexpected error: %s: %s", type(e).__name__, e)

    return {"batchItemFailures": failures}


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
