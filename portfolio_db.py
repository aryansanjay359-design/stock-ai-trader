# ==============================================================
# portfolio_db.py — shared by all GitHub Actions scripts
# Reads/writes portfolio to JSONBin.io cloud storage
# ==============================================================

import os
import json
import requests
from datetime import datetime

JSONBIN_URL       = "https://api.jsonbin.io/v3/b"
DEFAULT_PORTFOLIO = {"cash": 10000.0, "holdings": {}, "history": []}

def _creds():
    return (
        os.environ.get("JSONBIN_BIN_ID",  "").strip(),
        os.environ.get("JSONBIN_API_KEY", "").strip(),
    )

def load_portfolio():
    bin_id, api_key = _creds()
    if not bin_id or not api_key:
        print("WARNING: JSONBIN credentials not set — using empty portfolio")
        return DEFAULT_PORTFOLIO.copy()
    try:
        r = requests.get(
            f"{JSONBIN_URL}/{bin_id}/latest",
            headers={"X-Master-Key": api_key},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json().get("record", DEFAULT_PORTFOLIO.copy())
            data.setdefault("cash",     10000.0)
            data.setdefault("holdings", {})
            data.setdefault("history",  [])
            return data
        print(f"JSONBin load failed: {r.status_code} — {r.text[:100]}")
        return DEFAULT_PORTFOLIO.copy()
    except Exception as e:
        print(f"JSONBin load error: {e}")
        return DEFAULT_PORTFOLIO.copy()

def save_portfolio(portfolio):
    bin_id, api_key = _creds()
    if not bin_id or not api_key:
        print("WARNING: Cannot save — no JSONBin credentials")
        return False
    try:
        r = requests.put(
            f"{JSONBIN_URL}/{bin_id}",
            headers={"X-Master-Key": api_key, "Content-Type": "application/json"},
            json=portfolio,
            timeout=10,
        )
        return r.status_code == 200
    except Exception as e:
        print(f"JSONBin save error: {e}")
        return False

def record_trade(portfolio, action, ticker, shares, price, total, reasoning=""):
    portfolio["history"].append({
        "date":      datetime.now().isoformat(),
        "action":    action,
        "ticker":    ticker,
        "shares":    shares,
        "price":     price,
        "total":     total,
        "reasoning": reasoning,
    })
