# ==============================================================
# AI Stock Trader — Complete App
# Finnhub (live data) + Groq AI + ntfy notifications
# JSONBin.io for cloud portfolio storage (shared with GitHub Actions)
# ==============================================================

import streamlit as st
import requests
import json
import os
import pandas as pd
from datetime import datetime, timedelta

st.set_page_config(page_title="AI Stock Trader", page_icon="📈", layout="wide")

# ── Secrets ───────────────────────────────────────────────────
def _secret(key):
    try:
        return st.secrets[key]
    except Exception:
        return os.getenv(key, "")

FINNHUB_KEY     = _secret("FINNHUB_KEY")
GROQ_KEY        = _secret("GROQ_KEY")
NTFY_TOPIC      = _secret("NTFY_TOPIC")
JSONBIN_BIN_ID  = _secret("JSONBIN_BIN_ID")
JSONBIN_API_KEY = _secret("JSONBIN_API_KEY")

# ── Watchlist ─────────────────────────────────────────────────
WATCHLIST = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMD", "AMZN",
    "TSLA", "RIVN", "ENPH",
    "JPM", "GS", "V",
    "JNJ", "PFE", "LLY",
    "NFLX", "UBER", "SBUX",
    "INTC", "QCOM", "ORCL",
    "COIN", "PLTR", "SHOP", "SNOW", "ARM",
]

# ── Sell alert thresholds ─────────────────────────────────────
TAKE_PROFIT_PCT = 5.0
STOP_LOSS_PCT   = -3.0
DAY_GAIN_PCT    = 3.0

# ==============================================================
# JSONBIN PORTFOLIO STORAGE
# ==============================================================

JSONBIN_URL     = "https://api.jsonbin.io/v3/b"
DEFAULT_PORTFOLIO = {"cash": 10000.0, "holdings": {}, "history": []}

def load_portfolio():
    if not JSONBIN_BIN_ID or not JSONBIN_API_KEY:
        st.warning("JSONBin not configured — using local session only.")
        return DEFAULT_PORTFOLIO.copy()
    try:
        r = requests.get(
            f"{JSONBIN_URL}/{JSONBIN_BIN_ID}/latest",
            headers={"X-Master-Key": JSONBIN_API_KEY},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json().get("record", DEFAULT_PORTFOLIO.copy())
            data.setdefault("cash",     10000.0)
            data.setdefault("holdings", {})
            data.setdefault("history",  [])
            return data
        else:
            st.error(f"Could not load portfolio: {r.status_code}")
            return DEFAULT_PORTFOLIO.copy()
    except Exception as e:
        st.error(f"Portfolio load error: {e}")
        return DEFAULT_PORTFOLIO.copy()

def save_portfolio(portfolio):
    if not JSONBIN_BIN_ID or not JSONBIN_API_KEY:
        return False
    try:
        r = requests.put(
            f"{JSONBIN_URL}/{JSONBIN_BIN_ID}",
            headers={
                "X-Master-Key": JSONBIN_API_KEY,
                "Content-Type": "application/json",
            },
            json=portfolio,
            timeout=10,
        )
        return r.status_code == 200
    except Exception:
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

# ==============================================================
# NOTIFICATIONS
# ==============================================================

def send_notification(title, message, priority="high"):
    if not NTFY_TOPIC:
        return False
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            headers={
                "Title":        title,
                "Priority":     priority,
                "Tags":         "chart_increasing,robot",
                "Content-Type": "text/plain; charset=utf-8",
            },
            data=message.encode("utf-8"),
            timeout=5,
        )
        return True
    except Exception:
        return False

# ==============================================================
# FINNHUB
# ==============================================================

def get_quote(ticker):
    try:
        r    = requests.get(
            f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_KEY}",
            timeout=6
        )
        data = r.json()
        return data if data.get("c", 0) > 0 else None
    except Exception:
        return None

