# ==============================================================
# AI Stock Trader — Complete App
# Finnhub (live data) + Groq AI (recommendations)
# ntfy.sh (push notifications) + Full manual buy/sell
# ==============================================================

import streamlit as st
import requests
import json
import os
import pandas as pd
from datetime import datetime, timedelta

# ── Page config ───────────────────────────────────────────────
st.set_page_config(
    page_title="AI Stock Trader",
    page_icon="📈",
    layout="wide"
)

# ── API Keys — each loaded individually so one missing key
#    doesn't crash the whole app ───────────────────────────────
def _secret(key):
    try:
        return st.secrets[key]
    except Exception:
        return os.getenv(key, "")

FINNHUB_KEY = _secret("FINNHUB_KEY")
GROQ_KEY    = _secret("GROQ_KEY")
NTFY_TOPIC  = _secret("NTFY_TOPIC")

# ── Watchlist ─────────────────────────────────────────────────
WATCHLIST = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "AMD"]

# ── Portfolio file ────────────────────────────────────────────
PORTFOLIO_FILE = "portfolio.json"

# ==============================================================
# PUSH NOTIFICATIONS (ntfy.sh)
# ==============================================================

def send_notification(title, message, priority="high"):
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
                data = json.load(f)
                # Make sure all keys exist even in old saved files
                data.setdefault("cash", 10000.0)
                data.setdefault("holdings", {})
                data.setdefault("history", [])
                return data
        except Exception:
            pass
    save_portfolio(default)
    return default

def save_portfolio(p):
    with open(PORTFOLIO_FILE, "w") as f:
        json.dump(p, f, indent=2)

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

# ==============================================================
# FINNHUB API HELPERS
# ==============================================================

def get_quote(ticker):
    """Live quote: c=current, pc=prev close, h=high, l=low, o=open"""
    try:
        url  = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_KEY}"
        r    = requests.get(url, timeout=6)
        data = r.json()
        if data.get("c", 0) > 0:
            return data
        return None
    except Exception:
        return None

def get_candles(ticker, days=30):
    """Daily OHLCV candles for the past N days"""
    try:
        end   = int(datetime.now().timestamp())
        start = int((datetime.now() - timedelta(days=days + 10)).timestamp())
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
    """Recent news headlines"""
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
# AI ADVISOR (Groq)
# ==============================================================

