"""MacroClaw — Apple-inspired Financial Intelligence Dashboard."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

import httpx
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
import yfinance as yf

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="MacroClaw",
    page_icon="🦞",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Design tokens (Apple dark aesthetic) ──────────────────────────────────────
BG          = "#000000"
BG_ELEVATED = "#1d1d1f"
BG_CARD     = "#141414"
BORDER      = "rgba(255,255,255,0.08)"
BORDER_HL   = "rgba(255,255,255,0.16)"
TEXT_PRI    = "#f5f5f7"
TEXT_SEC    = "#a1a1a6"
TEXT_TER    = "#6e6e73"
ACCENT      = "#2997ff"
GREEN       = "#30d158"
RED         = "#ff453a"
ORANGE      = "#ff9f0a"
PURPLE      = "#bf5af2"

ASSET_COLORS = {
    "WTI Crude": ORANGE, "Brent Crude": "#ffd60a", "Gold": PURPLE,
    "DXY": "#32d74b", "USD/JPY": "#ff375f", "USD/CHF": "#5ac8fa"
}
SIGNAL_COLORS = {"BULLISH": GREEN, "BEARISH": RED, "NEUTRAL": ORANGE}
RISK_COLORS   = {"LOW": GREEN, "MEDIUM": ORANGE, "HIGH": RED, "UNKNOWN": TEXT_TER}

TRACKED = {
    "WTI Crude": "CL=F", "Brent Crude": "BZ=F", "Gold": "GC=F",
    "DXY": "DX=F", "USD/JPY": "JPY=X", "USD/CHF": "CHF=X"
}

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=SF+Mono&display=swap');

*, *::before, *::after { box-sizing: border-box; }

html, body, [class*="css"], .stApp {
    font-family: -apple-system, "SF Pro Display", "Inter", BlinkMacSystemFont,
                 "Segoe UI", Helvetica, Arial, sans-serif !important;
    -webkit-font-smoothing: antialiased;
}
.stApp {
    background-color: #000000 !important;
}

/* — hide chrome — */
#MainMenu, footer, .stDeployButton,
[data-testid="stToolbar"] { display: none !important; }

/* — scrollbar — */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #3a3a3c; border-radius: 10px; }

/* — sidebar — */
[data-testid="stSidebar"] {
    background: #0a0a0a !important;
    border-right: 1px solid rgba(255,255,255,0.06) !important;
}
[data-testid="stSidebar"] > div { padding-top: 0 !important; }
[data-testid="stSidebar"] * { color: #a1a1a6 !important; }
[data-testid="stSidebar"] textarea {
    background: #1c1c1e !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    border-radius: 10px !important;
    color: #f5f5f7 !important;
    font-size: 13px !important;
    line-height: 1.5 !important;
    resize: vertical !important;
    transition: border-color .2s !important;
}
[data-testid="stSidebar"] textarea:focus {
    border-color: rgba(41,151,255,0.5) !important;
    outline: none !important;
    box-shadow: 0 0 0 3px rgba(41,151,255,0.12) !important;
}
[data-testid="stSidebar"] .stSelectbox > div > div {
    background: #1c1c1e !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    border-radius: 10px !important;
    color: #f5f5f7 !important;
}

/* — main — */
.main .block-container {
    padding: 28px 40px 60px !important;
    max-width: 1440px !important;
}

/* — cards — */
.card {
    background: #141414;
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 18px;
    padding: 24px;
    transition: border-color .25s ease, box-shadow .25s ease;
    position: relative;
    overflow: hidden;
}
.card:hover {
    border-color: rgba(255,255,255,0.14);
    box-shadow: 0 20px 60px rgba(0,0,0,.6);
}
.card-sm { border-radius: 14px; padding: 18px 20px; }

/* — metric card — */
.metric-card {
    background: #141414;
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 20px;
    padding: 26px 24px 18px;
    position: relative;
    overflow: hidden;
    cursor: default;
    transition: all .3s cubic-bezier(.4,0,.2,1);
}
.metric-card:hover {
    border-color: rgba(255,255,255,0.16);
    transform: translateY(-2px);
    box-shadow: 0 24px 64px rgba(0,0,0,.7);
}
.metric-card .accent-line {
    position: absolute; top: 0; left: 0; right: 0; height: 2px;
    border-radius: 2px 2px 0 0;
}
.metric-card .bg-glyph {
    position: absolute; right: 18px; top: 50%; transform: translateY(-50%);
    font-size: 52px; opacity: 0.05; line-height: 1; pointer-events: none;
}
.metric-label {
    font-size: 11px; font-weight: 500; letter-spacing: .08em;
    text-transform: uppercase; color: #6e6e73; margin-bottom: 4px;
}
.metric-ticker {
    font-family: "SF Mono", "Fira Code", monospace;
    font-size: 11px; color: #3a3a3c; margin-bottom: 10px;
}
.metric-price {
    font-size: 36px; font-weight: 700;
    letter-spacing: -0.04em; color: #f5f5f7;
    line-height: 1; margin-bottom: 6px;
    font-variant-numeric: tabular-nums;
}
.metric-change {
    font-size: 14px; font-weight: 600; letter-spacing: -0.01em;
}
.metric-change.up   { color: #30d158; }
.metric-change.down { color: #ff453a; }
.metric-change.flat { color: #6e6e73; }
.metric-ohlc {
    margin-top: 10px;
    font-family: "SF Mono", "Fira Code", monospace;
    font-size: 10px; color: #3a3a3c; letter-spacing: .02em;
}

/* — section label — */
.section-label {
    font-size: 11px; font-weight: 600; letter-spacing: .1em;
    text-transform: uppercase; color: #6e6e73;
    margin: 32px 0 14px; display: flex; align-items: center; gap: 10px;
}
.section-label::after {
    content: ''; flex: 1; height: 1px; background: rgba(255,255,255,0.06);
}

/* — live badge — */
.live-badge {
    display: inline-flex; align-items: center; gap: 5px;
    padding: 3px 9px; border-radius: 999px;
    background: rgba(48,209,88,0.1); border: 1px solid rgba(48,209,88,0.2);
    font-size: 10px; font-weight: 600; color: #30d158; letter-spacing: .05em;
    text-transform: uppercase;
}
.live-dot {
    width: 5px; height: 5px; border-radius: 50%; background: #30d158;
    box-shadow: 0 0 6px #30d158; animation: blink 2s ease-in-out infinite;
}
@keyframes blink {
    0%,100% { opacity: 1; } 50% { opacity: .4; }
}

/* — news cards — */
.news-card {
    background: #141414; border: 1px solid rgba(255,255,255,0.06);
    border-radius: 14px; padding: 16px 18px; margin-bottom: 10px;
    transition: all .22s ease; cursor: default;
}
.news-card:hover {
    background: #1c1c1e; border-color: rgba(255,255,255,0.12);
    transform: translateY(-1px);
}
.news-headline {
    font-size: 14px; font-weight: 500; color: #f5f5f7;
    line-height: 1.45; margin-bottom: 10px;
}
.news-meta {
    display: flex; justify-content: space-between; align-items: center;
    font-size: 11px; color: #6e6e73;
    font-family: "SF Mono", monospace;
}
.tone-track {
    height: 2px; border-radius: 1px; background: rgba(255,255,255,0.05);
    margin-top: 10px; overflow: hidden;
}
.tone-fill { height: 100%; border-radius: 1px; }
.tone-tag {
    display: inline-block; padding: 2px 7px; border-radius: 4px;
    font-size: 9px; font-weight: 700; letter-spacing: .07em;
    text-transform: uppercase; margin-left: 6px; vertical-align: middle;
}

/* — brief — */
.exec-card {
    background: linear-gradient(145deg, #141414, #1a1a1a);
    border: 1px solid rgba(41,151,255,0.15);
    border-radius: 20px; padding: 28px 30px;
    font-size: 15px; line-height: 1.75; color: #a1a1a6;
    position: relative; overflow: hidden;
}
.exec-card::before {
    content: '';
    position: absolute; top: 0; left: 0; right: 0; height: 1px;
    background: linear-gradient(90deg, transparent, rgba(41,151,255,.5), transparent);
}
.risk-card {
    background: #141414; border: 1px solid rgba(255,255,255,0.07);
    border-radius: 20px; padding: 24px; text-align: center;
}
.risk-value {
    font-size: 40px; font-weight: 800; letter-spacing: -.04em;
    line-height: 1; margin: 8px 0 6px;
}
.risk-sub { font-size: 12px; color: #6e6e73; line-height: 1.5; }
.signal-row {
    display: flex; align-items: center; justify-content: space-between;
    padding: 13px 16px; margin-bottom: 8px;
    background: #1a1a1a; border: 1px solid rgba(255,255,255,0.05);
    border-radius: 12px; transition: border-color .2s;
}
.signal-row:hover { border-color: rgba(255,255,255,0.12); }
.signal-asset { font-size: 13px; font-weight: 500; color: #a1a1a6; }
.signal-pill {
    font-size: 11px; font-weight: 700; letter-spacing: .07em;
    text-transform: uppercase; padding: 4px 14px; border-radius: 999px;
}
.event-item {
    padding: 16px 20px; margin-bottom: 8px;
    background: #141414; border: 1px solid rgba(255,255,255,0.06);
    border-radius: 14px; transition: all .2s;
}
.event-item:hover { border-color: rgba(255,255,255,0.12); }
.event-title { font-size: 14px; font-weight: 500; color: #f5f5f7; margin-bottom: 6px; }
.event-impact { font-size: 13px; color: #6e6e73; line-height: 1.5; }
.rec-item {
    display: flex; gap: 12px; align-items: flex-start;
    padding: 14px 18px; margin-bottom: 8px;
    background: rgba(48,209,88,0.04);
    border: 1px solid rgba(48,209,88,0.1);
    border-radius: 12px;
}
.rec-num {
    min-width: 22px; height: 22px; background: rgba(48,209,88,0.15);
    border-radius: 50%; display: flex; align-items: center;
    justify-content: center; font-size: 11px; font-weight: 700;
    color: #30d158; flex-shrink: 0; margin-top: 1px;
}
.rec-text { font-size: 13px; color: #a1a1a6; line-height: 1.6; }
.dq-note {
    background: rgba(255,159,10,0.06); border: 1px solid rgba(255,159,10,0.15);
    border-radius: 12px; padding: 14px 18px;
    font-size: 13px; color: #a1a1a6; line-height: 1.5;
}
.empty-state {
    text-align: center; padding: 80px 20px;
}
.empty-icon { font-size: 56px; margin-bottom: 16px; opacity: .3; }
.empty-title { font-size: 20px; font-weight: 600; color: #f5f5f7; margin-bottom: 8px; }
.empty-sub { font-size: 14px; color: #6e6e73; }

/* — tabs — */
[data-testid="stTabs"] [role="tablist"] {
    background: #1c1c1e !important; border-radius: 12px !important;
    padding: 4px !important; gap: 2px !important;
    border: 1px solid rgba(255,255,255,0.07) !important;
}
[data-testid="stTabs"] [role="tab"] {
    border-radius: 9px !important; font-size: 13px !important;
    font-weight: 500 !important; color: #6e6e73 !important;
    padding: 9px 20px !important; border: none !important;
    transition: all .2s !important;
}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
    background: #2c2c2e !important; color: #f5f5f7 !important;
    box-shadow: 0 1px 4px rgba(0,0,0,.4) !important;
}

/* — buttons — */
button[kind="primary"] {
    background: #2997ff !important; border: none !important;
    border-radius: 980px !important; font-weight: 600 !important;
    font-size: 14px !important; letter-spacing: -.01em !important;
    transition: all .2s ease !important; color: #fff !important;
    box-shadow: 0 2px 12px rgba(41,151,255,.3) !important;
}
button[kind="primary"]:hover {
    background: #0a84ff !important;
    box-shadow: 0 4px 20px rgba(41,151,255,.4) !important;
    transform: scale(1.01) !important;
}
button[kind="primary"]:disabled {
    background: #2c2c2e !important; color: #6e6e73 !important;
    box-shadow: none !important; transform: none !important;
}
button[kind="secondary"] {
    background: #2c2c2e !important; border: 1px solid rgba(255,255,255,.1) !important;
    border-radius: 980px !important; font-weight: 500 !important;
    font-size: 13px !important; color: #f5f5f7 !important;
    transition: all .2s ease !important;
}
button[kind="secondary"]:hover {
    background: #3a3a3c !important; border-color: rgba(255,255,255,.2) !important;
}

/* — progress / spinner — */
.stProgress > div > div { background: #2997ff !important; border-radius: 999px !important; }
.stSpinner > div { border-top-color: #2997ff !important; }

/* — dataframe — */
[data-testid="stDataFrame"] {
    border-radius: 14px !important; overflow: hidden !important;
    border: 1px solid rgba(255,255,255,0.07) !important;
}

/* — misc — */
hr { border-color: rgba(255,255,255,0.06) !important; margin: 20px 0 !important; }
.stAlert { border-radius: 12px !important; }
</style>
""", unsafe_allow_html=True)


