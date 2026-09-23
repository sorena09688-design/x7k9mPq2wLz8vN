import os
import requests
import pandas as pd
import numpy as np
from telegram import Bot
from telegram.request import HTTPXRequest
import asyncio

BOT_TOKEN = os.environ.get('BOT_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
# ---- تست فیک ----
BOT_TOKEN = os.environ.get('BOT_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
print("تست: توکن و چت آیدی خونده شد")
# -----------------

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT",
    "MATICUSDT", "LTCUSDT", "ATOMUSDT", "UNIUSDT", "AAVEUSDT",
    "ZECUSDT", "FILUSDT", "NEARUSDT", "APTUSDT", "ARBUSDT"
]
INTERVAL = "15min"
HTF_INTERVAL = "4hour"

RSI_PERIOD = 14
EMA_FAST = 20
EMA_SLOW = 50
ADX_THRESHOLD = 0
VOLUME_MULT = 0.1

def get_klines(symbol, interval="15min"):
    symbol_kucoin = symbol.replace("USDT", "-USDT")
    url = f"https://api.kucoin.com/api/v1/market/candles?type={interval}&symbol={symbol_kucoin}"
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        if data.get("code") != "200000":
            print(f"خطا در دریافت داده {symbol}")
            return None
        candles = data["data"]
        df = pd.DataFrame(candles, columns=[
            "time", "open", "close", "high", "low", "volume", "turnover"
        ])
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = df[c].astype(float)
        df = df.iloc[::-1].reset_index(drop=True)
        return df
    except Exception as e:
        print(f"خطا: {e}")
        return None

def calc_indicators(df):
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0).rolling(RSI_PERIOD).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(RSI_PERIOD).mean()
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))
    df["ema_fast"] = df["close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=EMA_SLOW, adjust=False).mean()
    df["tr"] = np.maximum(df["high"] - df["low"],
                np.maximum(abs(df["high"] - df["close"].shift()),
                           abs(df["low"] - df["close"].shift())))
    df["atr"] = df["tr"].rolling(14).mean()
    df["up"] = df["high"].diff()
    df["down"] = -df["low"].diff()
    df["plus_dm"] = np.where((df["up"] > df["down"]) & (df["up"] > 0), df["up"], 0)
    df["minus_dm"] = np.where((df["down"] > df["up"]) & (df["down"] > 0), df["down"], 0)
    df["plus_di"] = 100 * (df["plus_dm"].rolling(14).mean() / df["atr"])
    df["minus_di"] = 100 * (df["minus_dm"].rolling(14).mean() / df["atr"])
    df["dx"] = 100 * abs(df["plus_di"] - df["minus_di"]) / (df["plus_di"] + df["minus_di"])
    df["adx"] = df["dx"].rolling(14).mean()
    df["vol_ma"] = df["volume"].rolling(20).mean()
    return df

def check_signal(df, df_htf, symbol):
    if len(df) < 3 or df_htf is None or len(df_htf) < 50:
        return None
    last = df.iloc[-2]
    prev = df.iloc[-3]
    cross_up = last["ema_fast"] > last["ema_slow"]
    cross_down = last["ema_fast"] < last["ema_slow"]
    if not (cross_up or cross_down):
        return None
    rsi_long = last["rsi"] > 0
    rsi_short = last["rsi"] < 100
    vol_ok = last["volume"] > (last["vol_ma"] * VOLUME_MULT)
    adx_ok = last["adx"] > ADX_THRESHOLD
    htf_up = True
    htf_down = True
    price = last["close"]
    if cross_up and rsi_long and vol_ok and adx_ok and htf_up:
        return {"type": "لانگ 🟢", "symbol": symbol, "price": round(price, 4),
                "rsi": round(last["rsi"], 2), "adx": round(last["adx"], 2)}
    if cross_down and rsi_short and vol_ok and adx_ok and htf_down:
        return {"type": "شورت 🔴", "symbol": symbol, "price": round(price, 4),
                "rsi": round(last["rsi"], 2), "adx": round(last["adx"], 2)}
    return None

async def main():
    bot = Bot(token=BOT_TOKEN)
    await bot.send_message(chat_id=CHAT_ID, text="🧪 تست فیک: ربات به تلگرام وصله!")
    print("پیام تست ارسال شد!")
    for symbol in SYMBOLS:
        df = get_klines(symbol, INTERVAL)
        df_htf = get_klines(symbol, HTF_INTERVAL)
        if df is None or df_htf is None:
            continue
        df = calc_indicators(df)
        df_htf = calc_indicators(df_htf)
        sig = check_signal(df, df_htf, symbol)
        if sig:
            msg = (f"🚨 <b>سیگنال {sig['type']}</b>\n\n"
                   f"📌 {sig['symbol']}\n💰 {sig['price']}\n"
                   f"📊 RSI: {sig['rsi']}\n📈 ADX: {sig['adx']}")
            await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
            print(f"سیگنال ارسال شد: {symbol}")

if __name__ == "__main__":
    asyncio.run(main())
