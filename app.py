# ==============================================================
# AI Stock Trader — Complete App
# Uses Finnhub for live stock data + Groq AI for recommendations
# Push notifications via ntfy.sh
# Paper trading with £10,000 dummy money
# ==============================================================

import streamlit as st
import requests
import json
import os
from datetime import datetime, timedelta

# ── Page config (must be first Streamlit call) ────────────────
st.set_page_config(
    page_title="AI Stock Trader",
    page_icon="📈",
    layout="wide"
)

# ── API Keys (loaded from Streamlit Secrets) ──────────────────
try:
    FINNHUB_KEY = st.secrets["FINNHUB_KEY"]
    GROQ_KEY    = st.secrets["GROQ_KEY"]
    NTFY_TOPIC  = st.secrets["NTFY_TOPIC"]
except Exception:
    FINNHUB_KEY = os.getenv("FINNHUB_KEY", "")
    GROQ_KEY    = os.getenv("GROQ_KEY", "")
    NTFY_TOPIC  = os.getenv("NTFY_TOPIC", "")

# ── Watchlist ─────────────────────────────────────────────────
WATCHLIST = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "AMD"]

# ── Portfolio file ────────────────────────────────────────────
PORTFOLIO_FILE = "portfolio.json"

# ==============================================================
# PUSH NOTIFICATIONS (ntfy.sh — free, no account needed)
# ==============================================================

def send_notification(title, message, priority="high"):
    """Send a push notification via ntfy.sh to your phone"""
    if not NTFY_TOPIC:
        return False
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            headers={
                "Title":    title,
                "Priority": priority,
                "Tags":     "chart_increasing,robot",
            },
            data=message.encode("utf-8"),
            timeout=5,
        )
        return True
    except Exception:
        return False

# ==============================================================
# PORTFOLIO HELPERS
# ==============================================================

def load_portfolio():
    default = {"cash": 10000.0, "holdings": {}, "history": []}
    if os.path.exists(PORTFOLIO_FILE):
        try:
            with open(PORTFOLIO_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return default

def save_portfolio(p):
    with open(PORTFOLIO_FILE, "w") as f:
        json.dump(p, f, indent=2)

# ==============================================================
# FINNHUB API HELPERS
# ==============================================================

def get_quote(ticker):
    """Returns dict with c=current, pc=prev close, h=high, l=low, o=open"""
    try:
        url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_KEY}"
        r   = requests.get(url, timeout=6)
        data = r.json()
        if data.get("c", 0) > 0:
            return data
        return None
    except Exception:
        return None

def get_candles(ticker, days=30):
    """Returns list of daily OHLCV candles for the past N days"""
    try:
        end   = int(datetime.now().timestamp())
        start = int((datetime.now() - timedelta(days=days + 5)).timestamp())
        url   = (
            f"https://finnhub.io/api/v1/stock/candle"
            f"?symbol={ticker}&resolution=D&from={start}&to={end}&token={FINNHUB_KEY}"
        )
        r    = requests.get(url, timeout=8)
        data = r.json()
        if data.get("s") == "ok":
            candles = []
            for i in range(len(data["t"])):
                candles.append({
                    "date":   datetime.fromtimestamp(data["t"][i]).strftime("%d %b"),
                    "open":   data["o"][i],
                    "high":   data["h"][i],
                    "low":    data["l"][i],
                    "close":  data["c"][i],
                    "volume": data["v"][i],
                })
            return candles[-days:]
        return []
    except Exception:
        return []

def get_company_news(ticker):
    """Returns recent news headlines for a ticker"""
    try:
        to_date   = datetime.now().strftime("%Y-%m-%d")
        from_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        url = (
            f"https://finnhub.io/api/v1/company-news"
            f"?symbol={ticker}&from={from_date}&to={to_date}&token={FINNHUB_KEY}"
        )
        r    = requests.get(url, timeout=6)
        news = r.json()
        return news[:5] if isinstance(news, list) else []
    except Exception:
        return []

# ==============================================================
# AI ADVISOR (Groq — free)
# ==============================================================