# ── Utilities ─────────────────────────────────────────────────────────────────

def _hex_to_rgba(h: str, a: float) -> str:
    h = h.lstrip("#")
    r, g, b = int(h[:2], 16), int(h[2:4], 16), int(h[4:], 16)
    return f"rgba({r},{g},{b},{a})"


def _http() -> httpx.Client:
    proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    return httpx.Client(proxy=proxy, timeout=12.0) if proxy else httpx.Client(timeout=12.0)


def _arrow(v: float) -> str:
    return "↑" if v > 0 else ("↓" if v < 0 else "→")


def _chart_theme() -> dict:
    return dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#0d0d0d",
        font=dict(family="-apple-system, Inter, sans-serif", color="#6e6e73", size=11),
        xaxis=dict(showgrid=False, linecolor="#2c2c2e", tickcolor="#2c2c2e",
                   showline=True, tickfont=dict(color="#6e6e73", size=10)),
        yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.04)",
                   linecolor="#2c2c2e", tickcolor="#2c2c2e",
                   showline=False, tickfont=dict(color="#6e6e73", size=10)),
    )


# ── Data fetchers ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def fetch_prices() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for label, ticker in TRACKED.items():
        try:
            h = yf.Ticker(ticker).history(period="2d", interval="1d", auto_adjust=True)
            if h.empty:
                raise ValueError("empty")
            last, prev = h.iloc[-1], h.iloc[-2] if len(h) >= 2 else h.iloc[-1]
            p = float(last["Close"]); pc = float(prev["Close"])
            chg = p - pc; pct = chg / pc * 100 if pc else 0.0
            out[label] = dict(
                ticker=ticker, price=p, prev_close=pc,
                change=chg, change_pct=pct,
                high=float(last["High"]), low=float(last["Low"]),
                open_=float(last["Open"]),
                volume=int(last.get("Volume") or 0),
                color=ASSET_COLORS[label],
            )
        except Exception as e:
            out[label] = dict(ticker=ticker, price=None, error=str(e), color=ASSET_COLORS[label])
    return out


