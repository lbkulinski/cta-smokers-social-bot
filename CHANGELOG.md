# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Target the Python 3.14 Lambda runtime (x86_64); CI and deploy build and test on Python 3.14
- Logging uses the standard `logging` module (INFO and above, with levels) instead of `print`, matching the other consumers
- A failed stations-table lookup is reported via `batchItemFailures` and retried, instead of being treated as an unknown station and dropping the report
- A post whose platform response can't be summarized no longer releases its receipt, so a retry can't repost it
- Dedupe table env var is `PROCESSED_REPORTS_TABLE_NAME`, matching the aggregates and submitter consumers (each still points at its own table)
- CI/CD aligned with `cta-smoking-report-aggregates`: `ci.yml` (ruff + pytest, reusable), deploy gated on CI in a `production` environment, actions pinned to commit SHAs, AWS role/region/function name read from repo **variables** instead of secrets (**action required:** create `AWS_ROLE_ARN`, `AWS_REGION` and `LAMBDA_FUNCTION_NAME` as repository variables and a `production` environment)
- `requests-oauthlib` pinned to `2.0.0` for reproducible builds
- Tests moved to pytest at the repo root; added `requirements-dev.txt`; Dependabot now covers `pip` and `github-actions`
- Support the new reports table schema (`carNumberLine` key, `reportedAt`, no `date`/`reportId`)
- MODIFY events with a changed `reportedAt` are treated as new reports; unchanged MODIFY and all REMOVE events are ignored
- Records with missing or malformed `reportedAt` are skipped; one bad record no longer fails the batch

- Station names are read from the DynamoDB stations table (`STATIONS_TABLE_NAME`) instead of the Chicago Data Portal; `CTA_STOPS_URL` is no longer used

### Added

- MIT `LICENSE`
- README documents the deploy setup (repo variables, `production` environment, OIDC trust subject) and the missing `DISCORD_WEBHOOK_URL` and `THREADS_TOKEN_LAST_REFRESHED` secrets
- Per-platform dedupe receipts (`PROCESSED_REPORTS_TABLE_NAME`): claimed before posting, released if the post fails; a dedupe or stations table error is reported via `batchItemFailures` (requires `ReportBatchItemFailures` on the event source mapping) so Lambda retries from that record; the rest of the batch is still processed
- Unit tests (`pytest`), run in CI
- Dependabot for pip and GitHub Actions

## [1.2.0] - 2026-03-25

### Fixed

- Post format documentation corrected: destination is always present, run number is optional

## [1.1.0] - 2026-03-25

### Added

- `README.md` and `CHANGELOG.md`

### Changed

- `SECRETS_MANAGER_SECRET_ID` environment variable replaces hardcoded Secrets Manager secret ID
- `CTA_STOPS_URL` environment variable replaces hardcoded Chicago Data Portal URL

## [1.0.0] - 2026-03-25

### Added

- AWS Lambda handler triggered by DynamoDB Streams INSERT events
- Post formatting with line, destination, next stop, car number, and run number
- Station name resolution via Chicago Data Portal CTA Stops API with cold-start caching
- Publishing to Twitter via Twitter API v2 with OAuth 1.0
- Publishing to Bluesky via AT Protocol XRPC
- Publishing to Mastodon via Mastodon API
- Publishing to Threads via Meta Graph API
- Credential loading from AWS Secrets Manager at cold start
- DynamoDB typed attribute deserialization

[Unreleased]: https://github.com/lbkulinski/cta-smokers-social-bot/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/lbkulinski/cta-smokers-social-bot/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/lbkulinski/cta-smokers-social-bot/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/lbkulinski/cta-smokers-social-bot/releases/tag/v1.0.0
