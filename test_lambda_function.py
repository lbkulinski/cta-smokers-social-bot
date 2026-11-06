import os
import unittest
from unittest import mock

from botocore.exceptions import ClientError

os.environ.setdefault("STATIONS_TABLE_NAME", "cta-train-stations")
os.environ.setdefault("PROCESSED_REPORTS_TABLE_NAME", "processed-cta-smoking-posts")
os.environ.setdefault("SECRETS_MANAGER_SECRET_ID", "test-secret")

# The module loads secrets from Secrets Manager at import time; stub boto3 for that.
with mock.patch("boto3.client") as _client:
    _client.return_value.get_secret_value.return_value = {"SecretString": "{}"}
    import lambda_function as lf

PLATFORMS = ["twitter_post", "bluesky_post", "mastodon_post", "threads_post", "discord_post"]
REPORTED_AT = "2026-02-21T21:00:22.399660Z"
OTHER_REPORTED_AT = "2026-02-21T22:15:00.000000Z"


class FakeDynamo:
    """In-memory stand-in for the boto3 DynamoDB client (dedupe + stations)."""

    def __init__(self, stations=None):
        self.receipts = {}
        self.put_calls = []
        self.deleted = []
        self.stations = stations or {}
        self.query_calls = []
        self.fail_put = None

    def put_item(self, **kw):
        self.put_calls.append(kw)
        if self.fail_put:
            raise self.fail_put
        key = kw["Item"]["reportKey"]["S"]
        if key in self.receipts:
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")
        self.receipts[key] = kw["Item"]

    def delete_item(self, **kw):
        key = kw["Key"]["reportKey"]["S"]
        self.deleted.append(key)
        self.receipts.pop(key, None)

    def query(self, **kw):
        self.query_calls.append(kw)
        if isinstance(self.stations, Exception):
            raise self.stations
        name = self.stations.get(kw["ExpressionAttributeValues"][":m"]["S"])
        return {"Items": [{"name": {"S": name}}] if name else []}


def image(reported_at=REPORTED_AT, car="2435", line="RED", dest="30173", next_station="40380",
          run="101", extra=None):
    img = {
        "carNumberLine": {"S": f"{car}#{line}"},
        "carNumber": {"S": car},
        "line": {"S": line},
        "gsiPk": {"S": "REPORT"},
        "expiresAt": {"N": "1771700000"},
        "destinationId": {"S": dest},
        "nextStationId": {"S": next_station},
    }
    if reported_at is not None:
        img["reportedAt"] = {"S": reported_at}
    if run is not None:
        img["runNumber"] = {"S": run}
    img.update(extra or {})
    return img


_seq = iter(range(1000, 10**6))


def record(event_name, new=None, old=None, principal=None, seq=None):
    ddb = {"SequenceNumber": str(seq if seq is not None else next(_seq))}
    if new is not None:
        ddb["NewImage"] = new
    if old is not None:
        ddb["OldImage"] = old
    rec = {"eventName": event_name, "dynamodb": ddb}
    if principal:
        rec["userIdentity"] = {"type": "Service", "principalId": principal}
    return rec


class HandlerTestCase(unittest.TestCase):
    def setUp(self):
        lf._station_cache.clear()
        lf._station_cache.update({"30173": "95th/Dan Ryan", "40380": "Clark/Lake"})
        self.posts = {}
        self.dynamo = FakeDynamo()
        patches = [
            mock.patch.object(lf, "_maybe_refresh_threads_token"),
            mock.patch.object(lf, "_dynamodb", return_value=self.dynamo),
        ]
        for name in PLATFORMS:
            m = mock.Mock(return_value={"data": {"id": "1"}, "uri": "u", "id": "1"})
            self.posts[name] = m
            patches.append(mock.patch.object(lf, name, m))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def run_handler(self, *records):
        return lf.lambda_handler({"Records": list(records)}, None)

    def assert_posted(self, times):
        for name, m in self.posts.items():
            self.assertEqual(m.call_count, times, name)


class NewReportTests(HandlerTestCase):
    def test_insert_posts_once_with_expected_text(self):
        self.run_handler(record("INSERT", new=image()))
        self.assert_posted(1)
        self.posts["twitter_post"].assert_called_once_with(
            "🚬 Red Line to 95th/Dan Ryan\n\nNext Stop: Clark/Lake\nCar: 2435 · Run: 101"
        )

    def test_insert_does_not_use_date_or_report_id(self):
        # Neither legacy attribute is present; the handler must not need them.
        img = image()
        self.assertNotIn("date", img)
        self.assertNotIn("reportId", img)
        self.run_handler(record("INSERT", new=img))
        self.assert_posted(1)

    def test_modify_with_new_reported_at_posts(self):
        self.run_handler(record("MODIFY", new=image(OTHER_REPORTED_AT), old=image(REPORTED_AT)))
        self.assert_posted(1)

    def test_modify_with_same_reported_at_does_not_post(self):
        self.run_handler(record("MODIFY", new=image(), old=image()))
        self.assert_posted(0)

    def test_modify_without_old_image_posts(self):
        self.run_handler(record("MODIFY", new=image()))
        self.assert_posted(1)

    def test_ttl_remove_does_not_post(self):
        self.run_handler(record("REMOVE", old=image(), principal="dynamodb.amazonaws.com"))
        self.assert_posted(0)

    def test_manual_remove_does_not_post(self):
        self.run_handler(record("REMOVE", old=image()))
        self.assert_posted(0)

    def test_remove_with_new_image_does_not_post(self):
        self.run_handler(record("REMOVE", new=image(), old=image()))
        self.assert_posted(0)


