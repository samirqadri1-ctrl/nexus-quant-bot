import os
import time
import requests
import numpy as np
from datetime import datetime, timezone

# =========================================================
# NEXUS QUANT AI — TELEGRAM LIVE SCANNER
# =========================================================

API = "https://api.binance.com"

# IMPORTANT:
# Add these two values in Hugging Face / GitHub:
# Settings -> Secrets
#
# TELEGRAM_BOT_TOKEN = your new Telegram bot token
# TELEGRAM_CHAT_ID   = your Telegram chat ID

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SCAN_INTERVAL_SECONDS = 600       # 10 minutes
SIGNAL_COOLDOWN_SECONDS = 3600    # same coin won't repeat for 1 hour

UNIVERSE = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "DOTUSDT",
    "BNBUSDT",
    "ADAUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "OPUSDT",
    "POLUSDT",
    "INJUSDT",
    "FETUSDT",
    "RENDERUSDT",
    "SUIUSDT",
    "ATOMUSDT"
]

last_signal_time = {}


# =========================================================
# LOGGING
# =========================================================

def log(message):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{now}] {message}", flush=True)


# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(text):

    if not TOKEN:
        log("ERROR: TELEGRAM_BOT_TOKEN is missing.")
        return False

    if not CHAT_ID:
        log("ERROR: TELEGRAM_CHAT_ID is missing.")
        return False

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": text
    }

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=15
        )

        log(
            f"Telegram HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

        if response.ok:
            return True

        return False

    except Exception as e:
        log(f"Telegram connection error: {e}")
        return False


# =========================================================
# BINANCE API
# =========================================================

def get_json(endpoint):

    try:

        response = requests.get(
            API + endpoint,
            timeout=15
        )

        response.raise_for_status()

        return response.json()

    except Exception as e:

        log(f"Binance API error: {e}")

        return None


# =========================================================
# RSI
# =========================================================

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


# =========================================================
# EMA
# =========================================================

def calculate_ema(values, period):

    if len(values) < period:
        return None

    values = np.asarray(values, dtype=float)

    multiplier = 2 / (period + 1)

    ema_value = np.mean(values[:period])

    for price in values[period:]:
        ema_value = (
            (price - ema_value) * multiplier
            + ema_value
        )

    return ema_value


# =========================================================
# SIGNAL COOLDOWN
# =========================================================

def signal_allowed(symbol):

    now = time.time()

    last_time = last_signal_time.get(symbol, 0)

    if now - last_time < SIGNAL_COOLDOWN_SECONDS:

        remaining = int(
            SIGNAL_COOLDOWN_SECONDS
            - (now - last_time)
        )

        log(
            f"{symbol}: signal cooldown active "
            f"({remaining}s remaining)"
        )

        return False

    return True


# =========================================================
# ANALYZE ONE COIN
# =========================================================

def analyze_symbol(symbol):

    data = get_json(
        f"/api/v3/klines"
        f"?symbol={symbol}"
        f"&interval=1h"
        f"&limit=100"
    )

    if not data or len(data) < 50:

        log(f"{symbol}: insufficient market data")

        return None

    closes = np.array(
        [float(x[4]) for x in data],
        dtype=float
    )

    highs = np.array(
        [float(x[2]) for x in data],
        dtype=float
    )

    lows = np.array(
        [float(x[3]) for x in data],
        dtype=float
    )

    volumes = np.array(
        [float(x[5]) for x in data],
        dtype=float
    )

    price = closes[-1]

    # -----------------------------------------------------
    # RSI
    # -----------------------------------------------------

    rsi = calculate_rsi(closes)

    if rsi is None:
        return None

    # -----------------------------------------------------
    # EMA
    # -----------------------------------------------------

    ema9 = calculate_ema(closes, 9)
    ema21 = calculate_ema(closes, 21)
    ema50 = calculate_ema(closes, 50)

    if not ema9 or not ema21 or not ema50:
        return None

    # -----------------------------------------------------
    # 24H RANGE
    # -----------------------------------------------------

    high24 = np.max(highs[-24:])
    low24 = np.min(lows[-24:])

    if low24 <= 0:
        return None

    range_percent = (
        (high24 - low24)
        / low24
    ) * 100

    # -----------------------------------------------------
    # VOLUME
    # -----------------------------------------------------

    avg_volume = np.mean(volumes[-21:-1])

    current_volume = volumes[-1]

    volume_ratio = (
        current_volume / avg_volume
        if avg_volume > 0
        else 0
    )

    # -----------------------------------------------------
    # SCORE
    # -----------------------------------------------------

    score = 50

    reasons = []

    # Trend
    if ema9 > ema21:
        score += 10
        reasons.append("EMA9 > EMA21")

    if price > ema50:
        score += 10
        reasons.append("Price > EMA50")

    # RSI
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

    # Volume
    if volume_ratio >= 1.1:
        score += 10
        reasons.append("Volume confirmation")

    # Volatility
    if range_percent <= 15:
        score += 5
        reasons.append("Controlled volatility")

    else:
        score -= 15
        reasons.append("High volatility")

    score = max(0, min(100, score))

    # -----------------------------------------------------
    # HARD SAFETY FILTERS
    # -----------------------------------------------------

    if rsi > 70:

        log(
            f"{symbol}: SKIP — RSI {rsi:.1f} overbought"
        )

        return None

    if range_percent > 15:

        log(
            f"{symbol}: SKIP — "
            f"24H range {range_percent:.1f}%"
        )

        return None

    if ema9 <= ema21:

        log(
            f"{symbol}: SKIP — trend not confirmed"
        )

        return None

    # -----------------------------------------------------
    # FINAL SCORE FILTER
    # -----------------------------------------------------

    if score < 70:

        log(
            f"{symbol}: SKIP — score {score}"
        )

        return None

    # -----------------------------------------------------
    # SIGNAL
    # -----------------------------------------------------

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


# =========================================================
# BUILD TELEGRAM MESSAGE
# =========================================================

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

        "Reasons:\n"
        + "\n".join(
            f"• {reason}"
            for reason in signal["reasons"]
        )
    )