def run_ai_analysis(portfolio):
    if not GROQ_KEY:
        return None, "No Groq API key set in Streamlit Secrets."

    # Build live market snapshot
    lines = ["Live market data:\n"]
    for ticker in WATCHLIST:
        q = get_quote(ticker)
        if q:
            change_pct = ((q["c"] - q["pc"]) / q["pc"] * 100) if q["pc"] else 0
            lines.append(
                f"  {ticker}: price=${q['c']:.2f}, "
                f"change={change_pct:+.2f}%, "
                f"high=${q['h']:.2f}, low=${q['l']:.2f}"
            )

    if len(lines) == 1:
        return None, "Could not fetch any market data. Check your Finnhub key."

    cash     = portfolio.get("cash", 0)
    holdings = portfolio.get("holdings", {})
    owned    = ", ".join(holdings.keys()) if holdings else "none"

    prompt = f"""
{chr(10).join(lines)}

Available cash: £{cash:.2f}
Already owns: {owned}

Pick the single best BUY from the tickers above.
You MUST respond with ONLY this JSON and nothing else — no markdown, no explanation:

{{"ticker":"AAPL","action":"BUY","shares":3,"price_per_share":213.45,"total_cost":640.35,"reasoning":"Brief reason using actual data above.","risk":"Low"}}
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
                "temperature": 0.1,
                "max_tokens":  300,
                "messages": [
                    {
                        "role":    "system",
                        "content": "You are a stock trading AI. Respond ONLY with a single line of valid JSON. No markdown fences. No explanation. No newlines inside the JSON."
                    },
                    {"role": "user", "content": prompt}
                ],
            },
            timeout=30,
        )

        data = resp.json()

        # Check for API-level errors (wrong key, rate limit, etc.)
        if "error" in data:
            return None, f"Groq API error: {data['error'].get('message', str(data['error']))}"

        if "choices" not in data or not data["choices"]:
            return None, f"Unexpected response from Groq: {json.dumps(data)[:200]}"

        raw = data["choices"][0]["message"]["content"].strip()

        # Strip any markdown the model sneaks in anyway
        raw = raw.replace("```json", "").replace("```", "").strip()

        # Find the JSON object even if there's surrounding text
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start == -1 or end == 0:
            return None, f"AI did not return valid JSON. Got: {raw[:200]}"

        rec = json.loads(raw[start:end])

        # Validate required fields
        for field in ["ticker", "shares", "price_per_share", "total_cost", "reasoning"]:
            if field not in rec:
                return None, f"AI response missing field: {field}. Got: {raw[:200]}"

        # Safety: don't recommend more than cash allows
        if rec["total_cost"] > cash:
            rec["shares"]         = max(1, int(cash // rec["price_per_share"]))
            rec["total_cost"]     = round(rec["shares"] * rec["price_per_share"], 2)

        rec.setdefault("risk",   "Medium")
        rec.setdefault("action", "BUY")

        return rec, None

    except json.JSONDecodeError as e:
        return None, f"Could not parse AI response as JSON: {e}"
    except Exception as e:
        return None, f"Unexpected error: {e}"

# ==============================================================
# SIDEBAR — always reload fresh portfolio here
# ==============================================================

portfolio = load_portfolio()
cash      = portfolio["cash"]
holdings  = portfolio["holdings"]

total_holdings_value = 0.0
for ticker, info in holdings.items():
    q = get_quote(ticker)
    if q:
        total_holdings_value += q["c"] * info["shares"]
    else:
        total_holdings_value += info.get("cost_basis", 0)

total_value = cash + total_holdings_value
profit      = total_value - 10000.0

st.sidebar.title("📈 AI Stock Trader")
st.sidebar.caption("Paper trading · Finnhub + Groq AI")
st.sidebar.divider()
st.sidebar.metric("💷 Cash",            f"£{cash:,.2f}")
st.sidebar.metric("📦 Holdings",        f"£{total_holdings_value:,.2f}")
st.sidebar.metric("💼 Total Portfolio", f"£{total_value:,.2f}")
delta_colour = "normal" if profit >= 0 else "inverse"
st.sidebar.metric("📊 Total P&L",       f"£{profit:+,.2f}")
st.sidebar.divider()

page = st.sidebar.radio(
    "Navigate",
    ["🏠 Dashboard", "🤖 AI Advisor", "🛒 Buy Stocks", "📋 My Portfolio", "📜 Trade History", "⚙️ Settings"]
)

# ==============================================================
# DASHBOARD
# ==============================================================

if page == "🏠 Dashboard":
    st.title("🏠 Market Dashboard")
    st.caption(f"Live data · {datetime.now().strftime('%d %b %Y, %H:%M')}")

    if not FINNHUB_KEY:
        st.error("⚠️ No Finnhub API key. Go to ⚙️ Settings.")
        st.stop()

    if st.button("🔄 Refresh prices"):
        st.rerun()

    st.subheader("Watchlist")
    cols = st.columns(4)
    for i, ticker in enumerate(WATCHLIST):
        q = get_quote(ticker)
        with cols[i % 4]:
            if q:
                change_pct = ((q["c"] - q["pc"]) / q["pc"] * 100) if q["pc"] else 0
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
    selected = st.selectbox("Stock", WATCHLIST, key="chart_ticker")
    period   = st.radio("Period", ["7 days", "30 days", "90 days"], horizontal=True)
    days_map = {"7 days": 7, "30 days": 30, "90 days": 90}
    candles  = get_candles(selected, days=days_map[period])

    if candles:
        df = pd.DataFrame(candles)
        st.line_chart(df.set_index("date")["close"], use_container_width=True)
        with st.expander("📊 Show full OHLCV data"):
            st.dataframe(df, use_container_width=True)
    else:
        st.info("No chart data available right now.")

    st.divider()
    st.subheader(f"📰 Latest News: {selected}")
    news = get_company_news(selected)
    if news:
        for article in news:
            ts = article.get("datetime", 0)
            date_str = datetime.fromtimestamp(ts).strftime("%d %b %Y") if ts else ""
            st.markdown(f"**[{article.get('headline', 'No title')}]({article.get('url', '#')})**")
            st.caption(f"{article.get('source', '')} · {date_str}")
            summary = article.get("summary", "")
            if summary:
                st.write(summary[:250] + ("..." if len(summary) > 250 else ""))
            st.divider()
    else:
        st.info("No recent news found.")

# ==============================================================
# AI ADVISOR
# ==============================================================

elif page == "🤖 AI Advisor":
    st.title("🤖 AI Investment Advisor")
    st.caption("AI scans the market and picks the best opportunity. **Nothing trades without your approval.**")

    if not FINNHUB_KEY:
        st.error("⚠️ Finnhub key missing. Go to ⚙️ Settings.")
        st.stop()
    if not GROQ_KEY:
        st.error("⚠️ Groq key missing. Go to ⚙️ Settings.")
        st.stop()

    if st.button("🔎 Run AI Analysis Now", type="primary", use_container_width=True):
        with st.spinner("Fetching live data and running AI analysis..."):
            rec, err = run_ai_analysis(portfolio)
        if err:
            st.error(f"❌ AI analysis failed: {err}")
        elif rec:
            st.session_state["pending_rec"] = rec
            send_notification(
                title=f"📈 AI Alert: {rec.get('action','BUY')} {rec['ticker']}",
                message=(
                    f"{rec['shares']} shares @ ${rec.get('price_per_share',0):.2f}\n"
                    f"Total: £{rec['total_cost']:.2f} | Risk: {rec.get('risk','?')}\n"
                    f"{rec['reasoning']}\n\nOpen the app to approve or reject."
                ),
            )

    rec = st.session_state.get("pending_rec")
    if rec:
        st.divider()
        st.subheader("📬 Recommendation — Awaiting Your Decision")
        risk_icon = {"Low": "🟢", "Medium": "🟡", "High": "🔴"}.get(rec.get("risk", ""), "⚪")

        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown(f"### {rec.get('action','BUY')} **{rec['ticker']}**")
            st.markdown(
                f"**Shares:** {rec['shares']}  |  "
                f"**Price:** ${rec.get('price_per_share',0):,.2f}  |  "
                f"**Total:** £{rec['total_cost']:,.2f}"
            )
            st.markdown(f"**Risk:** {risk_icon} {rec.get('risk', 'Unknown')}")
            st.markdown(f"**Reasoning:** {rec['reasoning']}")
        with col2:
            q = get_quote(rec["ticker"])
            if q:
                st.metric("Live Price", f"${q['c']:,.2f}")
            remaining = cash - rec["total_cost"]
            st.metric("Cash Remaining", f"£{remaining:,.2f}", delta=None)
            if remaining < 0:
                st.error("⚠️ Not enough cash!")

        st.warning("⚠️ Paper money only — no real money involved.")

        col_yes, col_no = st.columns(2)
        with col_yes:
            if st.button("✅ APPROVE TRADE", type="primary", use_container_width=True):
                portfolio = load_portfolio()  # reload fresh before writing
                if rec["total_cost"] > portfolio["cash"]:
                    st.error("Not enough cash for this trade!")
                else:
                    portfolio["cash"] -= rec["total_cost"]
                    ticker = rec["ticker"]
                    if ticker in portfolio["holdings"]:
                        ex           = portfolio["holdings"][ticker]
                        new_shares   = ex["shares"] + rec["shares"]
                        new_basis    = ex["cost_basis"] + rec["total_cost"]
                        portfolio["holdings"][ticker] = {
                            "shares":     new_shares,
                            "cost_basis": new_basis,
                            "avg_price":  new_basis / new_shares,
                        }
                    else:
                        portfolio["holdings"][ticker] = {
                            "shares":     rec["shares"],
                            "cost_basis": rec["total_cost"],
                            "avg_price":  rec.get("price_per_share", 0),
                        }
                    record_trade(portfolio, "BUY", ticker, rec["shares"],
                                 rec.get("price_per_share", 0), rec["total_cost"], rec["reasoning"])
                    save_portfolio(portfolio)
                    send_notification(
                        title=f"✅ Bought {ticker}",
                        message=f"{rec['shares']} shares for £{rec['total_cost']:.2f}",
                        priority="default",
                    )
                    del st.session_state["pending_rec"]
                    st.success(f"✅ Bought {rec['shares']} shares of {ticker}!")
                    st.rerun()

        with col_no:
            if st.button("❌ REJECT", use_container_width=True):
                send_notification(
                    title=f"❌ Rejected: {rec['ticker']}",
                    message="Trade rejected. No action taken.",
                    priority="low",
                )
                del st.session_state["pending_rec"]
                st.info("Trade rejected.")
                st.rerun()

# ==============================================================
# BUY STOCKS (manual)
# ==============================================================

elif page == "🛒 Buy Stocks":
    st.title("🛒 Buy Stocks Manually")
    st.caption("Search any stock and buy it yourself with your paper money.")

    if not FINNHUB_KEY:
        st.error("⚠️ Finnhub key missing. Go to ⚙️ Settings.")
        st.stop()

    # Stock search
    col1, col2 = st.columns([2, 1])
    with col1:
        ticker_input = st.text_input("Enter stock ticker (e.g. AAPL, TSLA, NVDA)", "").upper().strip()
    with col2:
        st.write("")
        st.write("")
        search = st.button("🔍 Look up price", use_container_width=True)

    if ticker_input and search:
        st.session_state["buy_ticker"] = ticker_input
        st.session_state["buy_quote"]  = get_quote(ticker_input)

    buy_ticker = st.session_state.get("buy_ticker")
    buy_quote  = st.session_state.get("buy_quote")

    if buy_ticker:
        if buy_quote:
            change_pct = ((buy_quote["c"] - buy_quote["pc"]) / buy_quote["pc"] * 100) if buy_quote["pc"] else 0

            st.divider()
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Current Price", f"${buy_quote['c']:,.2f}")
            c2.metric("Today's Change", f"{change_pct:+.2f}%")
            c3.metric("Day High",  f"${buy_quote['h']:,.2f}")
            c4.metric("Day Low",   f"${buy_quote['l']:,.2f}")

            st.divider()
            st.subheader(f"Buy {buy_ticker}")

            num_shares = st.number_input(
                "Number of shares",
                min_value=1,
                max_value=10000,
                value=1,
                step=1,
                key="manual_shares"
            )

            est_cost = round(num_shares * buy_quote["c"], 2)
            st.write(f"**Estimated cost:** £{est_cost:,.2f}")
            st.write(f"**Cash available:** £{cash:,.2f}")
            st.write(f"**Cash after purchase:** £{cash - est_cost:,.2f}")

            if est_cost > cash:
                st.error(f"⚠️ Not enough cash. You need £{est_cost:,.2f} but only have £{cash:,.2f}.")
            else:
                if st.button(f"✅ Buy {num_shares} shares of {buy_ticker} for £{est_cost:,.2f}", type="primary"):
                    portfolio = load_portfolio()
                    if est_cost > portfolio["cash"]:
                        st.error("Not enough cash!")
                    else:
                        portfolio["cash"] -= est_cost
                        if buy_ticker in portfolio["holdings"]:
                            ex        = portfolio["holdings"][buy_ticker]
                            new_sh    = ex["shares"] + num_shares
                            new_basis = ex["cost_basis"] + est_cost
                            portfolio["holdings"][buy_ticker] = {
                                "shares":     new_sh,
                                "cost_basis": new_basis,
                                "avg_price":  new_basis / new_sh,
                            }
                        else:
                            portfolio["holdings"][buy_ticker] = {
                                "shares":     num_shares,
                                "cost_basis": est_cost,
                                "avg_price":  buy_quote["c"],
                            }
                        record_trade(portfolio, "BUY", buy_ticker, num_shares,
                                     buy_quote["c"], est_cost, "Manual purchase")
                        save_portfolio(portfolio)
                        send_notification(
                            title=f"🛒 Manual Buy: {buy_ticker}",
                            message=f"Bought {num_shares} shares of {buy_ticker} for £{est_cost:.2f}",
                            priority="default",
                        )
                        st.success(f"✅ Bought {num_shares} shares of {buy_ticker} for £{est_cost:,.2f}!")
                        del st.session_state["buy_ticker"]
                        del st.session_state["buy_quote"]
                        st.rerun()
        else:
            st.error(f"❌ Could not find price for **{buy_ticker}**. Check the ticker symbol is correct.")

    # Quick buy from watchlist
    st.divider()
    st.subheader("Quick buy from watchlist")
    cols = st.columns(4)
    for i, ticker in enumerate(WATCHLIST):
        q = get_quote(ticker)
        with cols[i % 4]:
            if q:
                st.write(f"**{ticker}** — ${q['c']:,.2f}")
                if st.button(f"Buy {ticker}", key=f"quick_{ticker}"):
                    st.session_state["buy_ticker"] = ticker
                    st.session_state["buy_quote"]  = q
                    st.rerun()

# ==============================================================
# MY PORTFOLIO
# ==============================================================

elif page == "📋 My Portfolio":
    st.title("📋 My Portfolio")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("💷 Cash",         f"£{cash:,.2f}")
    col2.metric("📦 Holdings",     f"£{total_holdings_value:,.2f}")
    col3.metric("💼 Total Value",  f"£{total_value:,.2f}")
    col4.metric("📊 P&L",          f"£{profit:+,.2f}")

    st.divider()

    if holdings:
        st.subheader("Current Holdings")

        # Snapshot the keys to avoid dict-change-during-iteration bug
        tickers_held = list(holdings.keys())

        for ticker in tickers_held:
            if ticker not in portfolio["holdings"]:
                continue  # already sold this session
            info = portfolio["holdings"][ticker]
            q          = get_quote(ticker)
            curr_price = q["c"] if q else info["avg_price"]
            curr_value = curr_price * info["shares"]
            gain       = curr_value - info["cost_basis"]
            gain_pct   = (gain / info["cost_basis"] * 100) if info["cost_basis"] else 0
            icon       = "🟢" if gain >= 0 else "🔴"

            with st.expander(f"{icon} **{ticker}** — {info['shares']} shares · Now £{curr_value:,.2f} · P&L £{gain:+,.2f} ({gain_pct:+.1f}%)"):
                c1, c2, c3 = st.columns(3)
                c1.metric("Current Price",  f"${curr_price:,.2f}")
                c2.metric("Avg Buy Price",  f"£{info['avg_price']:,.2f}")
                c3.metric("Current Value",  f"£{curr_value:,.2f}")

                st.write(f"**Shares held:** {info['shares']}")
                st.write(f"**Total invested:** £{info['cost_basis']:,.2f}")
                st.write(f"**Unrealised P&L:** {icon} £{gain:+,.2f} ({gain_pct:+.1f}%)")

                # Partial or full sell
                sell_shares = st.number_input(
                    f"Shares to sell (max {info['shares']})",
                    min_value=1,
                    max_value=info["shares"],
                    value=info["shares"],
                    key=f"sell_qty_{ticker}"
                )
                proceeds = round(curr_price * sell_shares, 2)
                st.write(f"**You will receive:** £{proceeds:,.2f}")

                if st.button(f"💰 Sell {sell_shares} shares of {ticker}", key=f"sell_{ticker}", type="primary"):
                    if not q:
                        st.error("Cannot fetch live price to sell. Try again shortly.")
                    else:
                        portfolio = load_portfolio()
                        portfolio["cash"] += proceeds
                        remaining = info["shares"] - sell_shares
                        if remaining == 0:
                            del portfolio["holdings"][ticker]
                        else:
                            new_basis = info["cost_basis"] * (remaining / info["shares"])
                            portfolio["holdings"][ticker] = {
                                "shares":     remaining,
                                "cost_basis": new_basis,
                                "avg_price":  info["avg_price"],
                            }
                        record_trade(portfolio, "SELL", ticker, sell_shares,
                                     curr_price, proceeds, "Manual sell")
                        save_portfolio(portfolio)
                        send_notification(
                            title=f"💰 Sold {ticker}",
                            message=f"Sold {sell_shares} shares of {ticker} for £{proceeds:.2f}",
                            priority="default",
                        )
                        st.success(f"✅ Sold {sell_shares} shares of {ticker} for £{proceeds:,.2f}!")
                        st.rerun()
    else:
        st.info("No holdings yet. Go to 🛒 Buy Stocks or 🤖 AI Advisor to get started!")

    st.divider()
    if st.button("🔄 Reset Portfolio to £10,000", type="secondary"):
        save_portfolio({"cash": 10000.0, "holdings": {}, "history": []})
        st.success("Portfolio reset!")
        st.rerun()

# ==============================================================
# TRADE HISTORY
# ==============================================================

elif page == "📜 Trade History":
    st.title("📜 Trade History")
    history = portfolio.get("history", [])

    if history:
        # Summary stats
        buys  = [t for t in history if t["action"] == "BUY"]
        sells = [t for t in history if t["action"] == "SELL"]
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Trades", len(history))
        c2.metric("Buys",  len(buys))
        c3.metric("Sells", len(sells))
        st.divider()

        for trade in reversed(history):
            date_str = datetime.fromisoformat(trade["date"]).strftime("%d %b %Y  %H:%M")
            emoji    = "🟢" if trade["action"] == "BUY" else "🔴"
            with st.expander(
                f"{emoji} {trade['action']}  {trade['ticker']}  ·  "
                f"{trade['shares']} shares  ·  £{trade['total']:,.2f}  ·  {date_str}"
            ):
                st.write(f"**Price per share:** £{trade['price']:,.2f}")
                st.write(f"**Total:** £{trade['total']:,.2f}")
                st.write(f"**Reason:** {trade.get('reasoning', '—')}")
    else:
        st.info("No trades yet.")

# ==============================================================
# SETTINGS
# ==============================================================

elif page == "⚙️ Settings":
    st.title("⚙️ Settings & Setup")

    st.subheader("API Key Status")
    st.write("🔑 **Finnhub:**", "✅ Connected" if FINNHUB_KEY else "❌ Missing")
    st.write("🔑 **Groq:**",    "✅ Connected" if GROQ_KEY    else "❌ Missing")
    st.write("🔔 **Ntfy:**",    "✅ Connected" if NTFY_TOPIC  else "⚠️ Not set — notifications disabled")

    st.divider()
    st.subheader("📱 Push Notifications Setup (ntfy.sh — free)")
    st.markdown("""
