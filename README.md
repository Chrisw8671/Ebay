# eBay New Listings Watcher

A simple Python watcher for eBay listings that:

- polls eBay Browse API with `sort=newlyListed`
- tracks seen item IDs in a local state file
- prints only newly observed listings
- optionally posts alerts to Discord webhook

## Setup

1. Create an eBay Developer application and get **Production** keys.
2. Export environment variables:

```bash
export EBAY_CLIENT_ID="your-production-client-id"
export EBAY_CLIENT_SECRET="your-production-client-secret"
export EBAY_MARKETPLACE_ID="EBAY_GB"   # optional; default EBAY_GB
export POLL_INTERVAL="60"               # optional; default 60 seconds
export STATE_FILE="ebay_seen_items.json" # optional
export DISCORD_WEBHOOK_URL=""           # optional
```

3. Install dependency and run:

```bash
python -m pip install requests
python ebay_new_listings.py
```

## Configuration

Edit `WATCHES` in `ebay_new_listings.py`.

Each watch supports:

- `name`: label used for output/state
- `query`: eBay keyword query
- `limit`: number of results to fetch each poll
- `filter`: Browse API filter expression
- `category_ids` (optional): array of category IDs

Default watches include both fixed-price and auction items via:

```text
buyingOptions:{FIXED_PRICE|AUCTION}
```
