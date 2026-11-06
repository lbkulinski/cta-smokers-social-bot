# CTA Smokers Social Bot

An AWS Lambda bot that automatically posts reports of smoking incidents on Chicago CTA trains to Twitter, Bluesky, Mastodon, and Threads.

## How It Works

The bot is triggered by [DynamoDB Streams](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Streams.html) whenever a new smoking report is written to the reports table (one item per car number and line, keyed by `carNumberLine`). A new report is an `INSERT`, or a `MODIFY` whose `reportedAt` differs from the old image's (a resubmit over an expired item). `REMOVE` events (TTL or manual) are ignored. Records with a missing or malformed `reportedAt` are skipped. For each new report, it:

1. Deserializes the DynamoDB event payload
2. Looks up the station name by map ID in the CTA train stations DynamoDB table
3. Formats a post with line, destination, next stop, car number, and run number
4. Publishes the post to all four social platforms concurrently

A failure on any single platform does not block the others.

The handler uses [partial batch responses](https://docs.aws.amazon.com/lambda/latest/dg/services-ddb-batchfailurereporting.html): if the dedupe table is unavailable it returns that record's sequence number in `batchItemFailures` and stops, so Lambda retries from there. The event source mapping must set `FunctionResponseTypes` to `["ReportBatchItemFailures"]`.

### Delivery guarantees

Stream delivery is at least once, so the function claims a receipt before acting. This favors skipping over duplicating: a report is never acted on twice, but it can be skipped if the function is killed between the claim and the action, or if releasing the receipt after a failed action also fails. Receipts expire after 7 days. This is an accepted trade-off.

## Architecture

- **Compute:** AWS Lambda (Python 3)
- **Trigger:** DynamoDB Streams (`NEW_AND_OLD_IMAGES`; INSERT and MODIFY events must reach the function)
- **Secrets:** AWS Secrets Manager
- **Station data:** DynamoDB stations table (`mapId` partition key), queried per station and cached per container
- **Dedupe:** DynamoDB receipts table; one conditional put per report and platform before posting

## Supported Lines

RED, BLUE, BROWN, GREEN, ORANGE, PINK, PURPLE, YELLOW

## Social Platforms

| Platform | API |
|----------|-----|
| Twitter  | Twitter API v2 (OAuth 1.0) |
| Bluesky  | AT Protocol XRPC |
| Mastodon | Mastodon API (mastodon.social) |
| Threads  | Meta Graph API v1.0 |

## Environment Variables

The following environment variables must be set on the Lambda function:

| Key | Description |
|-----|-------------|
| `SECRETS_MANAGER_SECRET_ID` | AWS Secrets Manager secret ID containing API credentials |
| `STATIONS_TABLE_NAME` | DynamoDB stations table (partition key `mapId`, sort key `stopId`, attribute `name`); needs `dynamodb:Query` |
| `PROCESSED_REPORTS_TABLE_NAME` | Receipts table (`reportKey` S partition key, TTL attribute `ttl`); needs `dynamodb:PutItem` and `dynamodb:DeleteItem` |

### Secrets

The following credentials must be present in the Secrets Manager secret:

| Key | Description |
|-----|-------------|
| `BLUESKY_HANDLE` | Bluesky account handle |
| `BLUESKY_APP_PASSWORD` | Bluesky app password |
| `TWITTER_CONSUMER_KEY` | Twitter API consumer key |
| `TWITTER_CONSUMER_SECRET` | Twitter API consumer secret |
| `TWITTER_ACCESS_TOKEN` | Twitter access token |
| `TWITTER_ACCESS_TOKEN_SECRET` | Twitter access token secret |
| `THREADS_USER_ID` | Threads/Meta user ID |
| `THREADS_ACCESS_TOKEN` | Threads access token |
| `MASTODON_ACCESS_TOKEN` | Mastodon access token |
| `DISCORD_WEBHOOK_URL` | Discord webhook URL |
| `THREADS_TOKEN_LAST_REFRESHED` | Optional. ISO-8601 time the Threads token was last refreshed. The function sets it itself when it refreshes the token (and writes the new token back to the secret, so the role also needs `secretsmanager:PutSecretValue`) |

## Deployment

Dependencies are listed in `requirements.txt`. Build the deployment package:

```bash
pip install -r requirements.txt -t package/
cp lambda_function.py package/
cd package && zip -r ../lambda.zip . && cd ..
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

## CI/CD

- `.github/workflows/ci.yml` runs `ruff` and `pytest` on pull requests to `main` (Python 3.12).
- `.github/workflows/deploy.yml` runs CI (lint and tests), then updates the Lambda's code (dependencies from `requirements.txt` are bundled into `lambda.zip`). It runs on every push to `main` and can also be run manually. It only updates code; environment variables, tables, IAM and the event source mapping are managed elsewhere.
- `.github/dependabot.yml` checks the Python dependencies and the workflow actions weekly.

Deploy setup (repository settings):

| Kind | Name | Description |
|---|---|---|
| Variable | `AWS_ROLE_ARN` | IAM role GitHub assumes via OIDC. Needs `lambda:UpdateFunctionCode` and `lambda:GetFunctionConfiguration` on the function (the latter is used by the post-deploy `aws lambda wait function-updated` step). Because the deploy job runs in the `production` environment, the role's trust policy must allow the subject `repo:lbkulinski/cta-smokers-social-bot:environment:production` |
| Variable | `AWS_REGION` | Region of the Lambda |
| Variable | `LAMBDA_FUNCTION_NAME` | Name of the Lambda function |
| Environment | `production` | The deploy job runs in this environment. Optionally add required reviewers as an approval gate |

## Post Format

```
🚬 Red Line to 95th/Dan Ryan

Next Stop: Clark/Lake
Car: 1234 · Run: 101
```

Run number is optional and omitted when unavailable:

```
🚬 Blue Line to O'Hare

Next Stop: Pulaski
Car: 7109
```

## License

[MIT](LICENSE)