def run_ai_analysis(portfolio):
    """Ask Groq AI to pick the best stock to buy right now"""
    if not GROQ_KEY:
        return None, "No Groq API key set."

    lines = ["Current market data:\n"]
    for ticker in WATCHLIST:
        q = get_quote(ticker)
        if q:
            change_pct = ((q["c"] - q["pc"]) / q["pc"] * 100) if q["pc"] else 0
            lines.append(
                f"  {ticker}: price=${q['c']:.2f}, "
                f"today change={change_pct:+.2f}%, "
                f"high=${q['h']:.2f}, low=${q['l']:.2f}"
            )

    cash     = portfolio.get("cash", 0)
    holdings = portfolio.get("holdings", {})
    owned    = ", ".join(holdings.keys()) if holdings else "none"

    market_text = "\n".join(lines)
    user_msg = f"""
{market_text}

Investor's available cash: £{cash:.2f}
Currently owns: {owned}

Pick the single best BUY opportunity from the tickers above.
Consider: price momentum, day range position, and diversification.
Reply with ONLY valid JSON, no extra text, no markdown:

{{
  "ticker": "AAPL",
  "action": "BUY",
  "shares": 3,
  "price_per_share": 213.45,
  "total_cost": 640.35,
  "reasoning": "2-3 sentence explanation with specific data.",
  "risk": "Low"
}}
"""

    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_KEY}",
                "Content-Type":  "application/json",
            },
            json={
                "model": "llama3-8b-8192",
                "messages": [
                    {
                        "role":    "system",
                        "content": "You are an expert stock market analyst. You ONLY respond with valid JSON. No markdown. No explanation outside JSON."
                    },
                    {
                        "role":    "user",
                        "content": user_msg
                    }
                ],
                "temperature": 0.3,
                "max_tokens":  500,
            },
            timeout=30,
        )
        data = resp.json()
        raw  = data["choices"][0]["message"]["content"].strip()
        raw  = raw.replace("```json", "").replace("```", "").strip()
        rec  = json.loads(raw)
        return rec, None
    except Exception as e:
        return None, str(e)

# ==============================================================
# SIDEBAR
# ==============================================================

portfolio            = load_portfolio()
cash                 = portfolio["cash"]
holdings             = portfolio["holdings"]

total_holdings_value = 0.0
for ticker, info in holdings.items():
    q = get_quote(ticker)
    if q:
        total_holdings_value += q["c"] * info["shares"]

total_value = cash + total_holdings_value

st.sidebar.title("📈 AI Stock Trader")
st.sidebar.caption("Paper trading · Finnhub + Groq AI")
st.sidebar.divider()
st.sidebar.metric("💷 Cash",            f"£{cash:,.2f}")
st.sidebar.metric("📦 Holdings Value",  f"£{total_holdings_value:,.2f}")
st.sidebar.metric("💼 Total Portfolio", f"£{total_value:,.2f}")
profit = total_value - 10000
st.sidebar.metric("📊 Total P&L", f"£{profit:+,.2f}", delta=f"{profit/100:.1f}%")
st.sidebar.divider()

page = st.sidebar.radio(
    "Go to",
    ["🏠 Dashboard", "🤖 AI Advisor", "📋 My Portfolio", "📜 Trade History", "⚙️ Settings"]
)

# ==============================================================
# DASHBOARD
# ==============================================================