class FieldHandlingTests(HandlerTestCase):
    def test_missing_run_number_omits_run(self):
        self.run_handler(record("INSERT", new=image(run=None)))
        self.posts["twitter_post"].assert_called_once_with(
            "🚬 Red Line to 95th/Dan Ryan\n\nNext Stop: Clark/Lake\nCar: 2435"
        )

    def test_loop_destination_is_handled(self):
        with mock.patch.object(lf, "get_station_name", wraps=lf.get_station_name) as g:
            self.run_handler(record("INSERT", new=image(line="BROWN", dest="0")))
            looked_up = [c.args[0] for c in g.call_args_list]
        self.assertNotIn("0", looked_up)
        self.posts["twitter_post"].assert_called_once_with(
            "🚬 Brown Line to Loop\n\nNext Stop: Clark/Lake\nCar: 2435 · Run: 101"
        )


class MalformedReportedAtTests(HandlerTestCase):
    def test_missing_reported_at_is_skipped(self):
        self.run_handler(record("INSERT", new=image(reported_at=None)))
        self.assert_posted(0)

    def test_malformed_reported_at_is_skipped(self):
        self.run_handler(record("INSERT", new=image(reported_at="not-a-date")))
        self.assert_posted(0)

    def test_non_string_reported_at_is_skipped(self):
        self.run_handler(record("INSERT", new=image(extra={"reportedAt": {"N": "5"}})))
        self.assert_posted(0)

    def test_malformed_modify_is_skipped(self):
        self.run_handler(record("MODIFY", new=image(reported_at="garbage"), old=image()))
        self.assert_posted(0)

    def test_bad_record_does_not_fail_or_block_rest_of_batch(self):
        result = self.run_handler(
            record("INSERT", new=image(reported_at="garbage")),
            record("INSERT", new={}),
            record("INSERT", new=image(car="7109", line="BLUE", dest="30173")),
        )
        self.assertEqual(result, {"batchItemFailures": []})
        self.assert_posted(1)

    def test_unexpected_error_in_one_record_does_not_fail_batch(self):
        real = lf.build_post
        calls = []

        def flaky(report):
            calls.append(report["carNumber"])
            if report["carNumber"] == "1111":
                raise ValueError("boom")
            return real(report)

        with mock.patch.object(lf, "build_post", flaky):
            self.run_handler(
                record("INSERT", new=image(car="1111")),
                record("INSERT", new=image(car="2222")),
            )
        self.assertEqual(calls, ["1111", "2222"])
        self.assert_posted(1)


