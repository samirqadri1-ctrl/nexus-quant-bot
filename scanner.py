import os
import time
import requests
import numpy as np
from datetime import datetime, timezone

# =========================================================
# NEXUS QUANT AI — TELEGRAM LIVE SCANNER
# =========================================================

API = "https://api.binance.com"

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SCAN_INTERVAL_SECONDS = 600       # 10 minutes
SIGNAL_COOLDOWN_SECONDS = 3600    # same coin won't repeat for 1 hour

UNIVERSE = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "DOTUSDT",
    "BNBUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT",
    "OPUSDT", "POLUSDT", "INJUSDT", "FETUSDT",
    "RENDERUSDT", "SUIUSDT", "ATOMUSDT"
]

last_signal_time = {}

def log(message):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{now}] {message}", flush=True)

def send_telegram(text):
    if not TOKEN or not CHAT_ID:
        log("ERROR: Telegram credentials missing.")
        return False

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text}

    try:
        response = requests.post(url, json=payload, timeout=15)
        log(f"Telegram HTTP {response.status_code}: {response.text[:500]}")
        return response.ok
    except Exception as e:
        log(f"Telegram connection error: {e}")
        return False

def get_json(endpoint):
    try:
        response = requests.get(API + endpoint, timeout=15)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        log(f"Binance API error: {e}")
        return None

def calculate_rsi(closes, period=14):
    if len(closes) <= period:
        return None
    delta = np.diff(closes)
    gains = np.where(delta > 0, delta, 0)
    losses = np.where(delta < 0, -delta, 0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_ema(values, period):
    if len(values) < period:
        return None
    values = np.asarray(values, dtype=float)
    multiplier = 2 / (period + 1)
    ema_value = np.mean(values[:period])
    for price in values[period:]:
        ema_value = ((price - ema_value) * multiplier) + ema_value
    return ema_value

def signal_allowed(symbol):
    now = time.time()
    last_time = last_signal_time.get(symbol, 0)
    if now - last_time < SIGNAL_COOLDOWN_SECONDS:
        return False
    return True

def analyze_symbol(symbol):
    data = get_json(f"/api/v3/klines?symbol={symbol}&interval=1h&limit=100")
    if not data or len(data) < 50:
        return None

    closes = np.array([float(x[4]) for x in data], dtype=float)
    highs = np.array([float(x[2]) for x in data], dtype=float)
    lows = np.array([float(x[3]) for x in data], dtype=float)
    volumes = np.array([float(x[5]) for x in data], dtype=float)
    price = closes[-1]

    rsi = calculate_rsi(closes)
    if rsi is None:
        return None

    ema9 = calculate_ema(closes, 9)
    ema21 = calculate_ema(closes, 21)
    ema50 = calculate_ema(closes, 50)
    if not ema9 or not ema21 or not ema50:
        return None

    high24 = np.max(highs[-24:])
    low24 = np.min(lows[-24:])
    if low24 <= 0:
        return None

    range_percent = ((high24 - low24) / low24) * 100
    avg_volume = np.mean(volumes[-21:-1])
    current_volume = volumes[-1]
    volume_ratio = (current_volume / avg_volume if avg_volume > 0 else 0)

    score = 50
    reasons = []

    if ema9 > ema21:
        score += 10
        reasons.append("EMA9 > EMA21")
    if price > ema50:
        score += 10
        reasons.append("Price > EMA50")
    if 45 <= rsi <= 65:
        score += 15
        reasons.append("Healthy RSI")
    elif 65 < rsi <= 70:
        score += 5
        reasons.append("RSI elevated")
    elif rsi > 70:
        score -= 20
        reasons.append("RSI OVERBOUGHT")
    elif rsi < 35:
        score -= 15
        reasons.append("RSI weak")

    if volume_ratio >= 1.1:
        score += 10
        reasons.append("Volume confirmation")
    if range_percent <= 15:
        score += 5
        reasons.append("Controlled volatility")
    else:
        score -= 15
        reasons.append("High volatility")

    score = max(0, min(100, score))

    if rsi > 70 or range_percent > 15 or ema9 <= ema21 or score < 70:
        return None

    tp = price * 1.03
    sl = price * 0.985

    return {
        "symbol": symbol,
        "price": price,
        "rsi": rsi,
        "score": score,
        "tp": tp,
        "sl": sl,
        "volume_ratio": volume_ratio,
        "range_percent": range_percent,
        "reasons": reasons
    }

def build_signal_message(signal):
    coin = signal["symbol"].replace("USDT", "")
    return (
        "🧠 NEXUS QUANT AI\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🪙 Coin: {coin}/USDT\n"
        "📈 Direction: LONG / BUY\n\n"
        f"💰 Entry: ${signal['price']:.8f}\n"
        f"🎯 Take Profit +3%: ${signal['tp']:.8f}\n"
        f"🛑 Stop Loss -1.5%: ${signal['sl']:.8f}\n\n"
        f"⭐ AI Score: {signal['score']}%\n"
        f"📊 RSI: {signal['rsi']:.1f}\n"
        f"📦 Volume Ratio: {signal['volume_ratio']:.2f}x\n"
        f"📉 24H Range: {signal['range_percent']:.2f}%\n\n"
        "✅ FILTER STATUS: PASSED\n\n"
        "Reasons:\n" + "\n".join(f"• {r}" for r in signal["reasons"])
    )

def run_scanner():
    log("NEXUS QUANT AI SCANNER STARTED")
    signals_found = []

    for symbol in UNIVERSE:
        try:
            signal = analyze_symbol(symbol)
            if signal and signal_allowed(symbol):
                signals_found.append(signal)
        except Exception as e:
            log(f"{symbol}: error: {e}")

    if signals_found:
        signals_found.sort(key=lambda x: x["score"], reverse=True)
        for signal in signals_found[:2]:
            message = build_signal_message(signal)
            if send_telegram(message):
                last_signal_time[signal["symbol"]] = time.time()
    else:
        log("NO VALID SIGNALS FOUND.")
        send_telegram(
            "🛡️ NEXUS QUANT AI\n\n"
            "NO TRADE\n"
            "Market filtered or no safe setup.\n"
            "Waiting for confirmation."
        )

if __name__ == "__main__":
    run_scanner()
