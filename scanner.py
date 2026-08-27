import os
import requests
import numpy as np

# TELEGRAM CONFIG
TOKEN = "8832255995:AAHAdTkjtwP7Fns-8a17nMC3ldRq2XT4S_c"
CHAT_ID = "7203569246"

UNIVERSE = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "DOTUSDT", "APTUSDT",
    "BNBUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "ARBUSDT",
    "OPUSDT", "POLUSDT", "INJUSDT", "FETUSDT", "NEARUSDT",
    "RENDERUSDT", "SUIUSDT", "ATOMUSDT", "DOGEUSDT", "XRPUSDT"
]

API = "https://api.binance.com"

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def get_json(endpoint):
    try:
        res = requests.get(f"{API}{endpoint}", timeout=10)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass
    return None

def calculate_ema(prices, period):
    if len(prices) < period:
        return None
    weights = np.exp(np.linspace(-1., 0., period))
    weights /= weights.sum()
    a = np.convolve(prices, weights, mode='full')[:len(prices)]
    return a[period-1]

def calculate_rsi(prices, period=14):
    if len(prices) <= period:
        return 50.0
    deltas = np.diff(prices)
    seed = deltas[:period]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    if down == 0:
        return 100.0
    rs = up / down
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi

def check_market():
    klines = get_json(f"/api/v3/klines?symbol=BTCUSDT&interval=5m&limit=100")
    if not klines:
        return True 
    closes = np.array([float(x[4]) for x in klines])
    e20 = calculate_ema(closes, 20)
    e50 = calculate_ema(closes, 50)
    if e20 is not None and e50 is not None:
        return closes[-1] > e20 and e20 > e50
    return True

def run_scanner():
    bull = check_market()
    signals_found = []

    for symbol in UNIVERSE:
        # Fetch data: 5m (for RSI & Volume), 15m, 1h, 4h, 1d
        k5 = get_json(f"/api/v3/klines?symbol={symbol}&interval=5m&limit=50")
        k15 = get_json(f"/api/v3/klines?symbol={symbol}&interval=15m&limit=50")
        k1h = get_json(f"/api/v3/klines?symbol={symbol}&interval=1h&limit=50")
        k4h = get_json(f"/api/v3/klines?symbol={symbol}&interval=4h&limit=50")
        k1d = get_json(f"/api/v3/klines?symbol={symbol}&interval=1d&limit=30")
        ticker = get_json(f"/api/v3/ticker/24hr?symbol={symbol}")

        if not k5 or not k15 or not k1h or not k4h or not k1d or not ticker:
            continue

        c5 = np.array([float(x[4]) for x in k5])
        v5 = np.array([float(x[5]) for x in k5])
        c15 = np.array([float(x[4]) for x in k15])
        c1h = np.array([float(x[4]) for x in k1h])
        c4h = np.array([float(x[4]) for x in k4h])
        c1d = np.array([float(x[4]) for x in k1d])
        
        price = float(ticker['lastPrice'])
        high24h = float(ticker['highPrice'])
        low24h = float(ticker['lowPrice'])

        # 1. RSI Overbought / Healthy Check (Reject if overheated > 78 or too weak < 35)
        rsi_val = calculate_rsi(c5, 14)
        if rsi_val > 78 or rsi_val < 35:
            continue

        # 2. Volume Spike & Liquidity Validation (Current volume vs 20-period average)
        avg_vol = np.mean(v5[-21:-1]) if len(v5) > 20 else np.mean(v5)
        current_vol = v5[-1]
        if avg_vol > 0 and current_vol < avg_vol * 0.9:
            continue

        # 3. Multi-Timeframe EMA Alignment (15m, 1h, 4h, 1D)
        e9_15 = calculate_ema(c15, 9)
        e21_15 = calculate_ema(c15, 21)
        e50_1h = calculate_ema(c1h, 50)
        e50_4h = calculate_ema(c4h, 50)
        e20_1d = calculate_ema(c1d, 20)

        mtf_short = (e9_15 and e21_15 and e9_15 > e21_15)
        trend_higher = (e50_1h and price > e50_1h) and (e50_4h and price > e50_4h) and (e20_1d and price > e20_1d)

        if not mtf_short or not trend_higher:
            continue

        # 4. Volatility Buffer (Not right at 24h high)
        if high24h > low24h and (high24h - price) / high24h < 0.005:
            continue

        # All filters passed successfully!
        tp = round(price * 1.03, 4)
        sl = round(price * 0.985, 4)
        coin_name = symbol.replace("USDT", "")

        msg = (
            f"🚨 *NEXUS QUANT AI SIGNAL* 🚨\n\n"
            f"🪙 *Coin:* {coin_name} / USDT\n"
            f"📈 *Direction:* LONG (BUY)\n"
            f"💲 *Entry Price:* ${price}\n"
            f"🎯 *Take Profit (+3%):* ${tp}\n"
            f"🛑 *Stop Loss (-1.5%):* ${sl}\n"
            f"📊 *RSI Level:* {round(rsi_val, 1)}\n"
            f"💰 *Max Profit ($10):* +$0.30\n"
            f"📉 *Max Loss ($10):* -$0.15\n\n"
            f"⚡ *Status:* All Advanced Filters Passed!"
        )
        signals_found.append(msg)

    # Send signals to Telegram
    if signals_found:
        for s in signals_found[:2]: 
            send_telegram(s)
    else:
        print("No signals matched criteria in this run.")

if __name__ == "__main__":
    run_scanner()
