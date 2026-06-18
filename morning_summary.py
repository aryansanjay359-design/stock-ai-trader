# ==============================================================
# morning_summary.py
# Runs at 9am UK time via GitHub Actions
# Fetches market news + overnight price moves, asks Groq AI
# to summarise, sends a morning briefing via ntfy.sh
# ==============================================================

import os
import json
import requests
from datetime import datetime, timezone, timedelta

# ── API Keys ──────────────────────────────────────────────────
FINNHUB_KEY = os.environ.get("FINNHUB_KEY", "")
GROQ_KEY    = os.environ.get("GROQ_KEY", "")
NTFY_TOPIC  = os.environ.get("NTFY_TOPIC", "")

WATCHLIST = [
    # Tech giants
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMD", "AMZN",
    # Electric vehicles & energy
    "TSLA", "RIVN", "ENPH",
    # Finance
    "JPM", "GS", "V",
    # Healthcare & pharma
    "JNJ", "PFE", "LLY",
    # Consumer & retail
    "NFLX", "UBER", "SBUX",
    # Semiconductors & hardware
    "INTC", "QCOM", "ORCL",
    # Other high-growth
    "COIN", "PLTR", "SHOP", "SNOW", "ARM",
]

# ── Time ──────────────────────────────────────────────────────
uk_time   = datetime.now(timezone.utc) + timedelta(hours=1)
today     = uk_time.strftime("%d %b %Y")
today_api = uk_time.strftime("%Y-%m-%d")
yesterday = (uk_time - timedelta(days=1)).strftime("%Y-%m-%d")

print(f"Running morning summary for {today}...")

# ── Validate secrets ──────────────────────────────────────────
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
    except Exception:
        return None

def get_news(ticker):
    """Get last 24hrs of news for a ticker"""
    try:
        r    = requests.get(
            f"https://finnhub.io/api/v1/company-news"
            f"?symbol={ticker}&from={yesterday}&to={today_api}&token={FINNHUB_KEY}",
            timeout=8
        )
        news = r.json()
        return news[:3] if isinstance(news, list) else []
    except Exception:
        return []

def get_market_news():
    """Get general market news"""
    try:
        r    = requests.get(
            f"https://finnhub.io/api/v1/news?category=general&token={FINNHUB_KEY}",
            timeout=8
        )
        news = r.json()
        return news[:5] if isinstance(news, list) else []
    except Exception:
        return []

def send_notification(title, message, priority="default"):
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            headers={
                "Title":    title,
                "Priority": priority,
                "Tags":     "newspaper,sunrise",
            },
            data=message.encode("utf-8"),
            timeout=8,
        )
        print(f"Notification sent: {title}")
    except Exception as e:
        print(f"Notification failed: {e}")

# ==============================================================
# STEP 1 — Fetch overnight price moves
# ==============================================================

print("Fetching overnight price moves...")
price_lines = []

for ticker in WATCHLIST:
    q = get_quote(ticker)
    if q:
        change_pct = ((q["c"] - q["pc"]) / q["pc"] * 100) if q["pc"] else 0
        arrow      = "▲" if change_pct >= 0 else "▼"
        price_lines.append(
            f"  {ticker}: ${q['c']:.2f} {arrow} {change_pct:+.2f}% "
            f"(H ${q['h']:.2f} / L ${q['l']:.2f})"
        )

# ==============================================================
# STEP 2 — Fetch news headlines
# ==============================================================

print("Fetching market news...")
all_headlines = []

# General market news
market_news = get_market_news()
for article in market_news:
    headline = article.get("headline", "")
    if headline:
        all_headlines.append(f"[Market] {headline}")

# Stock-specific news (top 4 stocks only to stay within rate limits)
for ticker in WATCHLIST[:4]:
    news = get_news(ticker)
    for article in news:
        headline = article.get("headline", "")
        if headline:
            all_headlines.append(f"[{ticker}] {headline}")

print(f"Got {len(all_headlines)} headlines")

# ==============================================================
# STEP 3 — Ask Groq to write the morning briefing
# ==============================================================

print("Asking AI to summarise...")

prices_text    = "\n".join(price_lines) if price_lines else "No price data available."
headlines_text = "\n".join(all_headlines[:15]) if all_headlines else "No news available."

prompt = f"""
Today is {today}. You are writing a morning stock market briefing for a private investor.

OVERNIGHT PRICE MOVES:
{prices_text}

NEWS HEADLINES:
{headlines_text}

Write a concise morning briefing (max 200 words) covering:
1. Overall market mood (1 sentence)
2. Top 2-3 stories that matter today
3. One stock to watch and why
4. One sentence outlook for today's session

Keep it punchy, factual, and useful. No fluff.
"""

try:
    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {GROQ_KEY}",
            "Content-Type":  "application/json",
        },
        json={
            "model":       "llama-3.3-70b-versatile",
            "temperature": 0.4,
            "max_tokens":  400,
            "messages": [
                {
                    "role":    "system",
                    "content": "You are a sharp, concise financial journalist writing a morning briefing. Be direct and informative."
                },
                {"role": "user", "content": prompt}
            ],
        },
        timeout=30,
    )

    data = resp.json()

    if "error" in data:
        raise Exception(f"Groq error: {data['error'].get('message', str(data['error']))}")

    briefing = data["choices"][0]["message"]["content"].strip()
    print(f"AI briefing:\n{briefing}")

except Exception as e:
    print(f"AI summary failed: {e}")
    # Fall back to raw prices + headlines if AI fails
    briefing = (
        "AI summary unavailable today.\n\n"
        "PRICE MOVES:\n" + prices_text
    )

# ==============================================================
# STEP 4 — Send notification (split if too long)
# ==============================================================

# ntfy has a ~4000 char limit — split into 2 notifications if needed
full_message = (
    f"📅 {today}\n\n"
    f"{briefing}\n\n"
    f"── PRICES ──\n"
    f"{prices_text}\n\n"
    f"Open the app to trade."
)

if len(full_message) <= 3800:
    send_notification(
        title=f"Morning Briefing - {today}",
        message=full_message,
        priority="default",
    )
else:
    # Send in two parts
    send_notification(
        title=f"Morning Briefing - {today}",
        message=f"📅 {today}\n\n{briefing}",
        priority="default",
    )
    send_notification(
        title=f"Today's Prices - {today}",
        message=f"OVERNIGHT MOVES:\n{prices_text}",
        priority="low",
    )

print("Morning summary done.")
