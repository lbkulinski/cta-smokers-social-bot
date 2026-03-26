# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