if page == "🏠 Dashboard":
    st.title("🏠 Market Dashboard")
    st.caption(f"Live data from Finnhub · {datetime.now().strftime('%d %b %Y, %H:%M')}")

    if not FINNHUB_KEY:
        st.error("⚠️ No Finnhub API key found. Go to ⚙️ Settings to check your setup.")
        st.stop()

    col_refresh = st.columns([5, 1])[1]
    with col_refresh:
        if st.button("🔄 Refresh"):
            st.rerun()

    st.subheader("Watchlist")
    cols = st.columns(4)
    for i, ticker in enumerate(WATCHLIST):
        q = get_quote(ticker)
        with cols[i % 4]:
            if q:
                change     = q["c"] - q["pc"]
                change_pct = (change / q["pc"] * 100) if q["pc"] else 0
                st.metric(
                    label=ticker,
                    value=f"${q['c']:,.2f}",
                    delta=f"{change_pct:+.2f}%"
                )
                st.caption(f"H ${q['h']:.2f}  L ${q['l']:.2f}")
            else:
                st.metric(label=ticker, value="—")
                st.caption("No data")

    st.divider()
    st.subheader("Price Chart")
    selected = st.selectbox("Choose a stock", WATCHLIST)
    period   = st.radio("Period", ["7 days", "30 days", "90 days"], horizontal=True)
    days_map = {"7 days": 7, "30 days": 30, "90 days": 90}
    candles  = get_candles(selected, days=days_map[period])

    if candles:
        import pandas as pd
        df = pd.DataFrame(candles)
        st.line_chart(df.set_index("date")["close"], use_container_width=True)
        with st.expander("Show OHLCV table"):
            st.dataframe(df, use_container_width=True)
    else:
        st.info("No chart data available for this ticker right now.")

    st.divider()
    st.subheader(f"Latest News: {selected}")
    news = get_company_news(selected)
    if news:
        for article in news:
            st.markdown(f"**[{article.get('headline', 'No title')}]({article.get('url', '#')})**")
            st.caption(
                f"{article.get('source', '')} · "
                f"{datetime.fromtimestamp(article.get('datetime', 0)).strftime('%d %b %Y')}"
            )
            st.write(article.get("summary", "")[:200] + "...")
            st.divider()
    else:
        st.info("No recent news found.")

# ==============================================================
# AI ADVISOR
# ==============================================================