def get_candles(ticker, days=30):
    try:
        end   = int(datetime.now().timestamp())
        start = int((datetime.now() - timedelta(days=days + 10)).timestamp())
        r     = requests.get(
            f"https://finnhub.io/api/v1/stock/candle"
            f"?symbol={ticker}&resolution=D&from={start}&to={end}&token={FINNHUB_KEY}",
            timeout=8
        )
        data = r.json()
        if data.get("s") == "ok":
            return [
                {"date": datetime.fromtimestamp(data["t"][i]).strftime("%d %b"),
                 "open": data["o"][i], "high": data["h"][i],
                 "low":  data["l"][i], "close": data["c"][i], "volume": data["v"][i]}
                for i in range(len(data["t"]))
            ][-days:]
        return []
    except Exception:
        return []

def get_company_news(ticker):
    try:
        to_date   = datetime.now().strftime("%Y-%m-%d")
        from_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        r    = requests.get(
            f"https://finnhub.io/api/v1/company-news"
            f"?symbol={ticker}&from={from_date}&to={to_date}&token={FINNHUB_KEY}",
            timeout=6
        )
        news = r.json()
        return news[:5] if isinstance(news, list) else []
    except Exception:
        return []

# ==============================================================
# AI ADVISOR
# ==============================================================

def run_ai_analysis(portfolio):
    if not GROQ_KEY:
        return None, "No Groq API key set."

    lines = ["Live market data:\n"]
    for ticker in WATCHLIST:
        q = get_quote(ticker)
        if q:
            chg = ((q["c"] - q["pc"]) / q["pc"] * 100) if q["pc"] else 0
            lines.append(f"  {ticker}: price=${q['c']:.2f}, change={chg:+.2f}%, high=${q['h']:.2f}, low=${q['l']:.2f}")

    if len(lines) == 1:
        return None, "Could not fetch market data."

    cash    = portfolio.get("cash", 0)
    owned   = ", ".join(portfolio.get("holdings", {}).keys()) or "none"
    prompt  = f"""
{chr(10).join(lines)}

Available cash: £{cash:.2f}
Already owns: {owned}

Pick the single best BUY. IMPORTANT LIMITS: max 20 shares, max £3,500 total cost. Spread risk — do not go all in on one stock.
Reply ONLY with JSON, no markdown:
{{"ticker":"AAPL","action":"BUY","shares":3,"price_per_share":213.45,"total_cost":499.50,"reasoning":"Brief reason.","risk":"Low"}}
"""
    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "temperature": 0.1, "max_tokens": 300,
                "messages": [
                    {"role": "system", "content": "You are a stock trading AI. Respond ONLY with valid JSON. No markdown."},
                    {"role": "user",   "content": prompt}
                ],
            },
            timeout=30,
        )
        data = resp.json()
        if "error" in data:
            return None, f"Groq error: {data['error'].get('message', str(data['error']))}"
        if "choices" not in data:
            return None, f"Unexpected response: {json.dumps(data)[:200]}"

        raw = data["choices"][0]["message"]["content"].strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        s, e = raw.find("{"), raw.rfind("}") + 1
        if s == -1: return None, f"No JSON in response: {raw[:200]}"

        rec = json.loads(raw[s:e])
        for f in ["ticker", "shares", "price_per_share", "total_cost", "reasoning"]:
            if f not in rec:
                return None, f"Missing field: {f}"
        MAX_SPEND  = 3500.0
        MAX_SHARES = 20
        if rec["total_cost"] > MAX_SPEND or rec["shares"] > MAX_SHARES:
            rec["shares"]     = min(MAX_SHARES, max(1, int(MAX_SPEND // rec["price_per_share"])))
            rec["total_cost"] = round(rec["shares"] * rec["price_per_share"], 2)
        if rec["total_cost"] > cash:
            rec["shares"]     = max(1, int(cash // rec["price_per_share"]))
            rec["total_cost"] = round(rec["shares"] * rec["price_per_share"], 2)
        rec.setdefault("risk", "Medium")
        rec.setdefault("action", "BUY")
        return rec, None
    except Exception as e:
        return None, str(e)

# ==============================================================
# SELL ALERT CHECK (runs on dashboard load)
# ==============================================================

def check_sell_alerts(portfolio):
    """Check holdings for sell signals and return list of alerts"""
    alerts = []
    for ticker, info in portfolio.get("holdings", {}).items():
        avg_price = info.get("avg_price", 0)
        shares    = info.get("shares", 0)
        if avg_price == 0 or shares == 0:
            continue
        q = get_quote(ticker)
        if not q:
            continue
        curr_price    = q["c"]
        overall_pct   = ((curr_price - avg_price) / avg_price * 100) if avg_price else 0
        day_pct       = ((q["c"] - q["pc"]) / q["pc"] * 100) if q["pc"] else 0
        curr_value    = curr_price * shares
        total_gain    = curr_value - info.get("cost_basis", 0)

        triggers = []
        if overall_pct >= TAKE_PROFIT_PCT:
            triggers.append(f"up {overall_pct:.1f}% from your buy price")
        if overall_pct <= STOP_LOSS_PCT:
            triggers.append(f"down {abs(overall_pct):.1f}% — stop loss")
        if day_pct >= DAY_GAIN_PCT:
            triggers.append(f"up {day_pct:.1f}% today")

        if triggers:
            alerts.append({
                "ticker":      ticker,
                "shares":      shares,
                "curr_price":  curr_price,
                "avg_price":   avg_price,
                "overall_pct": overall_pct,
                "day_pct":     day_pct,
                "curr_value":  curr_value,
                "total_gain":  total_gain,
                "triggers":    triggers,
                "is_loss":     overall_pct <= STOP_LOSS_PCT,
            })
    return alerts

# ==============================================================
# SIDEBAR
# ==============================================================

portfolio = load_portfolio()
cash      = portfolio["cash"]
holdings  = portfolio["holdings"]

total_holdings_value = sum(
    (get_quote(t) or {}).get("c", info["avg_price"]) * info["shares"]
    for t, info in holdings.items()
)
total_value = cash + total_holdings_value
profit      = total_value - 10000.0

st.sidebar.title("📈 AI Stock Trader")
st.sidebar.caption("Paper trading · Finnhub + Groq AI")
st.sidebar.divider()
st.sidebar.metric("💷 Cash",            f"£{cash:,.2f}")
st.sidebar.metric("📦 Holdings",        f"£{total_holdings_value:,.2f}")
st.sidebar.metric("💼 Total Portfolio", f"£{total_value:,.2f}")
st.sidebar.metric("📊 Total P&L",       f"£{profit:+,.2f}")
st.sidebar.divider()

page = st.sidebar.radio("Navigate", [
    "🏠 Dashboard", "🤖 AI Advisor", "🛒 Buy Stocks",
    "📋 My Portfolio", "📜 Trade History", "⚙️ Settings"
])

# ==============================================================
# SELL ALERTS BANNER (shows on every page if triggered)
# ==============================================================

if holdings:
    alerts = check_sell_alerts(portfolio)
    for alert in alerts:
        icon = "🔴" if alert["is_loss"] else "🟢"
        reasons = " | ".join(alert["triggers"])
        st.warning(
            f"{icon} **SELL ALERT: {alert['ticker']}** — {reasons} — "
            f"Current: ${alert['curr_price']:.2f} | P&L: £{alert['total_gain']:+,.2f} — "
            f"[Go to Portfolio](#)"
        )
        # Send phone notification for new alerts
        send_notification(
            title=f"Sell Alert: {alert['ticker']} {alert['overall_pct']:+.1f}%",
            message=(
                f"{reasons}\n"
                f"Current price: ${alert['curr_price']:.2f}\n"
                f"Your avg buy: ${alert['avg_price']:.2f}\n"
                f"P&L: £{alert['total_gain']:+,.2f}\n"
                f"Open the app to sell."
            ),
            priority="urgent" if alert["is_loss"] else "high",
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
                chg = ((q["c"] - q["pc"]) / q["pc"] * 100) if q["pc"] else 0
                st.metric(label=ticker, value=f"${q['c']:,.2f}", delta=f"{chg:+.2f}%")
                st.caption(f"H ${q['h']:.2f}  L ${q['l']:.2f}")
            else:
                st.metric(label=ticker, value="—")

    st.divider()
    st.subheader("Price Chart")
    selected = st.selectbox("Stock", WATCHLIST, key="chart_ticker")
    period   = st.radio("Period", ["7 days", "30 days", "90 days"], horizontal=True)
    candles  = get_candles(selected, days={"7 days": 7, "30 days": 30, "90 days": 90}[period])
    if candles:
        df = pd.DataFrame(candles)
        st.line_chart(df.set_index("date")["close"], use_container_width=True)
        with st.expander("Show OHLCV data"):
            st.dataframe(df, use_container_width=True)
    else:
        st.info("No chart data available.")

    st.divider()
    st.subheader(f"Latest News: {selected}")
    news = get_company_news(selected)
    if news:
        for article in news:
            ts = article.get("datetime", 0)
            st.markdown(f"**[{article.get('headline','No title')}]({article.get('url','#')})**")
            st.caption(f"{article.get('source','')} · {datetime.fromtimestamp(ts).strftime('%d %b %Y') if ts else ''}")
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
        st.error("⚠️ Finnhub key missing.")
        st.stop()
    if not GROQ_KEY:
        st.error("⚠️ Groq key missing.")
        st.stop()

    if st.button("🔎 Run AI Analysis Now", type="primary", use_container_width=True):
        with st.spinner("Fetching live data and running AI analysis..."):
            rec, err = run_ai_analysis(portfolio)
        if err:
            st.error(f"❌ AI analysis failed: {err}")
        elif rec:
            st.session_state["pending_rec"] = rec
            send_notification(
                title=f"AI Alert: BUY {rec['ticker']}",
                message=(
                    f"{rec['shares']} shares @ ${rec.get('price_per_share',0):.2f}\n"
                    f"Total: £{rec['total_cost']:.2f} | Risk: {rec.get('risk','?')}\n"
                    f"{rec['reasoning']}\n\nOpen the app to approve or reject."
                ),
            )

    rec = st.session_state.get("pending_rec")
    if rec:
        st.divider()
        st.subheader("Recommendation — Awaiting Your Decision")
        risk_icon = {"Low": "🟢", "Medium": "🟡", "High": "🔴"}.get(rec.get("risk",""), "⚪")

        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown(f"### {rec.get('action','BUY')} **{rec['ticker']}**")
            st.markdown(f"**Shares:** {rec['shares']}  |  **Price:** ${rec.get('price_per_share',0):,.2f}  |  **Total:** £{rec['total_cost']:,.2f}")
            st.markdown(f"**Risk:** {risk_icon} {rec.get('risk','Unknown')}")
            st.markdown(f"**Reasoning:** {rec['reasoning']}")
        with col2:
            q = get_quote(rec["ticker"])
            if q:
                st.metric("Live Price", f"${q['c']:,.2f}")
            st.metric("Cash Remaining", f"£{cash - rec['total_cost']:,.2f}")

        st.warning("⚠️ Paper money only.")

        col_yes, col_no = st.columns(2)
        with col_yes:
            if st.button("✅ APPROVE TRADE", type="primary", use_container_width=True):
                portfolio = load_portfolio()
                if rec["total_cost"] > portfolio["cash"]:
                    st.error("Not enough cash!")
                else:
                    portfolio["cash"] -= rec["total_cost"]
                    ticker = rec["ticker"]
                    if ticker in portfolio["holdings"]:
                        ex        = portfolio["holdings"][ticker]
                        new_sh    = ex["shares"] + rec["shares"]
                        new_basis = ex["cost_basis"] + rec["total_cost"]
                        portfolio["holdings"][ticker] = {"shares": new_sh, "cost_basis": new_basis, "avg_price": new_basis / new_sh}
                    else:
                        portfolio["holdings"][ticker] = {"shares": rec["shares"], "cost_basis": rec["total_cost"], "avg_price": rec.get("price_per_share", 0)}
                    record_trade(portfolio, "BUY", ticker, rec["shares"], rec.get("price_per_share",0), rec["total_cost"], rec["reasoning"])
                    save_portfolio(portfolio)
                    send_notification(title=f"Bought {ticker}", message=f"{rec['shares']} shares for £{rec['total_cost']:.2f}", priority="default")
                    del st.session_state["pending_rec"]
                    st.success(f"✅ Bought {rec['shares']} shares of {ticker}!")
                    st.rerun()

        with col_no:
            if st.button("❌ REJECT", use_container_width=True):
                del st.session_state["pending_rec"]
                st.info("Trade rejected.")
                st.rerun()

# ==============================================================
# BUY STOCKS
# ==============================================================

elif page == "🛒 Buy Stocks":
    st.title("🛒 Buy Stocks Manually")

    col1, col2 = st.columns([2, 1])
    with col1:
        ticker_input = st.text_input("Enter stock ticker (e.g. AAPL, TSLA)", "").upper().strip()
    with col2:
        st.write("")
        st.write("")
        if st.button("🔍 Look up", use_container_width=True):
            st.session_state["buy_ticker"] = ticker_input
            st.session_state["buy_quote"]  = get_quote(ticker_input)

    buy_ticker = st.session_state.get("buy_ticker")
    buy_quote  = st.session_state.get("buy_quote")

    if buy_ticker:
        if buy_quote:
            chg = ((buy_quote["c"] - buy_quote["pc"]) / buy_quote["pc"] * 100) if buy_quote["pc"] else 0
            st.divider()
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Price",   f"${buy_quote['c']:,.2f}")
            c2.metric("Change",  f"{chg:+.2f}%")
            c3.metric("Day High", f"${buy_quote['h']:,.2f}")
            c4.metric("Day Low",  f"${buy_quote['l']:,.2f}")

            st.divider()
            num_shares = st.number_input("Number of shares", min_value=1, max_value=10000, value=1, step=1)
            est_cost   = round(num_shares * buy_quote["c"], 2)
            st.write(f"**Estimated cost:** £{est_cost:,.2f}  |  **Cash after:** £{cash - est_cost:,.2f}")

            if est_cost > cash:
                st.error(f"Not enough cash. Need £{est_cost:,.2f}, have £{cash:,.2f}.")
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
                            portfolio["holdings"][buy_ticker] = {"shares": new_sh, "cost_basis": new_basis, "avg_price": new_basis / new_sh}
                        else:
                            portfolio["holdings"][buy_ticker] = {"shares": num_shares, "cost_basis": est_cost, "avg_price": buy_quote["c"]}
                        record_trade(portfolio, "BUY", buy_ticker, num_shares, buy_quote["c"], est_cost, "Manual purchase")
                        save_portfolio(portfolio)
                        send_notification(title=f"Bought {buy_ticker}", message=f"{num_shares} shares for £{est_cost:.2f}", priority="default")
                        st.success(f"✅ Bought {num_shares} shares of {buy_ticker} for £{est_cost:,.2f}!")
                        del st.session_state["buy_ticker"]
                        del st.session_state["buy_quote"]
                        st.rerun()
        else:
            st.error(f"❌ Could not find price for **{buy_ticker}**.")

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
    col1.metric("💷 Cash",        f"£{cash:,.2f}")
    col2.metric("📦 Holdings",    f"£{total_holdings_value:,.2f}")
    col3.metric("💼 Total Value", f"£{total_value:,.2f}")
    col4.metric("📊 P&L",         f"£{profit:+,.2f}")
    st.divider()

    if holdings:
        st.subheader("Current Holdings")
        for ticker in list(holdings.keys()):
            if ticker not in portfolio["holdings"]:
                continue
            info       = portfolio["holdings"][ticker]
            q          = get_quote(ticker)
            curr_price = q["c"] if q else info["avg_price"]
            curr_value = curr_price * info["shares"]
            gain       = curr_value - info["cost_basis"]
            gain_pct   = (gain / info["cost_basis"] * 100) if info["cost_basis"] else 0
            icon       = "🟢" if gain >= 0 else "🔴"

            with st.expander(f"{icon} **{ticker}** — {info['shares']} shares · £{curr_value:,.2f} · P&L £{gain:+,.2f} ({gain_pct:+.1f}%)"):
                c1, c2, c3 = st.columns(3)
                c1.metric("Current Price", f"${curr_price:,.2f}")
                c2.metric("Avg Buy Price", f"£{info['avg_price']:,.2f}")
                c3.metric("Current Value", f"£{curr_value:,.2f}")
                st.write(f"**Shares:** {info['shares']}  |  **Invested:** £{info['cost_basis']:,.2f}  |  **P&L:** {icon} £{gain:+,.2f}")

                max_shares  = int(info["shares"])
                sell_shares = st.number_input(f"Shares to sell (max {max_shares})", min_value=1, max_value=max_shares, value=max_shares, step=1, key=f"sell_qty_{ticker}")
                proceeds    = round(curr_price * sell_shares, 2)
                st.write(f"**You will receive:** £{proceeds:,.2f}")

                if st.button(f"💰 Sell {sell_shares} shares of {ticker}", key=f"sell_{ticker}", type="primary"):
                    if not q:
                        st.error("Cannot fetch live price.")
                    else:
                        portfolio = load_portfolio()
                        portfolio["cash"] += proceeds
                        remaining = info["shares"] - sell_shares
                        if remaining == 0:
                            del portfolio["holdings"][ticker]
                        else:
                            new_basis = info["cost_basis"] * (remaining / info["shares"])
                            portfolio["holdings"][ticker] = {"shares": remaining, "cost_basis": new_basis, "avg_price": info["avg_price"]}
                        record_trade(portfolio, "SELL", ticker, sell_shares, curr_price, proceeds, "Manual sell")
                        save_portfolio(portfolio)
                        send_notification(title=f"Sold {ticker}", message=f"{sell_shares} shares for £{proceeds:.2f}", priority="default")
                        st.success(f"✅ Sold {sell_shares} shares of {ticker} for £{proceeds:,.2f}!")
                        st.rerun()
    else:
        st.info("No holdings yet. Go to 🛒 Buy Stocks or 🤖 AI Advisor!")

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
        buys  = [t for t in history if t["action"] == "BUY"]
        sells = [t for t in history if t["action"] == "SELL"]
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Trades", len(history))
        c2.metric("Buys",  len(buys))
        c3.metric("Sells", len(sells))
        st.divider()
        for trade in reversed(history):
            date_str = datetime.fromisoformat(trade["date"]).strftime("%d %b %Y %H:%M")
            emoji    = "🟢" if trade["action"] == "BUY" else "🔴"
            with st.expander(f"{emoji} {trade['action']} {trade['ticker']} · {trade['shares']} shares · £{trade['total']:,.2f} · {date_str}"):
                st.write(f"**Price:** £{trade['price']:,.2f}  |  **Total:** £{trade['total']:,.2f}")
                st.write(f"**Reason:** {trade.get('reasoning','—')}")
    else:
        st.info("No trades yet.")

# ==============================================================
# SETTINGS
# ==============================================================

elif page == "⚙️ Settings":
    st.title("⚙️ Settings & Setup")

    st.subheader("Status")
    st.write("🔑 **Finnhub:**",    "✅ Connected" if FINNHUB_KEY     else "❌ Missing")
    st.write("🔑 **Groq:**",       "✅ Connected" if GROQ_KEY        else "❌ Missing")
    st.write("🔔 **Ntfy:**",       "✅ Connected" if NTFY_TOPIC      else "⚠️ Not set")
    st.write("💾 **JSONBin:**",    "✅ Connected" if JSONBIN_BIN_ID  else "❌ Missing")

    if NTFY_TOPIC:
        st.divider()
        if st.button("📱 Send test notification"):
            sent = send_notification("Test from AI Stock Trader", "Notifications are working!", priority="default")
            st.success("Sent!") if sent else st.error("Failed.")

    st.divider()
    st.subheader("Streamlit Secrets — copy & paste")
    st.code(
        'FINNHUB_KEY     = "your_finnhub_key"\n'
        'GROQ_KEY        = "your_groq_key"\n'
        'NTFY_TOPIC      = "your-ntfy-topic"\n'
        'JSONBIN_BIN_ID  = "your_bin_id"\n'
        'JSONBIN_API_KEY = "your_master_key"',
        language="toml"
    )

    st.divider()
    st.subheader("Sell Alert Thresholds")
    st.write(f"Take profit: **+{TAKE_PROFIT_PCT}%**")
    st.write(f"Stop loss: **{STOP_LOSS_PCT}%**")
    st.write(f"Daily momentum: **+{DAY_GAIN_PCT}%**")
    st.info("To change these, edit TAKE_PROFIT_PCT, STOP_LOSS_PCT and DAY_GAIN_PCT at the top of app.py")

    st.divider()
    st.subheader("Watchlist")
    st.write(", ".join(WATCHLIST))