class DedupeTests(HandlerTestCase):
    def test_claims_one_receipt_per_platform_with_ttl(self):
        self.run_handler(record("INSERT", new=image()))
        keys = sorted(self.dynamo.receipts)
        self.assertEqual(keys, sorted(f"2435#RED#{REPORTED_AT}#{p}" for p in
                                      ["twitter", "bluesky", "mastodon", "threads", "discord"]))
        call = self.dynamo.put_calls[0]
        self.assertEqual(call["TableName"], "processed-cta-smoking-posts")
        self.assertEqual(call["ConditionExpression"], "attribute_not_exists(reportKey)")
        self.assertIn("ttl", call["Item"])

    def test_replayed_record_posts_only_once(self):
        rec = record("INSERT", new=image())
        self.run_handler(rec)
        self.run_handler(rec)
        self.assert_posted(1)

    def test_failed_platform_releases_receipt_and_retry_fills_gap(self):
        self.posts["bluesky_post"].side_effect = RuntimeError("down")
        rec = record("INSERT", new=image())
        self.run_handler(rec)
        self.assertEqual(self.dynamo.deleted, [f"2435#RED#{REPORTED_AT}#bluesky"])
        self.posts["bluesky_post"].side_effect = None
        self.run_handler(rec)
        self.assertEqual(self.posts["bluesky_post"].call_count, 2)
        for name in PLATFORMS:
            if name != "bluesky_post":
                self.assertEqual(self.posts[name].call_count, 1, name)

    def test_dedupe_error_reports_that_record_and_stops(self):
        ok = record("INSERT", new=image(car="1111"), seq=10)
        bad = record("INSERT", new=image(car="2222"), seq=11)
        after = record("INSERT", new=image(car="3333"), seq=12)
        real_put = self.dynamo.put_item

        def put(**kw):
            if "2222#RED" in kw["Item"]["reportKey"]["S"]:
                raise ClientError({"Error": {"Code": "ProvisionedThroughputExceededException"}}, "PutItem")
            return real_put(**kw)

        self.dynamo.put_item = put
        result = self.run_handler(ok, bad, after)
        self.assertEqual(result, {"batchItemFailures": [{"itemIdentifier": "11"}]})
        self.assertEqual(self.posts["twitter_post"].call_count, 1)  # only the first record
        self.assertFalse(any("3333" in k for k in self.dynamo.receipts))

    def test_dedupe_error_without_sequence_number_fails_whole_batch(self):
        self.dynamo.fail_put = ClientError({"Error": {"Code": "InternalServerError"}}, "PutItem")
        rec = record("INSERT", new=image())
        del rec["dynamodb"]["SequenceNumber"]
        with self.assertRaises(lf.DedupeUnavailable):
            self.run_handler(rec)
        self.assert_posted(0)

    def test_failed_release_is_logged_as_error(self):
        import contextlib
        import io

        self.posts["bluesky_post"].side_effect = RuntimeError("down")
        self.dynamo.delete_item = mock.Mock(side_effect=RuntimeError("denied"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.run_handler(record("INSERT", new=image()))
        self.assertIn("ERROR: could not release receipt", out.getvalue())

    def test_unparseable_response_does_not_release_receipt_or_repost(self):
        self.posts["twitter_post"].return_value = {}  # describe() expects r["data"]["id"]
        rec = record("INSERT", new=image())
        self.run_handler(rec)
        self.assertEqual(self.dynamo.deleted, [])
        self.run_handler(rec)
        self.assertEqual(self.posts["twitter_post"].call_count, 1)

    def test_station_lookup_failure_reports_record_for_retry_without_claiming(self):
        lf._station_cache.clear()
        with mock.patch.object(lf, "get_station_name", side_effect=lf.StationLookupUnavailable("down")):
            result = self.run_handler(record("INSERT", new=image(), seq=21))
        self.assertEqual(result, {"batchItemFailures": [{"itemIdentifier": "21"}]})
        self.assertEqual(self.dynamo.put_calls, [])
        self.assert_posted(0)

    def test_unknown_station_does_not_claim_receipts(self):
        lf._station_cache.clear()
        self.run_handler(record("INSERT", new=image()))
        self.assertEqual(self.dynamo.put_calls, [])


class ErrorLoggingTests(HandlerTestCase):
    def test_failed_post_logs_status_but_not_url_or_secrets(self):
        import contextlib
        import io

        import requests

        secret_url = "https://discord.com/api/webhooks/123/SECRET-TOKEN"
        resp = requests.Response()
        resp.status_code = 401
        resp.url = secret_url
        err = requests.HTTPError(f"401 Client Error: Unauthorized for url: {secret_url}", response=resp)
        self.posts["discord_post"].side_effect = err
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.run_handler(record("INSERT", new=image()))
        logged = out.getvalue()
        self.assertNotIn("SECRET-TOKEN", logged)
        self.assertIn("Failed to post to discord: HTTPError (HTTP 401)", logged)


class StationLookupTests(unittest.TestCase):
    def setUp(self):
        lf._station_cache.clear()
        self.addCleanup(lf._station_cache.clear)

    def lookup(self, dynamo, map_id):
        with mock.patch.object(lf, "_dynamodb", return_value=dynamo):
            return lf.get_station_name(map_id)

    def test_queries_by_map_id_without_scanning(self):
        dynamo = FakeDynamo(stations={"41090": "Monroe"})
        self.assertEqual(self.lookup(dynamo, "41090"), "Monroe")
        self.assertFalse(hasattr(dynamo, "scan"))
        call = dynamo.query_calls[0]
        self.assertEqual(call["TableName"], "cta-train-stations")
        self.assertEqual(call["KeyConditionExpression"], "mapId = :m")
        self.assertEqual(call["ExpressionAttributeValues"], {":m": {"S": "41090"}})
        self.assertEqual(call["Limit"], 1)

    def test_second_lookup_is_served_from_cache(self):
        dynamo = FakeDynamo(stations={"41090": "Monroe"})
        self.lookup(dynamo, "41090")
        self.lookup(dynamo, "41090")
        self.assertEqual(len(dynamo.query_calls), 1)

    def test_unknown_map_id_returns_none(self):
        self.assertIsNone(self.lookup(FakeDynamo(), "99999"))

    def test_query_failure_raises_and_is_not_cached(self):
        with self.assertRaises(lf.StationLookupUnavailable):
            self.lookup(FakeDynamo(stations=RuntimeError("denied")), "41090")
        self.assertEqual(self.lookup(FakeDynamo(stations={"41090": "Monroe"}), "41090"), "Monroe")


class ReportIdTests(unittest.TestCase):
    def test_report_key_is_car_number_line_plus_reported_at(self):
        report = lf.deserialize_dynamo_image(image())
        self.assertEqual(lf.report_key(report), f"2435#RED#{REPORTED_AT}")