@st.cache_data(ttl=300)
def fetch_ohlcv(ticker: str, period: str) -> pd.DataFrame:
    try:
        return yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=True)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def fetch_news(query: str, n: int = 10) -> list[dict]:
    url = (
        "https://api.gdeltproject.org/api/v2/doc/doc"
        f"?query={quote_plus(query)}&mode=ArtList&maxrecords={n}"
        "&timespan=72h&sort=DateDesc&format=json"
    )
    try:
        with _http() as c:
            r = c.get(url); r.raise_for_status()
            return r.json().get("articles", [])[:n]
    except Exception:
        return []


# ── Chart builders ────────────────────────────────────────────────────────────

def chart_sparkline(series: pd.Series, color: str) -> go.Figure:
    fig = go.Figure(go.Scatter(
        x=series.index, y=series.values, mode="lines",
        line=dict(color=color, width=1.5),
        fill="tozeroy", fillcolor=_hex_to_rgba(color, 0.07),
        hoverinfo="skip",
    ))
    fig.update_layout(
        height=52, margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        xaxis=dict(visible=False), yaxis=dict(visible=False),
    )
    return fig


def chart_candlestick(ticker: str, label: str, color: str, period: str) -> go.Figure:
    df = fetch_ohlcv(ticker, period)
    if df.empty:
        fig = go.Figure()
        fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#0d0d0d",
                          height=380, annotations=[dict(text="No data available",
                          x=0.5, y=0.5, xref="paper", yref="paper",
                          showarrow=False, font=dict(color="#6e6e73", size=14))])
        return fig

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.72, 0.28], vertical_spacing=0.0,
    )

    # Candlestick
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"],
        low=df["Low"], close=df["Close"], name="Price",
        increasing=dict(line=dict(color=GREEN, width=1), fillcolor=_hex_to_rgba(GREEN, 0.5)),
        decreasing=dict(line=dict(color=RED, width=1), fillcolor=_hex_to_rgba(RED, 0.5)),
        whiskerwidth=0.4, hoverlabel=dict(bgcolor="#1c1c1e"),
    ), row=1, col=1)

    # EMA 20
    ema = df["Close"].ewm(span=20).mean()
    fig.add_trace(go.Scatter(
        x=df.index, y=ema, name="EMA 20",
        line=dict(color=_hex_to_rgba(color, 0.6), width=1.2, dash="dot"),
        hovertemplate="EMA20 $%{y:,.2f}<extra></extra>",
    ), row=1, col=1)

    # Volume
    vol_colors = [
        _hex_to_rgba(GREEN, 0.4) if float(c) >= float(o) else _hex_to_rgba(RED, 0.4)
        for c, o in zip(df["Close"], df["Open"])
    ]
    if "Volume" in df.columns:
        fig.add_trace(go.Bar(
            x=df.index, y=df["Volume"], name="Vol",
            marker_color=vol_colors, showlegend=False,
            hovertemplate="Vol %{y:,.0f}<extra></extra>",
        ), row=2, col=1)

    base = _chart_theme()
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor=base["paper_bgcolor"],
        plot_bgcolor=base["plot_bgcolor"],
        font=base["font"],
        height=400,
        margin=dict(l=8, r=8, t=36, b=8),
        showlegend=True,
        legend=dict(orientation="h", y=1.05, x=0,
                    font=dict(size=10, color="#6e6e73"),
                    bgcolor="rgba(0,0,0,0)"),
        xaxis_rangeslider_visible=False,
        hovermode="x unified",
        hoverlabel=dict(bgcolor="#1c1c1e", bordercolor="#3a3a3c",
                        font=dict(color="#f5f5f7", size=11)),
    )
    # Row axes — set individually to avoid duplicate kwargs
    fig.update_yaxes(
        tickprefix="$", tickformat=",.0f",
        gridcolor="rgba(255,255,255,0.04)",
        linecolor="#2c2c2e", showline=False,
        tickfont=dict(color="#6e6e73", size=10),
        side="right", row=1, col=1,
    )
    fig.update_yaxes(
        showticklabels=False, gridcolor="rgba(255,255,255,0.03)",
        row=2, col=1,
    )
    fig.update_xaxes(
        showgrid=False, linecolor="#2c2c2e",
        tickfont=dict(color="#6e6e73", size=10),
        row=1, col=1,
    )
    fig.update_xaxes(
        showgrid=False, linecolor="#2c2c2e",
        tickfont=dict(color="#6e6e73", size=10),
        row=2, col=1,
    )
    return fig


