#!/usr/bin/env python3
"""
eBay new-listing watcher.

Polls eBay Browse API with sort=newlyListed, stores seen item IDs, and emits
alerts only for newly observed listings.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
SCOPE = "https://api.ebay.com/oauth/api_scope"

MARKETPLACE_ID = os.getenv("EBAY_MARKETPLACE_ID", "EBAY_GB")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "60"))
STATE_FILE = Path(os.getenv("STATE_FILE", "ebay_seen_items.json"))
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()

WATCHES: list[dict[str, Any]] = [
    {
        "name": "ThinkPad bargains",
        "query": "thinkpad t14",
        "limit": 20,
        "filter": ",".join(
            [
                "price:[0..350]",
                "priceCurrency:GBP",
                "conditions:{NEW|USED}",
                "buyingOptions:{FIXED_PRICE|AUCTION}",
            ]
        ),
    },
    {
        "name": "Vintage Casio",
        "query": "casio vintage watch",
        "limit": 20,
        "filter": ",".join(
            [
                "price:[0..80]",
                "priceCurrency:GBP",
                "buyingOptions:{FIXED_PRICE|AUCTION}",
            ]
        ),
    },
]


@dataclass
class Token:
    access_token: str
    expires_at: float


class EbayWatcher:
    def __init__(self) -> None:
        self.client_id = os.getenv("EBAY_CLIENT_ID", "").strip()
        self.client_secret = os.getenv("EBAY_CLIENT_SECRET", "").strip()
        if not self.client_id or not self.client_secret:
            raise RuntimeError("Missing EBAY_CLIENT_ID or EBAY_CLIENT_SECRET environment variables.")

        self.token: Token | None = None
        self.session = requests.Session()
        self.state = self._load_state()

    def _load_state(self) -> dict[str, list[str]]:
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return {str(k): list(v) for k, v in data.items() if isinstance(v, list)}
            except Exception:
                pass
        return {}

    def _save_state(self) -> None:
        STATE_FILE.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding="utf-8")

    def _get_token(self) -> str:
        now = time.time()
        if self.token and now < self.token.expires_at - 60:
            return self.token.access_token

        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode("utf-8")).decode("ascii")

        resp = self.session.post(
            TOKEN_URL,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {basic}",
            },
            data={"grant_type": "client_credentials", "scope": SCOPE},
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()

        access_token = payload["access_token"]
        expires_in = int(payload.get("expires_in", 7200))
        self.token = Token(access_token=access_token, expires_at=now + expires_in)
        return access_token

    def search(self, watch: dict[str, Any]) -> list[dict[str, Any]]:
        token = self._get_token()
        params: dict[str, str] = {
            "q": watch["query"],
            "sort": "newlyListed",
            "limit": str(watch.get("limit", 20)),
        }
        if watch.get("filter"):
            params["filter"] = watch["filter"]
        if watch.get("category_ids"):
            params["category_ids"] = ",".join(watch["category_ids"])

        resp = self.session.get(
            SEARCH_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": MARKETPLACE_ID,
            },
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        return payload.get("itemSummaries", [])

    def get_new_items(self, watch: dict[str, Any]) -> list[dict[str, Any]]:
        watch_name = watch["name"]
        seen_ids = set(self.state.get(watch_name, []))

        items = self.search(watch)
        new_items: list[dict[str, Any]] = []
        current_ids: list[str] = []

        for item in items:
            item_id = item.get("itemId")
            if not item_id:
                continue
            current_ids.append(item_id)
            if item_id not in seen_ids:
                new_items.append(item)

        combined = current_ids + self.state.get(watch_name, [])
        deduped: list[str] = []
        added = set()
        for item_id in combined:
            if item_id not in added:
                added.add(item_id)
                deduped.append(item_id)

        self.state[watch_name] = deduped[:500]
        self._save_state()
        return new_items

    def notify_discord(self, message: str) -> None:
        if not DISCORD_WEBHOOK_URL:
            return
        try:
            response = self.session.post(
                DISCORD_WEBHOOK_URL,
                json={"content": message[:1900]},
                timeout=15,
            )
            response.raise_for_status()
        except Exception as exc:
            print(f"[warn] Discord notify failed: {exc}", file=sys.stderr)

    @staticmethod
    def format_item(item: dict[str, Any], watch_name: str) -> str:
        title = item.get("title", "(no title)")
        item_web_url = item.get("itemWebUrl", "")
        price_obj = item.get("price") or {}
        price = price_obj.get("value")
        currency = price_obj.get("currency")
        condition = item.get("condition", "Unknown")
        origin_date = item.get("itemOriginDate", "Unknown time")

        price_str = f"{price} {currency}" if price and currency else "No price"
        return (
            f"[{watch_name}] {title}\n"
            f"Price: {price_str}\n"
            f"Condition: {condition}\n"
            f"Listed: {origin_date}\n"
            f"{item_web_url}"
        )

    def run_forever(self) -> None:
        print(f"Watching {len(WATCHES)} searches on {MARKETPLACE_ID}")
        print(f"Polling every {POLL_INTERVAL} seconds")
        print("Press Ctrl+C to stop\n")

        while True:
            try:
                for watch in WATCHES:
                    new_items = self.get_new_items(watch)
                    if new_items:
                        print(f"=== {watch['name']} | {len(new_items)} new item(s) ===")
                        for item in reversed(new_items):
                            msg = self.format_item(item, watch["name"])
                            print(msg)
                            print("-" * 80)
                            self.notify_discord(msg)
                    else:
                        print(f"[{watch['name']}] no new items")
                time.sleep(POLL_INTERVAL)

            except KeyboardInterrupt:
                print("\nStopped.")
                return
            except requests.HTTPError as exc:
                body = ""
                try:
                    body = exc.response.text[:1000]
                except Exception:
                    pass
                print(f"[http error] {exc}\n{body}", file=sys.stderr)
                time.sleep(min(POLL_INTERVAL, 60))
            except Exception as exc:
                print(f"[error] {exc}", file=sys.stderr)
                time.sleep(min(POLL_INTERVAL, 60))


if __name__ == "__main__":
    EbayWatcher().run_forever()
