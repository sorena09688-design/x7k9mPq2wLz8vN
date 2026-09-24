import os
import requests
import pandas as pd
import numpy as np
from telegram import Bot
import asyncio
import time
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
    "LTCUSDT", "ATOMUSDT", "UNIUSDT", "AAVEUSDT", "ZECUSDT",
    "TRXUSDT", "MATICUSDT", "ETCUSDT", "FILUSDT", "APTUSDT",
    "ARBUSDT", "OPUSDT", "NEARUSDT", "INJUSDT", "SUIUSDT",
    "SEIUSDT", "TIAUSDT", "IMXUSDT", "GRTUSDT", "SANDUSDT",
    "MANAUSDT", "AXSUSDT", "FTMUSDT", "ALGOUSDT", "EOSUSDT",
    "XLMUSDT", "VETUSDT", "THETAUSDT", "EGLDUSDT", "FLOWUSDT",
    "CHZUSDT", "ENJUSDT", "ZILUSDT", "IOTAUSDT", "ONEUSDT",
    "ANKRUSDT", "CRVUSDT", "COMPUSDT", "SNXUSDT", "MKRUSDT",
    "SUSHIUSDT", "YFIUSDT", "BALUSDT", "RENUSDT", "KNCUSDT",
    "ZRXUSDT", "OMGUSDT", "BATUSDT", "LRCUSDT", "STORJUSDT",
    "OCEANUSDT", "FETUSDT", "RNDRUSDT", "AGIXUSDT", "ARUSDT",
    "KSMUSDT", "KAVAUSDT", "RUNEUSDT", "WAVESUSDT", "CELOUSDT",
    "BANDUSDT", "NMRUSDT", "CTSIUSDT", "CVCUSDT", "DENTUSDT",
    "HOTUSDT", "IOSTUSDT", "IOTXUSDT", "MTLUSDT", "NKNUSDT",
    "OGNUSDT", "POLYUSDT", "REQUSDT", "RLCUSDT", "TRBUSDT",
    "UMAUSDT", "XEMUSDT", "XTZUSDT", "YFIIUSDT", "ZENUSDT",
    "DASHUSDT", "DCRUSDT", "LSKUSDT", "NEOUSDT", "QTUMUSDT",
    "RVNUSDT", "SCUSDT", "WTCUSDT", "ZECUSDT", "ZRXUSDT"
]

# حذف تکراری‌ها
SYMBOLS = list(dict.fromkeys(SYMBOLS))

INTERVAL = "15min"
HTF_INTERVAL = "4hour"

RSI_PERIOD = 14
EMA_FAST = 9
EMA_SLOW = 21
EMA_TREND = 100
ADX_THRESHOLD = 20
VOLUME_MULT = 1.2
MIN_SCORE = 4

RSI_LONG_MIN = 30
RSI_LONG_MAX = 65
RSI_SHORT_MIN = 35
RSI_SHORT_MAX = 70
RSI_REVERSAL_LONG = 30
RSI_REVERSAL_SHORT = 70

SEND_DIAGNOSTIC = False  # برای ۱۰۰ ارز، گزارش تشخیصی رو خاموش کن


def get_klines(symbol, interval="15min"):
    symbol_kucoin = symbol.replace("USDT", "-USDT")
    url = "https://api.kucoin.com/api/v1/market/candles?type=" + interval + "&symbol=" + symbol_kucoin
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        if data.get("code") != "200000":
            return None
        candles = data["data"]
        df = pd.DataFrame(candles, columns=[
            "time", "open", "close", "high", "low", "volume", "turnover"
        ])
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = df[c].astype(float)
        df = df.iloc[::-1].reset_index(drop=True)
        return df
    except Exception:
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


