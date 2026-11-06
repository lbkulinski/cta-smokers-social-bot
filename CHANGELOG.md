# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Dedupe table env var is `PROCESSED_REPORTS_TABLE_NAME`, matching the aggregates and submitter consumers (each still points at its own table)
- CI/CD aligned with `cta-smoking-report-aggregates`: `ci.yml` (ruff + pytest, reusable), deploy gated on CI in a `production` environment, actions pinned to commit SHAs, AWS role/region/function name read from repo **variables** instead of secrets (**action required:** create `AWS_ROLE_ARN`, `AWS_REGION` and `LAMBDA_FUNCTION_NAME` as repository variables and a `production` environment)
- Tests moved to pytest at the repo root; added `requirements-dev.txt`; Dependabot now covers `pip` and `github-actions`
- Support the new reports table schema (`carNumberLine` key, `reportedAt`, no `date`/`reportId`)
- MODIFY events with a changed `reportedAt` are treated as new reports; unchanged MODIFY and all REMOVE events are ignored
- Records with missing or malformed `reportedAt` are skipped; one bad record no longer fails the batch

- Station names are read from the DynamoDB stations table (`STATIONS_TABLE_NAME`) instead of the Chicago Data Portal; `CTA_STOPS_URL` is no longer used

### Added

- Per-platform dedupe receipts (`PROCESSED_REPORTS_TABLE_NAME`): claimed before posting, released if the post fails; a dedupe table error is reported via `batchItemFailures` (requires `ReportBatchItemFailures` on the event source mapping) so Lambda retries from that record
- Unit tests (`python -m unittest discover -s tests`), run in CI
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
