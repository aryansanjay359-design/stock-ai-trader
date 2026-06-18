# ==============================================================
# scheduled_analysis.py
# Runs via GitHub Actions — fetches live prices, asks Groq AI
# to pick the best trade, sends push notification via ntfy.sh
# ==============================================================

import os
import json
import requests
from datetime import datetime, timezone, timedelta

# ── API Keys from GitHub Secrets ─────────────────────────────
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

# ── UK time ───────────────────────────────────────────────────
uk_time = datetime.now(timezone.utc) + timedelta(hours=1)  # BST (summer)
time_str = uk_time.strftime("%d %b %Y %H:%M")

print(f"Running scheduled analysis at {time_str} UK time...")

# ==============================================================
# VALIDATION
# ==============================================================

missing = []
if not FINNHUB_KEY: missing.append("FINNHUB_KEY")
if not GROQ_KEY:    missing.append("GROQ_KEY")
if not NTFY_TOPIC:  missing.append("NTFY_TOPIC")

if missing:
    print(f"ERROR: Missing secrets: {', '.join(missing)}")
    print("Add them in GitHub → Settings → Secrets and variables → Actions")
    exit(1)

# ==============================================================
# FINNHUB — get live quotes
# ==============================================================

def get_quote(ticker):
    try:
        url  = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_KEY}"
        r    = requests.get(url, timeout=8)
        data = r.json()
        if data.get("c", 0) > 0:
            return data
        return None
    except Exception as e:
        print(f"  Quote error for {ticker}: {e}")
        return None

print("Fetching live market data...")
market_lines = []
quotes_fetched = 0

for ticker in WATCHLIST:
    q = get_quote(ticker)
    if q:
        change_pct = ((q["c"] - q["pc"]) / q["pc"] * 100) if q["pc"] else 0
        line = (
            f"  {ticker}: price=${q['c']:.2f}, "
            f"change={change_pct:+.2f}%, "
            f"high=${q['h']:.2f}, low=${q['l']:.2f}"
        )
        market_lines.append(line)
        quotes_fetched += 1
        print(line)

if quotes_fetched == 0:
    print("ERROR: Could not fetch any market data. Check FINNHUB_KEY.")
    requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        headers={"Title": "⚠️ AI Trader — Data Error", "Priority": "default"},
        data="Could not fetch market data. Check your Finnhub key.".encode(),
        timeout=5,
    )
    exit(1)

print(f"Fetched data for {quotes_fetched} stocks.")

# ==============================================================
# GROQ AI — pick best trade
# ==============================================================

market_text = "\n".join(market_lines)
prompt = f"""
Live market data at {time_str}:

{market_text}

Pick the single best BUY opportunity from the tickers above.
You MUST respond with ONLY this JSON and nothing else — no markdown, no explanation:

{{"ticker":"AAPL","action":"BUY","shares":3,"price_per_share":213.45,"total_cost":640.35,"reasoning":"Brief reason using actual data.","risk":"Low"}}
"""

print("Running AI analysis...")

try:
    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {GROQ_KEY}",
            "Content-Type":  "application/json",
        },
        json={
            "model":       "llama-3.3-70b-versatile",
            "temperature": 0.1,
            "max_tokens":  300,
            "messages": [
                {
                    "role":    "system",
                    "content": "You are a stock trading AI. Respond ONLY with a single line of valid JSON. No markdown. No explanation. No newlines inside the JSON."
                },
                {"role": "user", "content": prompt}
            ],
        },
        timeout=30,
    )

    data = resp.json()

    if "error" in data:
        raise Exception(f"Groq error: {data['error'].get('message', str(data['error']))}")

    if "choices" not in data or not data["choices"]:
        raise Exception(f"Unexpected Groq response: {json.dumps(data)[:200]}")

    raw = data["choices"][0]["message"]["content"].strip()
    raw = raw.replace("```json", "").replace("```", "").strip()

    # Extract JSON even if there's surrounding text
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    if start == -1 or end == 0:
        raise Exception(f"No JSON found in response: {raw[:200]}")

    rec = json.loads(raw[start:end])
    print(f"AI recommendation: {json.dumps(rec, indent=2)}")

except Exception as e:
    print(f"AI analysis failed: {e}")
    requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        headers={"Title": "⚠️ AI Trader — Analysis Failed", "Priority": "default"},
        data=f"Scheduled analysis failed at {time_str}:\n{e}".encode(),
        timeout=5,
    )
    exit(1)

# ==============================================================
# NTFY — send push notification
# ==============================================================

ticker    = rec.get("ticker", "?")
shares    = rec.get("shares", 0)
price     = rec.get("price_per_share", 0)
cost      = rec.get("total_cost", 0)
reasoning = rec.get("reasoning", "")
risk      = rec.get("risk", "Unknown")
risk_icon = {"Low": "🟢", "Medium": "🟡", "High": "🔴"}.get(risk, "⚪")

message = (
    f"📊 {time_str}\n\n"
    f"Recommendation: BUY {shares} shares of {ticker}\n"
    f"Price: ${price:.2f} | Total: £{cost:.2f}\n"
    f"Risk: {risk_icon} {risk}\n\n"
    f"Reason: {reasoning}\n\n"
    f"Open the app to approve or reject."
)

print(f"Sending notification to ntfy topic: {NTFY_TOPIC}")

try:
    r = requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        headers={
            "Title":    f"📈 AI Alert: BUY {ticker}",
            "Priority": "high",
            "Tags":     "chart_increasing,robot",
        },
        data=message.encode("utf-8"),
        timeout=8,
    )
    print(f"Notification sent! Status: {r.status_code}")
except Exception as e:
    print(f"Notification failed: {e}")
    exit(1)

print("Done.")
