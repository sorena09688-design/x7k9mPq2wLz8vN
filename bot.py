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
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT"
]
INTERVAL = "15min"
HTF_INTERVAL = "4hour"

RSI_PERIOD = 14
EMA_FAST = 9
EMA_SLOW = 21
EMA_TREND = 100
ADX_THRESHOLD = 0
VOLUME_MULT = 0.1
RSI_LONG_MIN = 0
RSI_SHORT_MAX = 100
MIN_SCORE = 0
SEND_DIAGNOSTIC = True


def get_klines(symbol, interval="15min"):
    symbol_kucoin = symbol.replace("USDT", "-USDT")
    url = "https://api.kucoin.com/api/v1/market/candles?type=" + interval + "&symbol=" + symbol_kucoin
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        if data.get("code") != "200000":
            print("خطا در دریافت داده " + symbol)
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
        print("خطا: " + str(e))
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

    df["vol_ma"] = df["volume"].rolling(20).mean()

    return df


def check_signal(df, df_htf, symbol):
    if df is None or df_htf is None:
        return None, None
    if len(df) < 3 or len(df_htf) < 50:
        return None, None

    last = df.iloc[-2]

    # ==== نسخه تست: بدون نیاز به کراس، فقط موقعیت EMA ====
    cross_up = last["ema_fast"] > last["ema_slow"]
    cross_down = last["ema_fast"] < last["ema_slow"]

    if not (cross_up or cross_down):
        return None, None

    price = last["close"]
    reasons = []
    score = 0

    if cross_up:
        score = 3
        reasons.append("✅ EMA9 بالای EMA21")
        reasons.append("✅ RSI = " + str(round(last["rsi"], 2)))
        reasons.append("✅ ADX = " + str(round(last["adx"], 2)))

        diagnostic = {
            "symbol": symbol, "direction": "لانگ", "score": score,
            "reasons": reasons, "price": round(price, 4)
        }

        if score >= MIN_SCORE:
            sl = round(price - (last["atr"] * 1.5), 4)
            tp1 = round(price + (last["atr"] * 2), 4)
            tp2 = round(price + (last["atr"] * 4), 4)
            return {
                "type": "لانگ 🟢", "symbol": symbol, "price": round(price, 4),
                "rsi": round(last["rsi"], 2), "adx": round(last["adx"], 2),
                "score": score, "reasons": reasons,
                "sl": sl, "tp1": tp1, "tp2": tp2,
            }, diagnostic
        return None, diagnostic

    if cross_down:
        score = 3
        reasons.append("✅ EMA9 زیر EMA21")
        reasons.append("✅ RSI = " + str(round(last["rsi"], 2)))
        reasons.append("✅ ADX = " + str(round(last["adx"], 2)))

        diagnostic = {
            "symbol": symbol, "direction": "شورت", "score": score,
            "reasons": reasons, "price": round(price, 4)
        }

        if score >= MIN_SCORE:
            sl = round(price + (last["atr"] * 1.5), 4)
            tp1 = round(price - (last["atr"] * 2), 4)
            tp2 = round(price - (last["atr"] * 4), 4)
            return {
                "type": "شورت 🔴", "symbol": symbol, "price": round(price, 4),
                "rsi": round(last["rsi"], 2), "adx": round(last["adx"], 2),
                "score": score, "reasons": reasons,
                "sl": sl, "tp1": tp1, "tp2": tp2,
            }, diagnostic
        return None, diagnostic

    return None, None


async def main():
    bot = Bot(token=BOT_TOKEN)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    signals_found = 0
    diagnostics = []

    for symbol in SYMBOLS:
        df = get_klines(symbol, INTERVAL)
        df_htf = get_klines(symbol, HTF_INTERVAL)
        if df is None or df_htf is None:
            continue
        df = calc_indicators(df)
        df_htf = calc_indicators(df_htf)
        sig, diag = check_signal(df, df_htf, symbol)

        if diag:
            diagnostics.append(diag)

        if sig:
            signals_found += 1
            reasons_text = "\n".join(sig["reasons"])
            msg = (
                "🚨 <b>سیگنال " + sig["type"] + "</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "📌 <b>ارز:</b> " + sig["symbol"] + "\n"
                "💰 <b>قیمت ورود:</b> " + str(sig["price"]) + "\n"
                "⭐ <b>امتیاز تأیید:</b> " + str(sig["score"]) + "/5\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "<b>📊 دلایل سیگنال:</b>\n" + reasons_text + "\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "📊 <b>RSI:</b> " + str(sig["rsi"]) + "\n"
                "📈 <b>ADX:</b> " + str(sig["adx"]) + "\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "🛑 <b>حد ضرر:</b> " + str(sig["sl"]) + "\n"
                "🎯 <b>هدف اول:</b> " + str(sig["tp1"]) + "\n"
                "🎯 <b>هدف دوم:</b> " + str(sig["tp2"]) + "\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "⏰ <b>زمان:</b> " + now + "\n"
                "⏱ <b>تایم‌فریم:</b> " + INTERVAL + " | تأیید: " + HTF_INTERVAL
            )
            await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
            print("سیگنال ارسال شد: " + symbol)

    if signals_found == 0:
        print(now + " | سیگنالی پیدا نشد")
        if SEND_DIAGNOSTIC:
            report = "📋 <b>گزارش تشخیصی - " + now + "</b>\n"
            report += "⏱ تایم‌فریم: " + INTERVAL + "\n"
            report += "━━━━━━━━━━━━━━━━━━\n"
            report += "<b>سیگنالی پیدا نشد.</b>\n"

            if diagnostics:
                report += "نمادهای دارای شرایط:\n\n"
                for d in diagnostics:
                    report += "📌 <b>" + d["symbol"] + "</b> (" + d["direction"] + ")\n"
                    report += "⭐ امتیاز: <b>" + str(d["score"]) + "/5</b>\n"
                    report += "💰 قیمت: " + str(d["price"]) + "\n"
                    report += "─────────\n"
            else:
                report += "هیچ نمادی شرایط اولیه رو نداشت."

            await bot.send_message(chat_id=CHAT_ID, text=report, parse_mode="HTML")
            print("گزارش تشخیصی ارسال شد.")
    else:
        print(now + " | " + str(signals_found) + " سیگنال ارسال شد")


if __name__ == "__main__":
    asyncio.run(main())
