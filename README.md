# CTA Smokers Social Bot

An AWS Lambda bot that automatically posts reports of smoking incidents on Chicago CTA trains to Twitter, Bluesky, Mastodon, and Threads.

## How It Works

The bot is triggered by [DynamoDB Streams](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Streams.html) whenever a new smoking incident is inserted into the incidents table. For each new record, it:

1. Deserializes the DynamoDB event payload
2. Looks up the station name from the [Chicago Data Portal](https://data.cityofchicago.org/resource/8pix-ypme.json)
3. Formats a post with line, destination, next stop, car number, and run number
4. Publishes the post to all four social platforms concurrently

A failure on any single platform does not block the others.

## Architecture

- **Compute:** AWS Lambda (Python 3)
- **Trigger:** DynamoDB Streams (INSERT events)
- **Secrets:** AWS Secrets Manager
- **Station data:** Chicago Data Portal CTA Stops API (cached at cold start)

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
| `CTA_STOPS_URL` | Chicago Data Portal CTA Stops API URL |

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

## Deployment

Dependencies are listed in `requirements.txt`. Build the deployment package:

```bash
pip install -r requirements.txt -t package/
cd package && zip -r ../lambda.zip . && cd ..
zip lambda.zip lambda_function.py
```

Upload `lambda.zip` to your Lambda function.

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
