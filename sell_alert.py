# ==============================================================
# sell_alert.py
# Runs every 30 mins during market hours via GitHub Actions
# Checks your holdings against sell conditions and notifies
# you immediately when it's a good time to sell
# ==============================================================

import os
import json
import requests
from datetime import datetime, timezone, timedelta

# ── API Keys ──────────────────────────────────────────────────
FINNHUB_KEY = os.environ.get("FINNHUB_KEY", "").strip()
GROQ_KEY    = os.environ.get("GROQ_KEY", "").strip()
NTFY_TOPIC  = os.environ.get("NTFY_TOPIC", "").strip()

# ── Portfolio file (in repo root) ─────────────────────────────
PORTFOLIO_FILE = "portfolio.json"

# ── Sell thresholds ───────────────────────────────────────────
TAKE_PROFIT_PCT  = 5.0   # Notify if up 5% or more from avg buy price
STOP_LOSS_PCT    = -3.0  # Notify if down 3% or more (protect from losses)
DAY_GAIN_PCT     = 3.0   # Notify if up 3%+ today alone (momentum peak)

# ── Time ──────────────────────────────────────────────────────
uk_time  = datetime.now(timezone.utc) + timedelta(hours=1)
time_str = uk_time.strftime("%d %b %Y %H:%M")

print(f"Running sell alert check at {time_str}...")

# ── Validate ──────────────────────────────────────────────────
missing = []
if not FINNHUB_KEY: missing.append("FINNHUB_KEY")
if not GROQ_KEY:    missing.append("GROQ_KEY")
if not NTFY_TOPIC:  missing.append("NTFY_TOPIC")

if missing:
    print(f"ERROR: Missing secrets: {', '.join(missing)}")
    exit(1)

# ==============================================================
# HELPERS
# ==============================================================

def get_quote(ticker):
    try:
        r    = requests.get(
            f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_KEY}",
            timeout=8
        )
        data = r.json()
        return data if data.get("c", 0) > 0 else None
    except Exception as e:
        print(f"  Quote error {ticker}: {e}")
        return None

def send_notification(title, message, priority="high"):
    try:
        r = requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            headers={
                "Title":        title,
                "Priority":     priority,
                "Tags":         "money_with_wings,rotating_light",
                "Content-Type": "text/plain; charset=utf-8",
            },
            data=message.encode("utf-8"),
            timeout=10,
        )
        print(f"Notification sent: {title} (status {r.status_code})")
        return r.status_code == 200
    except Exception as e:
        print(f"Notification failed: {e}")
        return False

def ask_ai_sell_opinion(ticker, shares, avg_price, curr_price, gain_pct, day_change_pct, reason):
    """Ask Groq AI for a brief sell recommendation"""
    try:
        prompt = f"""
A stock trader owns {shares} shares of {ticker}.
- Average buy price: ${avg_price:.2f}
- Current price: ${curr_price:.2f}
- Overall gain/loss: {gain_pct:+.2f}%
- Today's price change: {day_change_pct:+.2f}%
- Trigger reason: {reason}

In 2 sentences max, should they sell now or hold? Be direct and specific.
"""
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_KEY}",
                "Content-Type":  "application/json",
            },
            json={
                "model":       "llama-3.3-70b-versatile",
                "temperature": 0.2,
                "max_tokens":  100,
                "messages": [
                    {"role": "system", "content": "You are a concise stock trading advisor. Give direct, actionable advice in 2 sentences max."},
                    {"role": "user",   "content": prompt}
                ],
            },
            timeout=20,
        )
        data = resp.json()
        if "choices" in data:
            return data["choices"][0]["message"]["content"].strip()
        return "Could not get AI opinion."
    except Exception:
        return "Could not get AI opinion."

# ==============================================================
# LOAD PORTFOLIO
# ==============================================================

if not os.path.exists(PORTFOLIO_FILE):
    print("No portfolio.json found — no holdings to check.")
    exit(0)

try:
    with open(PORTFOLIO_FILE) as f:
        portfolio = json.load(f)
except Exception as e:
    print(f"Could not read portfolio: {e}")
    exit(0)

holdings = portfolio.get("holdings", {})

if not holdings:
    print("No holdings in portfolio — nothing to monitor.")
    exit(0)

print(f"Checking {len(holdings)} holdings: {', '.join(holdings.keys())}")

# ==============================================================
# CHECK EACH HOLDING
# ==============================================================

alerts_sent = 0

for ticker, info in holdings.items():
    avg_price  = info.get("avg_price", 0)
    shares     = info.get("shares", 0)
    cost_basis = info.get("cost_basis", 0)

    if avg_price == 0 or shares == 0:
        continue

    q = get_quote(ticker)
    if not q:
        print(f"  {ticker}: could not fetch quote, skipping")
        continue

    curr_price    = q["c"]
    prev_close    = q["pc"]
    day_change    = curr_price - prev_close
    day_change_pct = (day_change / prev_close * 100) if prev_close else 0
    overall_gain  = curr_price - avg_price
    overall_pct   = (overall_gain / avg_price * 100) if avg_price else 0
    curr_value    = curr_price * shares
    total_gain    = curr_value - cost_basis

    print(f"  {ticker}: curr=${curr_price:.2f}, avg=${avg_price:.2f}, "
          f"gain={overall_pct:+.2f}%, today={day_change_pct:+.2f}%")

    # ── Check sell conditions ─────────────────────────────────
    triggers = []

    if overall_pct >= TAKE_PROFIT_PCT:
        triggers.append(f"UP {overall_pct:.1f}% from your buy price (take profit target hit)")

    if overall_pct <= STOP_LOSS_PCT:
        triggers.append(f"DOWN {abs(overall_pct):.1f}% from your buy price (stop loss triggered)")

    if day_change_pct >= DAY_GAIN_PCT:
        triggers.append(f"UP {day_change_pct:.1f}% today alone (strong daily momentum)")

    if not triggers:
        print(f"  {ticker}: no sell signal")
        continue

    # ── Got a trigger — ask AI for opinion ───────────────────
    reason    = " | ".join(triggers)
    ai_opinion = ask_ai_sell_opinion(
        ticker, shares, avg_price, curr_price,
        overall_pct, day_change_pct, reason
    )

    # ── Determine urgency ─────────────────────────────────────
    is_stop_loss = overall_pct <= STOP_LOSS_PCT
    priority     = "urgent" if is_stop_loss else "high"
    alert_type   = "STOP LOSS" if is_stop_loss else "SELL OPPORTUNITY"

    # ── Build notification ────────────────────────────────────
    message = (
        f"Time: {time_str}\n\n"
        f"Ticker: {ticker}\n"
        f"Shares: {shares}\n"
        f"Your avg buy: ${avg_price:.2f}\n"
        f"Current price: ${curr_price:.2f}\n"
        f"Overall P&L: {overall_pct:+.2f}% (£{total_gain:+,.2f})\n"
        f"Today: {day_change_pct:+.2f}%\n\n"
        f"Why: {reason}\n\n"
        f"AI view: {ai_opinion}\n\n"
        f"Open the app to sell."
    )

    title = f"{alert_type}: {ticker} {overall_pct:+.1f}%"

    sent = send_notification(title, message, priority=priority)
    if sent:
        alerts_sent += 1

# ==============================================================
# SUMMARY
# ==============================================================

if alerts_sent == 0:
    print(f"No sell signals found across {len(holdings)} holdings. All good.")
else:
    print(f"Sent {alerts_sent} sell alert(s).")

print("Done.")