elif page == "🤖 AI Advisor":
    st.title("🤖 AI Investment Advisor")
    st.caption("The AI scans the market and picks the best opportunity. **Nothing trades without your approval.**")

    if not FINNHUB_KEY or not GROQ_KEY:
        st.error("⚠️ API keys missing. Go to ⚙️ Settings.")
        st.stop()

    st.info(
        "Click the button below. The AI will analyse all stocks on your watchlist "
        "and recommend the single best trade right now."
    )

    if st.button("🔎 Run AI Analysis Now", type="primary", use_container_width=True):
        with st.spinner("Fetching live market data and running AI analysis..."):
            rec, err = run_ai_analysis(portfolio)
        if err:
            st.error(f"AI analysis failed: {err}")
        elif rec:
            st.session_state["pending_rec"] = rec
            # ── Send push notification ──────────────────────
            notif_sent = send_notification(
                title=f"📈 AI Trade Alert: {rec['action']} {rec['ticker']}",
                message=(
                    f"{rec['shares']} shares @ ${rec.get('price_per_share', 0):.2f}\n"
                    f"Total: £{rec['total_cost']:.2f}\n"
                    f"Risk: {rec.get('risk', 'Unknown')}\n"
                    f"{rec['reasoning']}\n\n"
                    f"Open the app to approve or reject."
                ),
            )
            if notif_sent:
                st.success("📱 Push notification sent to your phone!")
            elif NTFY_TOPIC:
                st.warning("Notification failed — check your NTFY_TOPIC in Secrets.")

    rec = st.session_state.get("pending_rec")
    if rec:
        st.divider()
        st.subheader("📬 AI Recommendation — Awaiting Your Decision")

        col1, col2 = st.columns([3, 1])
        with col1:
            risk_colour = {"Low": "🟢", "Medium": "🟡", "High": "🔴"}.get(rec.get("risk", ""), "⚪")
            st.markdown(f"### {rec['action']} **{rec['ticker']}**")
            st.markdown(
                f"**Shares:** {rec['shares']}  |  "
                f"**Price:** ${rec.get('price_per_share', 0):,.2f}  |  "
                f"**Total cost:** £{rec['total_cost']:,.2f}"
            )
            st.markdown(f"**Risk:** {risk_colour} {rec.get('risk', 'Unknown')}")
            st.markdown(f"**AI Reasoning:**  \n{rec['reasoning']}")

        with col2:
            q = get_quote(rec["ticker"])
            if q:
                st.metric("Live Price", f"${q['c']:,.2f}")
            st.metric("Cash After Trade", f"£{cash - rec['total_cost']:,.2f}")

        st.warning("⚠️ This uses **dummy paper money** only. Review carefully before approving.")

        col_yes, col_no = st.columns(2)
        with col_yes:
            if st.button("✅ APPROVE TRADE", type="primary", use_container_width=True):
                if rec["total_cost"] > portfolio["cash"]:
                    st.error("Not enough cash!")
                else:
                    portfolio["cash"] -= rec["total_cost"]
                    ticker = rec["ticker"]
                    if ticker in portfolio["holdings"]:
                        existing     = portfolio["holdings"][ticker]
                        total_shares = existing["shares"] + rec["shares"]
                        total_cost   = existing["cost_basis"] + rec["total_cost"]
                        portfolio["holdings"][ticker] = {
                            "shares":     total_shares,
                            "cost_basis": total_cost,
                            "avg_price":  total_cost / total_shares,
                        }
                    else:
                        portfolio["holdings"][ticker] = {
                            "shares":     rec["shares"],
                            "cost_basis": rec["total_cost"],
                            "avg_price":  rec.get("price_per_share", 0),
                        }
                    portfolio["history"].append({
                        "date":      datetime.now().isoformat(),
                        "action":    "BUY",
                        "ticker":    ticker,
                        "shares":    rec["shares"],
                        "price":     rec.get("price_per_share", 0),
                        "total":     rec["total_cost"],
                        "reasoning": rec["reasoning"],
                    })
                    save_portfolio(portfolio)
                    # Notify on approval
                    send_notification(
                        title=f"✅ Trade Approved: BUY {ticker}",
                        message=f"Bought {rec['shares']} shares of {ticker} for £{rec['total_cost']:.2f}",
                        priority="default",
                    )
                    del st.session_state["pending_rec"]
                    st.success(f"✅ Trade approved! Bought {rec['shares']} shares of {ticker}.")
                    st.rerun()

        with col_no:
            if st.button("❌ REJECT", use_container_width=True):
                send_notification(
                    title=f"❌ Trade Rejected: {rec['ticker']}",
                    message="You rejected the AI's recommendation. No trade was made.",
                    priority="low",
                )
                del st.session_state["pending_rec"]
                st.info("Trade rejected. No action taken.")
                st.rerun()

# ==============================================================
# MY PORTFOLIO
# ==============================================================

elif page == "📋 My Portfolio":
    st.title("📋 My Portfolio")

    col1, col2, col3 = st.columns(3)
    col1.metric("💷 Cash",         f"£{cash:,.2f}")
    col2.metric("📦 Holdings",     f"£{total_holdings_value:,.2f}")
    col3.metric("💼 Total Value",  f"£{total_value:,.2f}")

    st.divider()

    if holdings:
        st.subheader("Current Holdings")
        for ticker, info in holdings.items():
            q          = get_quote(ticker)
            curr_price = q["c"] if q else info["avg_price"]
            curr_value = curr_price * info["shares"]
            gain       = curr_value - info["cost_basis"]
            gain_pct   = (gain / info["cost_basis"] * 100) if info["cost_basis"] else 0
            colour     = "🟢" if gain >= 0 else "🔴"

            c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1, 1])
            c1.markdown(f"**{ticker}**")
            c2.write(f"{info['shares']} shares")
            c3.write(f"Avg £{info['avg_price']:.2f}")
            c4.write(f"Now £{curr_value:,.2f}")
            c5.markdown(f"{colour} £{gain:+,.2f} ({gain_pct:+.1f}%)")

            if st.button(f"Sell {ticker}", key=f"sell_{ticker}"):
                if q:
                    proceeds = q["c"] * info["shares"]
                    portfolio["cash"] += proceeds
                    del portfolio["holdings"][ticker]
                    portfolio["history"].append({
                        "date":      datetime.now().isoformat(),
                        "action":    "SELL",
                        "ticker":    ticker,
                        "shares":    info["shares"],
                        "price":     q["c"],
                        "total":     proceeds,
                        "reasoning": "Manual sell by user",
                    })
                    save_portfolio(portfolio)
                    send_notification(
                        title=f"💰 Sold {ticker}",
                        message=f"Sold {info['shares']} shares of {ticker} for £{proceeds:.2f}",
                        priority="default",
                    )
                    st.success(f"Sold {info['shares']} shares of {ticker} for £{proceeds:,.2f}")
                    st.rerun()
                else:
                    st.error("Could not fetch current price to sell.")
    else:
        st.info("No holdings yet. Head to the AI Advisor to get your first recommendation!")

    st.divider()
    if st.button("🔄 Reset Portfolio to £10,000", type="secondary"):
        save_portfolio({"cash": 10000.0, "holdings": {}, "history": []})
        st.success("Portfolio reset to £10,000!")
        st.rerun()