def build_message(sig, now, signal_type):
    reasons_text = "\n".join(sig["reasons"])
    msg = (
        "🚨 <b>سیگنال " + signal_type + " - " + sig["type"] + "</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 <b>ارز:</b> " + sig["symbol"] + "\n"
        "💰 <b>قیمت ورود:</b> " + str(sig["price"]) + "\n"
        "⭐ <b>امتیاز تأیید:</b> " + str(sig["score"]) + "/6\n"
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
    return msg


def make_signal(symbol, price, last, reasons, score, direction):
    if direction == "لانگ 🟢":
        sl = round(price - (last["atr"] * 1.5), 4)
        tp1 = round(price + (last["atr"] * 2), 4)
        tp2 = round(price + (last["atr"] * 4), 4)
    else:
        sl = round(price + (last["atr"] * 1.5), 4)
        tp1 = round(price - (last["atr"] * 2), 4)
        tp2 = round(price - (last["atr"] * 4), 4)
    return {
        "type": direction, "symbol": symbol, "price": round(price, 4),
        "rsi": round(last["rsi"], 2), "adx": round(last["adx"], 2),
        "score": score, "reasons": reasons,
        "sl": sl, "tp1": tp1, "tp2": tp2,
    }


def check_signal(df, df_htf, symbol):
    if df is None or df_htf is None:
        return None, None, None
    if len(df) < 5 or len(df_htf) < 50:
        return None, None, None

    last = df.iloc[-2]
    prev = df.iloc[-3]
    price = last["close"]
    rsi = last["rsi"]

    volume_required = last["volume"] > (last["vol_ma"] * VOLUME_MULT)
    htf_up = df_htf["close"].iloc[-1] > df_htf["ema_trend"].iloc[-1]
    htf_down = df_htf["close"].iloc[-1] < df_htf["ema_trend"].iloc[-1]
    adx_required = last["adx"] > ADX_THRESHOLD

    # ====== ۱. سیگنال برگشت لانگ ======
    if rsi < RSI_REVERSAL_LONG and rsi > prev["rsi"] and last["close"] > prev["close"]:
        macd_required = last["macd"] > last["macd_signal"]
        if not (volume_required and macd_required and adx_required and htf_up):
            return None, None, None

        reasons = []
        reasons.append("🔄 برگشت از اشباع فروش (RSI: " + str(round(rsi, 2)) + ")")
        reasons.append("✅ حجم بالا (اجباری)")
        reasons.append("✅ MACD صعودی (اجباری)")
        reasons.append("✅ ADX = " + str(round(last["adx"], 2)) + " (اجباری)")
        reasons.append("✅ روند ۴ساعته صعودی (اجباری)")
        score = 5

        diagnostic = {"symbol": symbol, "direction": "برگشت لانگ", "score": score,
                      "reasons": reasons, "price": round(price, 4)}

        if score >= MIN_SCORE:
            sig = make_signal(symbol, price, last, reasons, score, "لانگ 🟢")
            return sig, diagnostic, "برگشت"
        return None, diagnostic, None

    # ====== ۲. سیگنال برگشت شورت ======
    if rsi > RSI_REVERSAL_SHORT and rsi < prev["rsi"] and last["close"] < prev["close"]:
        macd_required = last["macd"] < last["macd_signal"]
        if not (volume_required and macd_required and adx_required and htf_down):
            return None, None, None

        reasons = []
        reasons.append("🔄 برگشت از اشباع خرید (RSI: " + str(round(rsi, 2)) + ")")
        reasons.append("✅ حجم بالا (اجباری)")
        reasons.append("✅ MACD نزولی (اجباری)")
        reasons.append("✅ ADX = " + str(round(last["adx"], 2)) + " (اجباری)")
        reasons.append("✅ روند ۴ساعته نزولی (اجباری)")
        score = 5

        diagnostic = {"symbol": symbol, "direction": "برگشت شورت", "score": score,
                      "reasons": reasons, "price": round(price, 4)}

        if score >= MIN_SCORE:
            sig = make_signal(symbol, price, last, reasons, score, "شورت 🔴")
            return sig, diagnostic, "برگشت"
        return None, diagnostic, None

    # ====== ۳. سیگنال کراس معمولی ======
    cross_up = (prev["ema_fast"] <= prev["ema_slow"]) and (last["ema_fast"] > last["ema_slow"])
    cross_down = (prev["ema_fast"] >= prev["ema_slow"]) and (last["ema_fast"] < last["ema_slow"])

    if not (cross_up or cross_down):
        return None, None, None

    if not volume_required:
        return None, None, None

    reasons = []

    if cross_up:
        macd_required = last["macd"] > last["macd_signal"]
        if not macd_required:
            return None, None, None

        rsi_ok = (rsi > RSI_LONG_MIN) and (rsi < RSI_LONG_MAX)
        score = 3
        reasons.append("✅ کراس صعودی EMA9/21")
        reasons.append("✅ حجم بالا (اجباری)")
        reasons.append("✅ MACD صعودی (اجباری)")

        if rsi_ok:
            score += 1
            reasons.append("✅ RSI = " + str(round(rsi, 2)) + " (محدوده امن)")
        else:
            reasons.append("❌ RSI = " + str(round(rsi, 2)) + " (خارج از محدوده)")

        if adx_required:
            score += 1
            reasons.append("✅ ADX = " + str(round(last["adx"], 2)))
        else:
            reasons.append("❌ ADX = " + str(round(last["adx"], 2)))

        if htf_up:
            score += 1
            reasons.append("✅ روند ۴ساعته صعودی")
        else:
            reasons.append("❌ روند ۴ساعته نزولی")

        diagnostic = {"symbol": symbol, "direction": "کراس لانگ", "score": score,
                      "reasons": reasons, "price": round(price, 4)}

        if score >= MIN_SCORE:
            sig = make_signal(symbol, price, last, reasons, score, "لانگ 🟢")
            return sig, diagnostic, "کراس"
        return None, diagnostic, None

    if cross_down:
        macd_required = last["macd"] < last["macd_signal"]
        if not macd_required:
            return None, None, None

        rsi_ok = (rsi > RSI_SHORT_MIN) and (rsi < RSI_SHORT_MAX)
        score = 3
        reasons.append("✅ کراس نزولی EMA9/21")
        reasons.append("✅ حجم بالا (اجباری)")
        reasons.append("✅ MACD نزولی (اجباری)")

        if rsi_ok:
            score += 1
            reasons.append("✅ RSI = " + str(round(rsi, 2)) + " (محدوده امن)")
        else:
            reasons.append("❌ RSI = " + str(round(rsi, 2)) + " (خارج از محدوده)")

        if adx_required:
            score += 1
            reasons.append("✅ ADX = " + str(round(last["adx"], 2)))
        else:
            reasons.append("❌ ADX = " + str(round(last["adx"], 2)))

        if htf_down:
            score += 1
            reasons.append("✅ روند ۴ساعته نزولی")
        else:
            reasons.append("❌ روند ۴ساعته صعودی")

        diagnostic = {"symbol": symbol, "direction": "کراس شورت", "score": score,
                      "reasons": reasons, "price": round(price, 4)}

        if score >= MIN_SCORE:
            sig = make_signal(symbol, price, last, reasons, score, "شورت 🔴")
            return sig, diagnostic, "کراس"
        return None, diagnostic, None

    return None, None, None


async def main():
    bot = Bot(token=BOT_TOKEN)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    signals_found = 0
    processed = 0

    for symbol in SYMBOLS:
        try:
            df = get_klines(symbol, INTERVAL)
            time.sleep(0.15)
            df_htf = get_klines(symbol, HTF_INTERVAL)
            time.sleep(0.15)

            if df is None or df_htf is None:
                continue

            df = calc_indicators(df)
            df_htf = calc_indicators(df_htf)
            sig, diag, signal_type = check_signal(df, df_htf, symbol)

            processed += 1

            if sig:
                signals_found += 1
                msg = build_message(sig, now, signal_type)
                await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
                print("سیگنال ارسال شد: " + symbol + " | " + signal_type)

        except Exception as e:
            print("خطا در " + symbol + ": " + str(e))
            continue

    print(now + " | پردازش شده: " + str(processed) + " | سیگنال: " + str(signals_found))


if __name__ == "__main__":
    asyncio.run(main())