def chart_normalised(period: str) -> go.Figure:
    fig = go.Figure()
    for label, ticker in TRACKED.items():
        df = fetch_ohlcv(ticker, period)
        if df.empty:
            continue
        s = df["Close"]
        norm = s / s.iloc[0] * 100
        color = ASSET_COLORS[label]
        fig.add_trace(go.Scatter(
            x=norm.index, y=norm.values, name=label,
            line=dict(color=color, width=2),
            fill="tozeroy" if label == "Gold" else None,
            fillcolor=_hex_to_rgba(color, 0.04),
            hovertemplate=f"<b>{label}</b> %{{x|%b %d}} idx=%{{y:.1f}}<extra></extra>",
        ))
    base = _chart_theme()
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor=base["paper_bgcolor"],
        plot_bgcolor=base["plot_bgcolor"],
        font=base["font"],
        height=220,
        margin=dict(l=8, r=8, t=32, b=8),
        showlegend=True,
        legend=dict(orientation="h", y=1.12, x=0,
                    font=dict(size=11, color="#6e6e73"),
                    bgcolor="rgba(0,0,0,0)"),
        hovermode="x unified",
        hoverlabel=dict(bgcolor="#1c1c1e", bordercolor="#3a3a3c",
                        font=dict(color="#f5f5f7", size=11)),
    )
    fig.update_xaxes(**base["xaxis"])
    fig.update_yaxes(**base["yaxis"], title_text="Index (base 100)",
                     title_font=dict(size=10, color="#6e6e73"))
    return fig