# =========================================================
# SCANNER
# =========================================================

def run_scanner():

    log("========================================")
    log("NEXUS QUANT AI SCANNER STARTED")
    log("========================================")

    signals_found = []

    for symbol in UNIVERSE:

        try:

            log(f"Scanning {symbol}...")

            signal = analyze_symbol(symbol)

            if signal is None:
                continue

            if not signal_allowed(symbol):
                continue

            signals_found.append(signal)

            log(
                f"SIGNAL FOUND: "
                f"{symbol} | "
                f"Score {signal['score']} | "
                f"RSI {signal['rsi']:.1f}"
            )

        except Exception as e:

            log(
                f"{symbol}: scanner error: {e}"
            )

    # -----------------------------------------------------
    # SEND TOP 2 SIGNALS
    # -----------------------------------------------------

    if signals_found:

        signals_found.sort(
            key=lambda x: x["score"],
            reverse=True
        )

        for signal in signals_found[:2]:

            message = build_signal_message(signal)

            success = send_telegram(message)

            if success:

                last_signal_time[
                    signal["symbol"]
                ] = time.time()

                log(
                    f"Telegram signal sent: "
                    f"{signal['symbol']}"
                )

    else:

        log("NO VALID SIGNALS FOUND.")

        # Enabled status message to send "NO TRADE" alert
        SEND_NO_TRADE_STATUS = True

        if SEND_NO_TRADE_STATUS:

            send_telegram(
                "🛡️ NEXUS QUANT AI\n\n"
                "NO TRADE\n"
                "Market filtered or no safe setup.\n"
                "Waiting for confirmation."
            )


# =========================================================
# CONTINUOUS WORKER
# =========================================================

def main():

    log("NEXUS worker booting...")

    if not TOKEN:
        log(
            "❌ TELEGRAM_BOT_TOKEN NOT FOUND"
        )

    if not CHAT_ID:
        log(
            "❌ TELEGRAM_CHAT_ID NOT FOUND"
        )

    if not TOKEN or not CHAT_ID:

        log(
            "Please configure Secrets."
        )

        return

    # Test Telegram connection first

    log("Testing Telegram connection...")

    test_message = (
        "🟢 NEXUS QUANT AI ONLINE\n\n"
        "Telegram connection test successful."
    )

    if not send_telegram(test_message):

        log(
            "❌ TELEGRAM TEST FAILED."
        )

        return

    log(
        "✅ Telegram connection verified."
    )

    # Continuous scanning

    while True:

        try:

            run_scanner()

        except Exception as e:

            log(
                f"MAIN SCANNER ERROR: {e}"
            )

        log(
            f"Next scan in "
            f"{SCAN_INTERVAL_SECONDS // 60} minutes..."
        )

        time.sleep(
            SCAN_INTERVAL_SECONDS
        )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    main()
