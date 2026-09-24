import os
import requests
import pandas as pd
import numpy as np
from telegram import Bot
import asyncio
from datetime import datetime

BOT_TOKEN = os.environ.get('BOT_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')

if not BOT_TOKEN:
    print("خطا: BOT_TOKEN تنظیم نشده!")
    exit(1)
if not CHAT_ID:
    print("خطا: CHAT_ID تنظیم نشده!")
    exit(1)

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT",
    "LTCUSDT", "ATOMUSDT", "UNIUSDT", "AAVEUSDT", "ZECUSDT"
]
INTERVAL = "30min"
HTF_INTERVAL = "4hour"

RSI_PERIOD = 14
EMA_FAST = 20
EMA_SLOW = 50
EMA_TREND = 200
ADX_THRESHOLD = 22
VOLUME_MULT = 1.2
RSI_LONG_MIN = 52
RSI_SHORT_MAX = 48
MIN_SCORE = 3


def get_klines(symbol, interval="30min"):
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
    df["ema_trend"] = df["close"].ewm(span=EMA_TREND, adjust=False).mean()

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

    df["macd"] = df["close"].ewm(span=12, adjust=False).mean() - df["close"].ewm(span=26, adjust=False).mean()
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    df["vol_ma"] = df["volume"].rolling(20).mean()

    return df


def check_signal(df, df_htf, symbol):
    if len(df) < 3 or df_htf is None or len(df_htf) < 200:
        return None

    last = df.iloc[-2]
    prev = df.iloc[-3]

    cross_up = (prev["ema_fast"] <= prev["ema_slow"]) and (last["ema_fast"] > last["ema_slow"])
    cross_down = (prev["ema_fast"] >= prev["ema_slow"]) and (last["ema_fast"] < last["ema_slow"])

    if not (cross_up or cross_down):
        return None

    price = last["close"]
    reasons = []
    score = 0

    rsi_ok_long = last["rsi"] > RSI_LONG_MIN
    rsi_ok_short = last["rsi"] < RSI_SHORT_MAX
    vol_ok = last["volume"] > (last["vol_ma"] * VOLUME_MULT)
    adx_ok = last["adx"] > ADX_THRESHOLD
    macd_ok_long = last["macd"] > last["macd_signal"]
    macd_ok_short = last["macd"] < last["macd_signal"]
    trend_up = df_htf["close"].iloc[-1] > df_htf["ema_trend"].iloc[-1]
    trend_down = df_htf["close"].iloc[-1] < df_htf["ema_trend"].iloc[-1]

    if cross_up:
        if rsi_ok_long: score += 1; reasons.append(f"✅ RSI = {round(last['rsi'], 2)} (بالای {RSI_LONG_MIN})")
        else: reasons.append(f"❌ RSI = {round(last['rsi'], 2)} (زیر {RSI_LONG_MIN})")

        if adx_ok: score += 1; reasons.append(f"✅ ADX = {round(last['adx'], 2)} (روند قوی)")
        else: reasons.append(f"❌ ADX = {round(last['adx'], 2)} (روند ضعیف)")

        if vol_ok: score += 1; reasons.append(f"✅ حجم = {round(last['volume']/last['vol_ma'], 2)}x میانگین")
        else: reasons.append(f"❌ حجم پایین")

        if macd_ok_long: score += 1; reasons.append(f"✅ MACD صعودی")
        else: reasons.append(f"❌ MACD نزولی")

        if trend_up: score += 1; reasons.append(f"✅ روند ۴ساعته صعودی (بالای EMA200)")
        else: reasons.append(f"❌ روند ۴ساعته نزولی")

        if score >= MIN_SCORE:
            sl = round(price - (last["atr"] * 1.5), 4)
            tp1 = round(price + (last["atr"] * 2), 4)
            tp2 = round(price + (last["atr"] * 4), 4)
            return {
                "type": "لانگ 🟢", "symbol": symbol, "price": round(price, 4),
                "rsi": round(last["rsi"], 2), "adx": round(last["adx"], 2),
                "ema_fast": round(last["ema_fast"], 4), "ema_slow": round(last["ema_slow"], 4),
                "score": score, "reasons": reasons,
                "sl": sl, "tp1": tp1, "tp2": tp2,
                "vol_ratio": round(last["volume"]/last["vol_ma"], 2)
            }

    if cross_down:
        if rsi_ok_short: score += 1; reasons.append(f"✅ RSI = {round(last['rsi'], 2)} (زیر {RSI_SHORT_MAX})")
        else: reasons.append(f"❌ RSI = {round(last['rsi'], 2)} (بالای {RSI_SHORT_MAX})")

        if adx_ok: score += 1; reasons.append(f"✅ ADX = {round(last['adx'], 2)} (روند قوی)")
        else: reasons.append(f"❌ ADX = {round(last['adx'], 2)} (روند ضعیف)")

        if vol_ok: score += 1; reasons.append(f"✅ حجم = {round(last['volume']/last['vol_ma'], 2)}x میانگین")
        else: reasons.append(f"❌ حجم پایین")

        if macd_ok_short: score += 1; reasons.append(f"✅ MACD نزولی")
        else: reasons.append(f"❌ MACD صعودی")

        if trend_down: score += 1; reasons.append(f"✅ روند ۴ساعته نزولی (زیر EMA200)")
        else: reasons.append(f"❌ روند ۴ساعته صعودی")

        if score >= MIN_SCORE:
            sl = round(price + (last["atr"] * 1.5), 4)
            tp1 = round(price - (last["atr"] * 2), 4)
            tp2 = round(price - (last["atr"] * 4), 4)
            return {
                "type": "شورت 🔴", "symbol": symbol, "price": round(price, 4),
                "rsi": round(last["rsi"], 2), "adx": round(last["adx"], 2),
                "ema_fast": round(last["ema_fast"], 4), "ema_slow": round(last["ema_slow"], 4),
                "score": score, "reasons": reasons,
                "sl": sl, "tp1": tp1, "tp2": tp2,
                "vol_ratio": round(last["volume"]/last["vol_ma"], 2)
            }

    return None