**Step 1** — Install **ntfy** on your phone (App Store / Play Store)

**Step 2** — Pick a unique private topic name, e.g. `my-trader-x8k29`

**Step 3** — In the ntfy app: tap **+** → enter your topic → Subscribe

**Step 4** — Add to Streamlit Secrets:
```toml
NTFY_TOPIC = "my-trader-x8k29"
```
    """)

    if NTFY_TOPIC:
        st.divider()
        if st.button("📱 Send test notification"):
            sent = send_notification(
                title="✅ AI Stock Trader — Test",
                message="Push notifications are working correctly!",
                priority="default",
            )
            st.success("Sent! Check your phone.") if sent else st.error("Failed to send.")

    st.divider()
    st.subheader("All Streamlit Secrets — copy & paste this")
    st.code(
        'FINNHUB_KEY = "your_finnhub_key_here"\n'
        'GROQ_KEY    = "your_groq_key_here"\n'
        'NTFY_TOPIC  = "your-unique-topic-here"',
        language="toml"
    )

    st.divider()
    st.subheader("Where to get your keys")
    st.markdown("""
- **Finnhub (free):** [finnhub.io](https://finnhub.io) → Sign up → copy API key from dashboard
- **Groq (free):** [console.groq.com](https://console.groq.com) → Sign up → API Keys → Create key
- **ntfy (free):** No account needed — just pick a topic name
    """)

    st.divider()
    st.subheader("Watchlist")
    st.write(", ".join(WATCHLIST))
    st.info("To change the watchlist, edit the WATCHLIST variable at the top of app.py.")
