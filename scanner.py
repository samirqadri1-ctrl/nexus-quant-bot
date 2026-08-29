import os
import requests
import numpy as np

# TELEGRAM CONFIG (Loaded from GitHub Secrets)
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

UNIVERSE = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "DOTUSDT",
    "BNBUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT",
    "OPUSDT", "POLUSDT", "INJUSDT", "FETUSDT",
    "RENDERUSDT", "SUIUSDT", "ATOMUSDT"
]

API = "https://api.binance.com"

def send_telegram(text):
    if not TOKEN or not CHAT_ID:
        print("Telegram credentials missing!")
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        res = requests.post(url, json=payload, timeout=10)
        print(f"Telegram response: {res.status_code}")
    except Exception as e:
        print(f"Telegram error: {e}")

def get_json(endpoint):
    try:
        res = requests.get(API + endpoint, timeout=10)
        return res.json()
    except Exception as e:
        print(f"API error: {e}")
        return None

def run_scanner():
    signals_found = []
    
    for symbol in UNIVERSE:
        data = get_json(f"/api/v3/klines?symbol={symbol}&interval=1h&limit=50")
        if not data or len(data) < 30:
            continue
            
        closes = np.array([float(x[4]) for x in data])
        highs = np.array([float(x[2]) for x in data])
        lows = np.array([float(x[3]) for x in data])
        
        price = closes[-1]
        high24 = np.max(highs[-24:])
        low24 = np.min(lows[-24:])
        
        # Simple RSI calculation
        delta = np.diff(closes)
        gain = (delta > 0) * delta
        loss = (delta < 0) * -delta
        avg_gain = np.mean(gain[-14:])
        avg_loss = np.mean(loss[-14:])
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            
        # Strategy filters
        if rsi > 70 or rsi < 30:
            continue
            
        if high24 > low24 and (high24 - low24) / low24 > 0.15:
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
            f"📊 *RSI Level:* {round(rsi, 1)}\n"
            f"💰 *Max Profit ($10):* +$0.30\n"
            f"📉 *Max Loss ($10):* -$0.15\n\n"
            f"⚡ *Status:* All Advanced Filters Passed!"
        )
        signals_found.append(msg)

    # Send signals or status to Telegram
    if signals_found:
        for s in signals_found[:2]:
            send_telegram(s)
    else:
        no_trade_msg = (
            "🔴 *STICKY DECISION BOARD*\n\n"
            "🔴 *NO TRADE* — market filtered or choppy, waiting for safe setup."
        )
        send_telegram(no_trade_msg)

if __name__ == "__main__":
    run_scanner()