async def main():
    bot = Bot(token=BOT_TOKEN)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    signals_found = 0

    for symbol in SYMBOLS:
        df = get_klines(symbol, INTERVAL)
        df_htf = get_klines(symbol, HTF_INTERVAL)
        if df is None or df_htf is None:
            continue
        df = calc_indicators(df)
        df_htf = calc_indicators(df_htf)
        sig = check_signal(df, df_htf, symbol)
        if sig:
            signals_found += 1
            reasons_text = "\n".join(sig["reasons"])
            msg = (
                f"🚨 <b>سیگنال {sig['type']}</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📌 <b>ارز:</b> {sig['symbol']}\n"
                f"💰 <b>قیمت ورود:</b> {sig['price']}\n"
                f"⭐ <b>امتیاز تأیید:</b> {sig['score']}/5\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"<b>📊 دلایل سیگنال:</b>\n{reasons_text}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📉 <b>EMA{EMA_FAST}:</b> {sig['ema_fast']}\n"
                f"📈 <b>EMA{EMA_SLOW}:</b> {sig['ema_slow']}\n"
                f"📊 <b>RSI:</b> {sig['rsi']}\n"
                f"📈 <b>ADX:</b> {sig['adx']}\n"
                f"📊 <b>نسبت حجم:</b> {sig['vol_ratio']}x\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🛑 <b>حد ضرر:</b> {sig['sl']}\n"
                f"🎯 <b>هدف اول:</b> {sig['tp1']}\n"
                f"🎯 <b>هدف دوم:</b> {sig['tp2']}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"⏰ <b>زمان:</b> {now}\n"
                f"⏱ <b>تایم‌فریم:</b> {INTERVAL} | تأیید: {HTF_INTERVAL}"
            )
            await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
            print(f"سیگنال ارسال شد: {symbol}")

    if signals_found == 0:
        print(f"{now} | سیگنالی پیدا نشد")


if __name__ == "__main__":
    asyncio.run(main())