# ==============================================================
# TRADE HISTORY
# ==============================================================

elif page == "📜 Trade History":
    st.title("📜 Trade History")
    history = portfolio.get("history", [])

    if history:
        for trade in reversed(history):
            date_str = datetime.fromisoformat(trade["date"]).strftime("%d %b %Y  %H:%M")
            emoji    = "🟢 BUY" if trade["action"] == "BUY" else "🔴 SELL"
            with st.expander(f"{emoji}  {trade['ticker']}  ·  {date_str}  ·  £{trade['total']:,.2f}"):
                st.write(f"**Shares:** {trade['shares']}  |  **Price:** £{trade['price']:,.2f}  |  **Total:** £{trade['total']:,.2f}")
                st.write(f"**Reason:** {trade.get('reasoning', '—')}")
    else:
        st.info("No trades yet.")

# ==============================================================
# SETTINGS
# ==============================================================

elif page == "⚙️ Settings":
    st.title("⚙️ Settings & Setup")

    st.subheader("API Key Status")
    st.write("🔑 **Finnhub Key:**", "✅ Set" if FINNHUB_KEY else "❌ Missing")
    st.write("🔑 **Groq Key:**",    "✅ Set" if GROQ_KEY    else "❌ Missing")
    st.write("🔔 **Ntfy Topic:**",  "✅ Set" if NTFY_TOPIC  else "❌ Missing — notifications won't work")

    st.divider()
    st.subheader("📱 Setting up push notifications (ntfy.sh)")
    st.markdown("""
**Step 1 — Install the ntfy app on your phone:**
- iPhone: search **ntfy** on the App Store
- Android: search **ntfy** on the Play Store

**Step 2 — Choose a unique topic name**

Pick something unique that only you know, for example:
`johns-trader-x7k29`  *(make up your own — don't use this one)*

**Step 3 — Subscribe in the app**
- Open the ntfy app on your phone
- Tap **+** → type your topic name → Subscribe

**Step 4 — Add it to Streamlit Secrets**
```toml
NTFY_TOPIC = "your-unique-topic-name"
```

That's it — you'll now get a notification on your phone every time the AI finds a trade!
    """)

    st.divider()
    st.subheader("All Streamlit Secrets (copy and paste this)")
    st.code("""
FINNHUB_KEY = "your_finnhub_key_here"
GROQ_KEY    = "your_groq_key_here"
NTFY_TOPIC  = "your-unique-topic-name"
    """, language="toml")

    st.divider()
    st.subheader("Test notification")
    if st.button("📱 Send test notification to my phone"):
        sent = send_notification(
            title="✅ Test from AI Stock Trader",
            message="Notifications are working! You'll receive alerts when the AI finds a trade.",
            priority="default",
        )
        if sent:
            st.success("Test notification sent! Check your phone.")
        else:
            st.error("Failed — make sure NTFY_TOPIC is set in your Streamlit Secrets.")

    st.divider()
    st.subheader("Watchlist")
    st.write("Current watchlist:", ", ".join(WATCHLIST))
    st.info("To change the watchlist, edit the WATCHLIST variable at the top of app.py.")