def chart_risk_gauge(risk: str) -> go.Figure:
    val = {"LOW": 16, "MEDIUM": 50, "HIGH": 84}.get(risk.upper(), 50)
    color = RISK_COLORS.get(risk.upper(), TEXT_TER)
    fig = go.Figure(go.Indicator(
        mode="gauge",
        value=val,
        domain=dict(x=[0, 1], y=[0, 1]),
        gauge=dict(
            axis=dict(
                range=[0, 100],
                tickvals=[0, 33, 66, 100],
                ticktext=["", "LOW", "MED", "HIGH"],
                tickcolor="#3a3a3c",
                tickfont=dict(size=9, color="#6e6e73"),
            ),
            bar=dict(color=color, thickness=0.22),
            bgcolor="rgba(0,0,0,0)",
            borderwidth=0,
            steps=[
                dict(range=[0,  33], color=_hex_to_rgba(GREEN,  0.1)),
                dict(range=[33, 66], color=_hex_to_rgba(ORANGE, 0.1)),
                dict(range=[66,100], color=_hex_to_rgba(RED,    0.1)),
            ],
            threshold=dict(
                line=dict(color=color, width=3),
                thickness=0.85, value=val,
            ),
        ),
    ))
    fig.update_layout(
        height=160, margin=dict(l=16, r=16, t=8, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def chart_signals(signals: dict[str, str]) -> go.Figure:
    if not signals:
        return go.Figure()
    assets, vals, colors, texts = [], [], [], []
    for asset, signal in signals.items():
        s = str(signal).upper()
        assets.append(asset.replace("_", " "))
        vals.append(1.0 if s == "BULLISH" else -1.0 if s == "BEARISH" else 0.0)
        colors.append(SIGNAL_COLORS.get(s, TEXT_TER))
        texts.append(s)

    fig = go.Figure(go.Bar(
        x=vals, y=assets, orientation="h",
        marker=dict(
            color=[_hex_to_rgba(c, 0.7) for c in colors],
            line=dict(color=colors, width=1.5),
        ),
        text=texts, textposition="inside",
        textfont=dict(color="#f5f5f7", size=11, family="-apple-system, Inter"),
        hovertemplate="%{y}: %{text}<extra></extra>",
    ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        height=max(180, len(assets)*40), margin=dict(l=0, r=0, t=0, b=0),
        showlegend=False,
        xaxis=dict(
            range=[-1.5, 1.5],
            tickvals=[-1, 0, 1],
            ticktext=["BEARISH", "NEUTRAL", "BULLISH"],
            gridcolor="rgba(255,255,255,0.05)",
            zeroline=True, zerolinecolor="rgba(255,255,255,0.08)", zerolinewidth=1,
            tickfont=dict(size=10, color="#6e6e73"),
            showline=False,
        ),
        yaxis=dict(
            gridcolor="rgba(0,0,0,0)", showline=False,
            tickfont=dict(color="#a1a1a6", size=12),
        ),
    )
    return fig


# ── Agent runner ──────────────────────────────────────────────────────────────

def run_analysis(query: str) -> dict:
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    from macroclaw.config.config import MacroClawConfig
    from macroclaw.agents.agent_loop import AgentLoop
    from macroclaw.agents.tool_registry import ToolRegistry
    from macroclaw.memory.manager import MemoryManager
    from macroclaw.tools.geopolitical_news_fetcher import GeopoliticalNewsFetcher
    from macroclaw.tools.commodity_data_fetcher import CommodityDataFetcher

    cfg = MacroClawConfig()
    reg = ToolRegistry()
    reg.register(GeopoliticalNewsFetcher(news_api_key=cfg.news_api_key))
    reg.register(CommodityDataFetcher(alpha_vantage_key=cfg.alpha_vantage_api_key))
    brief = asyncio.run(AgentLoop(cfg, reg, MemoryManager(enabled=False)).run(query))
    
    if brief and brief.commodity_action:
        try:
            from macroclaw.memory.predictions import save_prediction
            for ca in brief.commodity_action:
                sig_key = ca.asset.replace(" ", "_").upper()
                if sig_key not in brief.signals:
                    if "WTI" in ca.asset.upper(): sig_key = "WTI_CRUDE"
                    elif "BRENT" in ca.asset.upper(): sig_key = "BRENT_CRUDE"
                    elif "GOLD" in ca.asset.upper(): sig_key = "GOLD"
                    elif "DXY" in ca.asset.upper(): sig_key = "DXY"
                    elif "JPY" in ca.asset.upper(): sig_key = "USD_JPY"
                    elif "CHF" in ca.asset.upper(): sig_key = "USD_CHF"
                
                signal = brief.signals.get(sig_key, "NEUTRAL")
                save_prediction(ca.asset, ca.ticker, signal, ca.current_price, brief)
        except Exception as e:
            st.error(f"Error saving prediction: {e}")

    return brief.raw if brief.raw else {"executive_summary": str(brief.executive_summary)}


# ── Sidebar ───────────────────────────────────────────────────────────────────

def sidebar() -> dict:
    st.sidebar.markdown("""
    <div style="padding:28px 20px 20px;border-bottom:1px solid rgba(255,255,255,0.06)">
      <div style="font-size:22px;font-weight:800;color:#f5f5f7;letter-spacing:-.02em">
        🦞 MacroClaw
      </div>
      <div style="font-size:11px;color:#6e6e73;margin-top:3px">
        Macro Intelligence Platform
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.sidebar.markdown('<div style="height:16px"></div>', unsafe_allow_html=True)

    query = st.sidebar.text_area(
        "Analysis query", height=128, key="query",
        placeholder="Describe what you want to analyse…",
        value=(
            "Analyse the current geopolitical environment and its impact on "
            "Crude Oil (WTI and Brent) and Gold. Provide a full investment brief."
        ),
        label_visibility="collapsed",
    )

    st.sidebar.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)

    run = st.sidebar.button(
        "Run Analysis",
        use_container_width=True, type="primary",
        disabled=st.session_state.get("running", False),
    )

    st.sidebar.markdown('<div style="height:16px"></div>', unsafe_allow_html=True)
    st.sidebar.markdown(
        '<div style="font-size:11px;color:#6e6e73;letter-spacing:.06em;'
        'text-transform:uppercase;margin-bottom:8px">Chart Period</div>',
        unsafe_allow_html=True,
    )
    period = st.sidebar.selectbox("Period", ["1mo", "3mo", "6mo", "1y"],
                                  index=0, label_visibility="collapsed")

    st.sidebar.divider()
    auto = st.sidebar.checkbox("Auto-refresh prices", value=False)
    interval = 60
    if auto:
        interval = st.sidebar.slider("Interval (s)", 30, 300, 60, step=30)

    if st.sidebar.button("Clear cache", use_container_width=True):
        st.cache_data.clear()
        st.session_state.pop("brief", None)
        st.rerun()

    st.sidebar.markdown(
        f'<div style="position:fixed;bottom:20px;left:0;width:260px;'
        f'text-align:center;font-size:10px;color:#3a3a3c">'
        f'MacroClaw v2026.3.0</div>',
        unsafe_allow_html=True,
    )
    return dict(query=query, run=run, period=period, auto=auto, interval=interval)


# ── Tab: Market ───────────────────────────────────────────────────────────────

def tab_market(period: str) -> None:
    prices = fetch_prices()

    # Header row
    hc1, hc2 = st.columns([1, 1])
    with hc1:
        st.markdown(
            '<div class="section-label">'
            'Live Prices &nbsp;<span class="live-badge">'
            '<span class="live-dot"></span>LIVE</span></div>',
            unsafe_allow_html=True,
        )
    with hc2:
        now = datetime.now(timezone.utc)
        st.markdown(
            f'<div style="text-align:right;font-size:11px;color:#6e6e73;'
            f'font-family:SF Mono,monospace;padding-top:32px">'
            f'{now.strftime("%Y-%m-%d %H:%M:%S")} UTC</div>',
            unsafe_allow_html=True,
        )

    # Metric cards
    items = list(prices.items())
    for row_idx in range(0, len(items), 3):
        cols = st.columns(3, gap="medium")
        for j, (label, d) in enumerate(items[row_idx:row_idx+3]):
            color = d.get("color", TEXT_TER)
            with cols[j]:
                if d.get("price") is None:
                    st.markdown(
                        f'<div class="metric-card">'
                        f'<div class="metric-label">{label}</div>'
                        f'<div style="color:{RED};font-size:13px;margin-top:8px">'
                        f'⚠ {d.get("error","N/A")[:60]}</div></div>',
                        unsafe_allow_html=True,
                    )
                    continue

                p = d["price"]; pct = d["change_pct"]; chg = d["change"]
                cls = "up" if pct > 0 else ("down" if pct < 0 else "flat")
                arrow = _arrow(pct)
                icon = "🛢️" if "Crude" in label else "🥇" if label == "Gold" else "💵" if "DXY" in label else "💱"
                st.markdown(
                    f'<div class="metric-card">'
                    f'<div class="accent-line" style="background:{color}"></div>'
                    f'<div class="bg-glyph">{icon}</div>'
                    f'<div class="metric-label">{label}</div>'
                    f'<div class="metric-ticker">{d["ticker"]}</div>'
                    f'<div class="metric-price">${p:,.2f}</div>'
                    f'<div class="metric-change {cls}">'
                    f'{arrow} {pct:+.2f}% &nbsp;'
                    f'<span style="font-size:12px;font-weight:400;color:#6e6e73">'
                    f'({chg:+.2f})</span></div>'
                    f'<div class="metric-ohlc">'
                    f'O {d["open_"]:,.2f} &nbsp;·&nbsp; '
                    f'H {d["high"]:,.2f} &nbsp;·&nbsp; '
                    f'L {d["low"]:,.2f} &nbsp;·&nbsp; '
                    f'PC {d["prev_close"]:,.2f}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                # Sparkline
                df_sp = fetch_ohlcv(d["ticker"], "1mo")
                if not df_sp.empty:
                    st.plotly_chart(
                        chart_sparkline(df_sp["Close"], color),
                        use_container_width=True, config=dict(displayModeBar=False),
                        key=f"sparkline_{d['ticker']}_{label}",
                    )

    # Candlestick — per-asset tabs
    st.markdown('<div class="section-label">Price Charts</div>', unsafe_allow_html=True)
    
    def _tab_icon(lbl: str) -> str:
        if "Crude" in lbl: return "🛢️"
        if lbl == "Gold": return "🥇"
        if "DXY" in lbl: return "💵"
        return "💱"
        
    asset_tabs = st.tabs([
        f"  {_tab_icon(lbl)}  {lbl}  "
        for lbl in TRACKED
    ])

    for tab, (label, ticker) in zip(asset_tabs, TRACKED.items()):
        with tab:
            fig = chart_candlestick(ticker, label, ASSET_COLORS[label], period)
            st.plotly_chart(fig, use_container_width=True,
                            config=dict(displayModeBar=True, displaylogo=False, 
                            modeBarButtonsToRemove=['lasso2d', 'select2d']),
                            key=f"candlestick_{ticker}_{label}")

    # Normalised performance
    st.markdown('<div class="section-label">Relative Performance</div>', unsafe_allow_html=True)
    st.plotly_chart(chart_normalised(period), use_container_width=True,
                    config=dict(displayModeBar=False), key="normalised_perf_chart")


# ── Tab: News ─────────────────────────────────────────────────────────────────

def tab_news() -> None:
    st.markdown('<div class="section-label">Geopolitical Intelligence</div>',
                unsafe_allow_html=True)

    qc, bc = st.columns([5, 1])
    with qc:
        q = st.text_input("Search News", value="oil gold conflict OPEC sanctions war trade",
                          placeholder="Search…", label_visibility="collapsed",
                          key="news_q")
    with bc:
        if st.button("Fetch", use_container_width=True):
            st.cache_data.clear()

    articles = fetch_news(q)

    if not articles:
        st.markdown(
            '<div class="dq-note">⚠ GDELT returned no results. '
            'Rate limiting may be active — try again in a moment or simplify your query.</div>',
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        f'<div style="font-size:11px;color:#6e6e73;margin-bottom:16px">'
        f'{len(articles)} articles · GDELT Project · last 72 h</div>',
        unsafe_allow_html=True,
    )

    ca, cb = st.columns(2, gap="medium")
    for i, art in enumerate(articles):
        try:
            tone = float(art.get("tone") or 0)
        except (TypeError, ValueError):
            tone = 0.0

        pct = max(0, min(100, 50 + tone * 4))
        tone_color = RED if tone < -2 else (ORANGE if tone < 0 else GREEN)
        tone_label = "Risk" if tone < -1 else ("Neutral" if abs(tone) <= 1 else "Positive")
        emoji = "🔴" if tone < -2 else ("🟡" if tone < 0 else "🟢")

        title = art.get("title", "(no title)")
        source = art.get("domain", "")
        date_raw = str(art.get("seendate", ""))
        date_str = f"{date_raw[4:6]}/{date_raw[6:8]}" if len(date_raw) >= 8 else "—"
        url = art.get("url", "")
        link_html = (
            f'&nbsp;<a href="{url}" target="_blank" '
            f'style="color:{ACCENT};text-decoration:none;font-size:11px">↗</a>'
            if url else ""
        )

        html = (
            f'<div class="news-card">'
            f'<div class="news-headline">{emoji} {title}</div>'
            f'<div class="news-meta">'
            f'<span style="color:#6e6e73">{source}{link_html}</span>'
            f'<span style="display:flex;align-items:center;gap:6px">'
            f'<span class="tone-tag" style="background:{_hex_to_rgba(tone_color,.12)};'
            f'color:{tone_color}">{tone_label}</span>'
            f'<span>{date_str}</span>'
            f'</span></div>'
            f'<div class="tone-track">'
            f'<div class="tone-fill" style="width:{pct:.0f}%;background:{tone_color}"></div>'
            f'</div></div>'
        )
        (ca if i % 2 == 0 else cb).markdown(html, unsafe_allow_html=True)


# ── Tab: Brief ────────────────────────────────────────────────────────────────

def tab_brief(brief: dict) -> None:
    if not brief:
        st.markdown(
            '<div class="empty-state">'
            '<div class="empty-icon">🦞</div>'
            '<div class="empty-title">No analysis yet</div>'
            '<div class="empty-sub">Click <b>Run Analysis</b> in the sidebar to generate<br>'
            'a full macroeconomic investment brief.</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    # Executive summary
    st.markdown('<div class="section-label">Executive Summary</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="exec-card">{brief.get("executive_summary","")}</div>',
        unsafe_allow_html=True,
    )

    # Risk + Signals
    st.markdown('<div class="section-label">Risk Assessment & Signals</div>',
                unsafe_allow_html=True)
    rc, sc = st.columns([1, 1], gap="large")

    with rc:
        risk = str(brief.get("risk_level", "UNKNOWN")).upper()
        rcolor = RISK_COLORS.get(risk, TEXT_TER)
        rationale = brief.get("risk_rationale", "")
        st.markdown(
            f'<div class="risk-card">'
            f'<div style="font-size:11px;color:#6e6e73;text-transform:uppercase;'
            f'letter-spacing:.08em">Overall Risk</div>'
            f'<div class="risk-value" style="color:{rcolor}">{risk}</div>'
            f'<div class="risk-sub">{rationale}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        st.plotly_chart(chart_risk_gauge(risk), use_container_width=True,
                        config=dict(displayModeBar=False))

    with sc:
        signals = brief.get("signals", {})
        st.markdown(
            '<div style="font-size:11px;color:#6e6e73;text-transform:uppercase;'
            'letter-spacing:.08em;margin-bottom:12px">Directional Signals</div>',
            unsafe_allow_html=True,
        )
        if signals:
            st.plotly_chart(chart_signals(signals), use_container_width=True,
                            config=dict(displayModeBar=False))
            pills = ""
            for asset, sig in signals.items():
                sc2 = SIGNAL_COLORS.get(str(sig).upper(), TEXT_TER)
                pills += (
                    f'<span class="signal-pill" '
                    f'style="background:{_hex_to_rgba(sc2,.1)};'
                    f'color:{sc2};border:1px solid {_hex_to_rgba(sc2,.3)};margin:4px">'
                    f'{asset.replace("_"," ")} {sig}</span>'
                )
            st.markdown(f'<div style="margin-top:4px">{pills}</div>', unsafe_allow_html=True)

    # Commodity action
    com = brief.get("commodity_action", [])
    if com:
        st.markdown('<div class="section-label">Commodity Action</div>', unsafe_allow_html=True)
        rows = []
        for ca in com:
            chg = ca.get("change_pct_1d", 0)
            rows.append({
                "Asset": ca.get("asset", ""),
                "Ticker": ca.get("ticker", ""),
                "Price": f"${ca.get('current_price', 0):,.2f}",
                "1D Δ": f"{chg:+.2f}%" if isinstance(chg, (int, float)) else str(chg),
                "Trend (1M)": ca.get("period_trend", ""),
                "Geopolitical Link": ca.get("geopolitical_correlation", ""),
            })
        st.dataframe(
            pd.DataFrame(rows), use_container_width=True, hide_index=True,
            column_config={
                "Trend (1M)": st.column_config.TextColumn(width="large"),
                "Geopolitical Link": st.column_config.TextColumn(width="large"),
            },
        )

    # Key events
    events = brief.get("key_events", [])
    if events:
        st.markdown('<div class="section-label">Key Events</div>', unsafe_allow_html=True)
        for ev in events:
            loc = f" · {ev['location']}" if ev.get("location") else ""
            dt  = f" · {ev['date']}"    if ev.get("date")     else ""
            impact = ev.get("market_impact", "")
            st.markdown(
                f'<div class="event-item">'
                f'<div class="event-title">📍 {ev.get("event","")}'
                f'<span style="color:#6e6e73;font-weight:400">{loc}{dt}</span></div>'
                + (f'<div class="event-impact">→ {impact}</div>' if impact else "")
                + '</div>',
                unsafe_allow_html=True,
            )

    # Strategy
    strat = brief.get("investment_strategy", "")
    recs  = brief.get("recommendations", [])
    if strat or recs:
        st.markdown('<div class="section-label">Investment Strategy</div>', unsafe_allow_html=True)
        if strat:
            st.markdown(
                f'<div style="font-size:14px;color:#a1a1a6;line-height:1.75;margin-bottom:16px">'
                f'{strat}</div>',
                unsafe_allow_html=True,
            )
        for i, rec in enumerate(recs, 1):
            st.markdown(
                f'<div class="rec-item">'
                f'<div class="rec-num">{i}</div>'
                f'<div class="rec-text">{rec}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    # Data quality
    dq = brief.get("data_quality_notes", "")
    if dq:
        st.markdown(
            f'<div class="dq-note"><b>⚠ Data Quality:</b> {dq}</div>',
            unsafe_allow_html=True,
        )

    # Raw JSON
    with st.expander("Raw JSON"):
        st.json(brief)


# ── Main ──────────────────────────────────────────────────────────────────────


# ── Tab: Scoring ──────────────────────────────────────────────────────────────

def tab_scoring() -> None:
    st.markdown('<div class="section-label">Prediction Performance & Backtesting</div>', unsafe_allow_html=True)
    
    try:
        from macroclaw.memory.predictions import get_all_predictions
        preds = get_all_predictions()
    except Exception as e:
        st.warning(f"Could not load predictions: {e}")
        return

    if not preds:
        st.markdown('<div class="empty-state">No predictions saved yet. Run an analysis to track logic.</div>', unsafe_allow_html=True)
        return

    # Evaluate predictions
    wins = 0
    losses = 0
    pending = 0
    
    rows = []
    
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    
    for p in preds:
        # p is dict with id, timestamp, asset, ticker, signal, price_at_prediction, executive_summary
        t_str = p.get('timestamp', '')
        asset = p.get('asset', 'Unknown')
        ticker = p.get('ticker', '')
        signal = str(p.get('signal', '')).upper()
        old_price = float(p.get('price_at_prediction', 0))
        
        # Get current price
        try:
            df = fetch_ohlcv(ticker, "1d")
            if not df.empty:
                current_price = df.iloc[-1]["Close"]
            else:
                current_price = old_price
        except Exception:
            current_price = old_price
            
        change_pct = ((current_price - old_price) / old_price) * 100 if old_price > 0 else 0
        
        status = "PENDING"
        # Let's say if signal was BULLISH and change_pct > 0.1 -> WIN
        # If signal BEARISH and change_pct < -0.1 -> WIN
        if signal == "BULLISH":
            if change_pct > 0.1: status = "WIN 🟢"; wins += 1
            elif change_pct < -0.1: status = "LOSS 🔴"; losses += 1
            else: pending += 1
        elif signal == "BEARISH":
            if change_pct < -0.1: status = "WIN 🟢"; wins += 1
            elif change_pct > 0.1: status = "LOSS 🔴"; losses += 1
            else: pending += 1
        else:
            status = "NEUTRAL ➖"
            pending += 1
            
        date_short = t_str[:16].replace("T", " ") if t_str else "Unknown"
        rows.append({
            "Date": date_short,
            "Asset": asset,
            "Signal": signal,
            "Pred Price": f"${old_price:,.2f}",
            "Current Price": f"${current_price:,.2f}",
            "Change %": f"{change_pct:+.2f}%",
            "Result": status
        })
        
    # Metrics
    c1, c2, c3, c4 = st.columns(4)
    total = wins + losses
    win_rate = (wins / total * 100) if total > 0 else 0
    c1.metric("Win Rate", f"{win_rate:.1f}%")
    c2.metric("Wins 🟢", wins)
    c3.metric("Losses 🔴", losses)
    c4.metric("Pending/Neutral ➖", pending)
    
    st.dataframe(
        pd.DataFrame(rows), 
        use_container_width=True, 
        hide_index=True 
    )
def main() -> None:
    st.session_state.setdefault("brief", {})
    st.session_state.setdefault("running", False)
    st.session_state.setdefault("last_refresh", time.time())

    opts = sidebar()

    # Page title
    st.markdown(
        '<div style="margin-bottom:24px">'
        '<h1 style="font-size:34px;font-weight:800;color:#f5f5f7;'
        'letter-spacing:-.04em;margin:0;line-height:1">MacroClaw</h1>'
        '<p style="font-size:14px;color:#6e6e73;margin:4px 0 0">Macroeconomic &amp; '
        'Geopolitical Investment Intelligence</p>'
        '</div>',
        unsafe_allow_html=True,
    )

    t_market, t_news, t_brief, t_scoring = st.tabs([
        "  📈  Market  ",
        "  🌍  News  ",
        "  📋  Brief  ",
        "  🎯  Scoring & Win Rate  ",
    ])

    with t_market:
        tab_market(opts["period"])

    with t_news:
        tab_news()

    with t_brief:
        if opts["run"] and not st.session_state.running:
            st.session_state.running = True
            steps = [
                (10, "Starting MacroClaw…"),
                (30, "Fetching geopolitical news…"),
                (55, "Fetching commodity prices…"),
                (80, "Synthesising…"),
                (95, "Writing investment brief…"),
            ]
            pb = st.progress(0)
            for pct, msg in steps:
                pb.progress(pct, text=msg)
                time.sleep(0.25)
            try:
                result = run_analysis(opts["query"])
                pb.progress(100, text="Done ✓")
                time.sleep(0.4)
                pb.empty()
                st.session_state.brief = result
                st.toast("Investment brief ready.", icon="✅")
            except Exception as e:
                pb.empty()
                import traceback; traceback.print_exc()
                st.error(f"Analysis failed: {e}")
            st.session_state.running = False
            st.rerun()

        tab_brief(st.session_state.brief)

    # Auto-refresh
    if opts["auto"]:
        elapsed = time.time() - st.session_state.last_refresh
        if elapsed >= opts["interval"]:
            st.session_state.last_refresh = time.time()
            st.cache_data.clear()
            st.rerun()
        st.sidebar.markdown(
            f'<div style="font-size:10px;color:#6e6e73;text-align:center;margin-top:4px">'
            f'Refresh in {int(opts["interval"] - elapsed)}s</div>',
            unsafe_allow_html=True,
        )
        
    with t_scoring:
        tab_scoring()


if __name__ == "__main__":
    main()
