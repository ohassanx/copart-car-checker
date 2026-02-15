# Copart Car Checker

Monitors Copart UK for new car listings (all makes & models) matching specific criteria and sends Telegram notifications.

## Search Criteria

- **Category**: U (Undamaged/Unrecorded) ONLY
- **Make/Model**: All cars
- **Year**: 2020-2027
- **Transmission**: Automatic
- **Mileage**: 0-80,000 miles
- **Damage**: Minor or None
- **V5 Document**: Must have V5

## How It Works

1. Runs every 2 hours via GitHub Actions
2. Fetches current BMW listings from Copart UK
3. Compares with previously seen cars (stored in `seen_cars.json`)
4. Sends Telegram notification for any new cars
5. Updates the state file with current listings

## State Management

The `seen_cars.json` file stores car IDs that have been seen before. This file is automatically committed back to the repository after each run.

## Manual Testing

To test locally:

```bash
export BOT_TOKEN="your-bot-token"
export CHAT_ID="your-chat-id"
cd copart-bmw-checker
python3 check_cars.py
```

## Modifying Search Criteria

Edit the `SEARCH_PARAMS` in `check_cars.py` to change:
- Year range
- Mileage limits
- Transmission type
- Damage codes
- Other filters
