import os
import json
import requests
import pandas as pd
import numpy as np
from telegram import Bot
import asyncio
import time
from datetime import datetime, timezone, timedelta

BOT_TOKEN = os.environ.get('BOT_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')

if not BOT_TOKEN:
    print("خطا: BOT_TOKEN تنظیم نشده!")
    exit(1)
if not CHAT_ID:
    print("خطا: CHAT_ID تنظیم نشده!")
    exit(1)

HISTORY_FILE = "signals_history.json"
SCENARIO_HISTORY_FILE = "scenarios_history.json"
COOLDOWN_MINUTES = 30
SCENARIO_COOLDOWN_MINUTES = 60
NO_SIGNAL_COOLDOWN_MINUTES = 0

IRAN_TZ = timezone(timedelta(hours=3, minutes=30))

SYMBOLS = [
    "OPUSDT", "ZECUSDT", "PUMPUSDT", "WLDUSDT", "TIAUSDT",
    "PEPEUSDT", "ARBUSDT", "ALLOUSDT", "BOMEUSDT", "APTUSDT",
    "LABUSDT", "FLOKIUSDT", "UNIUSDT", "FILUSDT", "KAITOUSDT",
    "TAOUSDT", "BONKUSDT", "ORDIUSDT", "NEARUSDT", "STXUSDT",
    "SHIBUSDT", "XLMUSDT", "NOTUSDT", "AVAXUSDT", "DOGEUSDT",
    "AAVEUSDT", "LDOUSDT", "ATOMUSDT", "KASUSDT", "PYTHUSDT",
    "ADAUSDT", "SUIUSDT", "BMTUSDT", "ETHFIUSDT", "XRPUSDT",
    "WIFUSDT", "JASMYUSDT", "LUNCUSDT", "HMSTRUSDT", "HBARUSDT",
    "POLUSDT", "HEMIUSDT", "HEIUSDT", "SEIUSDT", "JUPUSDT",
    "DOTUSDT", "IMXUSDT", "LINKUSDT", "HYPEUSDT", "FETUSDT",
    "ICPUSDT", "TUTUSDT", "LTCUSDT", "ONDOUSDT", "PROMUSDT",
    "BRENTOILUSDT", "CAKEUSDT", "RENDERUSDT", "ZROUSDT", "TRXUSDT",
    "INJUSDT", "GIGGLEUSDT", "XAUTUSDT", "PAXGUSDT", "BNBUSDT",
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BCHUSDT", "ALGOUSDT",
    "GRAMUSDT", "ENAUSDT", "ACEUSDT", "HOMEUSDT"
]
SYMBOLS = list(dict.fromkeys(SYMBOLS))

INTERVAL = "30min"
TREND_TFS = [
    ("30min", "۳۰ دقیقه"),
    ("2hour", "۲ ساعته"),
    ("4hour", "۴ ساعته")
]

RSI_PERIOD = 14
EMA_FAST = 9
EMA_SLOW = 21
EMA_TREND = 100

ADX_THRESHOLD = 18
VOLUME_MULT = 1.0
RSI_LONG_MIN = 30
RSI_LONG_MAX = 70
RSI_SHORT_MIN = 30
RSI_SHORT_MAX = 70
RSI_REVERSAL_LONG = 35
RSI_REVERSAL_SHORT = 65


def load_history(file_path):
    try:
        with open(file_path, "r") as f:
            return json.load(f)
    except:
        return {}


def save_history(history, file_path):
    try:
        with open(file_path, "w") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print("خطا در ذخیره: " + str(e))


def is_duplicate(history, symbol, direction, signal_type, cooldown):
    if cooldown == 0:
        return False
    key = symbol + "_" + direction + "_" + signal_type
    if key in history:
        try:
            last_time = datetime.strptime(history[key], "%Y-%m-%d %H:%M:%S")
            now_iran = datetime.now(IRAN_TZ).replace(tzinfo=None)
            diff_minutes = (now_iran - last_time).total_seconds() / 60
            if diff_minutes < cooldown:
                return True
        except:
            return False
    return False


def update_history(history, symbol, direction, signal_type):
    key = symbol + "_" + direction + "_" + signal_type
    history[key] = datetime.now(IRAN_TZ).strftime("%Y-%m-%d %H:%M:%S")
    return history


def get_klines(symbol, interval):
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


def get_trend(df):
    if df is None or len(df) < EMA_TREND:
        return "داده کافی نیست", 0
    df["ema_trend"] = df["close"].ewm(span=EMA_TREND, adjust=False).mean()
    last_close = df["close"].iloc[-2]
    last_ema = df["ema_trend"].iloc[-2]
    diff_pct = ((last_close - last_ema) / last_ema) * 100
    if last_close > last_ema:
        return "صعودی 📈", diff_pct
    else:
        return "نزولی 📉", diff_pct


def get_trends_for_symbol(symbol):
    trends = {}
    for tf_code, tf_name in TREND_TFS:
        df = get_klines(symbol, tf_code)
        time.sleep(0.1)
        trend, diff = get_trend(df)
        trends[tf_name] = (trend, diff)
    return trends


def get_decimals(price):
    if price >= 100:
        return 2
    elif price >= 1:
        return 4
    elif price >= 0.01:
        return 5
    else:
        return 8


def build_signal_message(sig, now, signal_type, trends):
    reasons_text = "\n".join(sig["reasons"])

    trends_text = ""
    for tf_name, (trend, diff) in trends.items():
        trends_text += "⏱ " + tf_name + ": <b>" + trend + "</b> (" + str(round(diff, 2)) + "%)\n"

    msg = (
        "🟦 <b>سیگنال " + signal_type + " - " + sig["type"] + "</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 <b>ارز:</b> " + sig["symbol"] + "\n"
        "💰 <b>قیمت ورود:</b> " + str(sig["price"]) + "\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "<b>📊 دلایل سیگنال:</b>\n" + reasons_text + "\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "<b>📈 روند تایم‌فریم‌ها:</b>\n" + trends_text +
        "━━━━━━━━━━━━━━━━━━\n"
        "📊 <b>RSI:</b> " + str(sig["rsi"]) + "\n"
        "📈 <b>ADX:</b> " + str(sig["adx"]) + "\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🛑 <b>حد ضرر:</b> " + str(sig["sl"]) + "\n"
        "🎯 <b>هدف اول:</b> " + str(sig["tp1"]) + "\n"
        "🎯 <b>هدف دوم:</b> " + str(sig["tp2"]) + "\n"
        "🎯 <b>هدف سوم:</b> " + str(sig["tp3"]) + "\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⏰ <b>زمان:</b> " + now + "\n"
        "⏱ <b>تایم‌فریم سیگنال:</b> " + INTERVAL
    )
    return msg


def make_signal(symbol, price, last, reasons, direction):
    dec = get_decimals(price)
    atr = last["atr"]
    if direction == "لانگ 🟢":
        sl = round(price - (atr * 1.5), dec)
        tp1 = round(price + (atr * 1.5), dec)
        tp2 = round(price + (atr * 3), dec)
        tp3 = round(price + (atr * 5), dec)
    else:
        sl = round(price + (atr * 1.5), dec)
        tp1 = round(price - (atr * 1.5), dec)
        tp2 = round(price - (atr * 3), dec)
        tp3 = round(price - (atr * 5), dec)
    return {
        "type": direction, "symbol": symbol, "price": round(price, dec),
        "rsi": round(last["rsi"], 2), "adx": round(last["adx"], 2),
        "reasons": reasons,
        "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3,
    }


def check_signal(df, df_htf, symbol):
    if df is None or df_htf is None:
        return None, None
    if len(df) < 5 or len(df_htf) < 50:
        return None, None

    last = df.iloc[-2]
    prev = df.iloc[-3]
    price = last["close"]
    rsi = last["rsi"]

    htf_up = df_htf["close"].iloc[-1] > df_htf["ema_trend"].iloc[-1]
    htf_down = df_htf["close"].iloc[-1] < df_htf["ema_trend"].iloc[-1]
    volume_required = last["volume"] > (last["vol_ma"] * VOLUME_MULT)
    adx_required = last["adx"] > ADX_THRESHOLD

    # ====== ۱. برگشت لانگ ======
    if rsi < RSI_REVERSAL_LONG and rsi > prev["rsi"] and last["close"] > prev["close"]:
        macd_required = last["macd"] > last["macd_signal"]
        if not (volume_required and macd_required and adx_required and htf_up):
            return None, None
        reasons = []
        reasons.append("🔄 برگشت از اشباع فروش (RSI: " + str(round(rsi, 2)) + ")")
        reasons.append("✅ حجم بالا")
        reasons.append("✅ MACD صعودی")
        reasons.append("✅ ADX = " + str(round(last["adx"], 2)))
        reasons.append("✅ روند ۴ساعته صعودی")
        sig = make_signal(symbol, price, last, reasons, "لانگ 🟢")
        return sig, "برگشت"

    # ====== ۲. برگشت شورت ======
    if rsi > RSI_REVERSAL_SHORT and rsi < prev["rsi"] and last["close"] < prev["close"]:
        macd_required = last["macd"] < last["macd_signal"]
        if not (volume_required and macd_required and adx_required and htf_down):
            return None, None
        reasons = []
        reasons.append("🔄 برگشت از اشباع خرید (RSI: " + str(round(rsi, 2)) + ")")
        reasons.append("✅ حجم بالا")
        reasons.append("✅ MACD نزولی")
        reasons.append("✅ ADX = " + str(round(last["adx"], 2)))
        reasons.append("✅ روند ۴ساعته نزولی")
        sig = make_signal(symbol, price, last, reasons, "شورت 🔴")
        return sig, "برگشت"

    # ====== ۳. کراس ======
    cross_up = (prev["ema_fast"] <= prev["ema_slow"]) and (last["ema_fast"] > last["ema_slow"])
    cross_down = (prev["ema_fast"] >= prev["ema_slow"]) and (last["ema_fast"] < last["ema_slow"])

    if cross_up:
        macd_required = last["macd"] > last["macd_signal"]
        rsi_ok = (rsi > RSI_LONG_MIN) and (rsi < RSI_LONG_MAX)
        if not (volume_required and macd_required and adx_required and htf_up and rsi_ok):
            return None, None
        reasons = []
        reasons.append("✅ کراس صعودی EMA9/21")
        reasons.append("✅ حجم بالا")
        reasons.append("✅ MACD صعودی")
        reasons.append("✅ ADX = " + str(round(last["adx"], 2)))
        reasons.append("✅ روند ۴ساعته صعودی")
        reasons.append("✅ RSI = " + str(round(rsi, 2)))
        sig = make_signal(symbol, price, last, reasons, "لانگ 🟢")
        return sig, "کراس"

    if cross_down:
        macd_required = last["macd"] < last["macd_signal"]
        rsi_ok = (rsi > RSI_SHORT_MIN) and (rsi < RSI_SHORT_MAX)
        if not (volume_required and macd_required and adx_required and htf_down and rsi_ok):
            return None, None
        reasons = []
        reasons.append("✅ کراس نزولی EMA9/21")
        reasons.append("✅ حجم بالا")
        reasons.append("✅ MACD نزولی")
        reasons.append("✅ ADX = " + str(round(last["adx"], 2)))
        reasons.append("✅ روند ۴ساعته نزولی")
        reasons.append("✅ RSI = " + str(round(rsi, 2)))
        sig = make_signal(symbol, price, last, reasons, "شورت 🔴")
        return sig, "کراس"

    return None, None


def find_support_resistance(df, lookback=50):
    if df is None or len(df) < lookback:
        return None, None
    recent = df.iloc[-lookback:]
    current_price = recent["close"].iloc[-1]
    lows = recent["low"].values
    highs = recent["high"].values
    support_candidates = [x for x in lows if x < current_price * 0.998]
    resistance_candidates = [x for x in highs if x > current_price * 1.002]
    support = max(support_candidates) if support_candidates else current_price * 0.97
    resistance = min(resistance_candidates) if resistance_candidates else current_price * 1.03
    return support, resistance


def build_scenario_message(symbol, price, support, resistance, atr, rsi, adx, trends):
    # ==== منطق RSI: فقط سناریوی منطقی نشون بده ====
    show_long = rsi < 70
    show_short = rsi > 30

    if not show_long and not show_short:
        return None

    dec = get_decimals(price)

    trends_text = ""
    for tf_name, (trend, diff) in trends.items():
        trends_text += "⏱ " + tf_name + ": <b>" + trend + "</b> (" + str(round(diff, 2)) + "%)\n"

    msg = (
        "🟨 <b>سناریوی معاملاتی - " + symbol + "</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "💰 <b>قیمت فعلی:</b> " + str(round(price, dec)) + "\n"
        "📊 <b>RSI:</b> " + str(round(rsi, 2)) + " | <b>ADX:</b> " + str(round(adx, 2)) + "\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "<b>📈 روند تایم‌فریم‌ها:</b>\n" + trends_text +
        "━━━━━━━━━━━━━━━━━━\n"
    )

    if show_long:
        long_entry = round(support, dec)
        long_sl = round(support - (atr * 1.5), dec)
        long_tp1 = round(support + (atr * 1.5), dec)
        long_tp2 = round(support + (atr * 3), dec)
        msg += (
            "🟢 <b>سناریو لانگ:</b>\n"
            "اگه قیمت به <b>" + str(long_entry) + "</b> رسید (حمایت)\n"
            "→ ورود لانگ\n"
            "→ 🛑 حد ضرر: <b>" + str(long_sl) + "</b>\n"
            "→ 🎯 هدف اول: <b>" + str(long_tp1) + "</b>\n"
            "→ 🎯 هدف دوم: <b>" + str(long_tp2) + "</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
        )

    if show_short:
        short_entry = round(resistance, dec)
        short_sl = round(resistance + (atr * 1.5), dec)
        short_tp1 = round(resistance - (atr * 1.5), dec)
        short_tp2 = round(resistance - (atr * 3), dec)
        msg += (
            "🔴 <b>سناریو شورت:</b>\n"
            "اگه قیمت به <b>" + str(short_entry) + "</b> رسید (مقاومت)\n"
            "→ ورود شورت\n"
            "→ 🛑 حد ضرر: <b>" + str(short_sl) + "</b>\n"
            "→ 🎯 هدف اول: <b>" + str(short_tp1) + "</b>\n"
            "→ 🎯 هدف دوم: <b>" + str(short_tp2) + "</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
        )

    msg += (
        "⚠️ <b>توجه:</b> این سناریو شرطیه، نه پیش‌بینی.\n"
        "⏰ " + datetime.now(IRAN_TZ).strftime("%Y-%m-%d %H:%M")
    )
    return msg


async def main():
    bot = Bot(token=BOT_TOKEN)
    signal_history = load_history(HISTORY_FILE)
    scenario_history = load_history(SCENARIO_HISTORY_FILE)
    now = datetime.now(IRAN_TZ).strftime("%Y-%m-%d %H:%M")

    signals_found = 0
    scenarios_found = 0
    duplicates_skipped = 0
    processed = 0

    for symbol in SYMBOLS:
        try:
            df = get_klines(symbol, INTERVAL)
            time.sleep(0.1)
            df_htf = get_klines(symbol, "4hour")
            time.sleep(0.1)

            if df is None or df_htf is None:
                continue

            df = calc_indicators(df)
            df_htf = calc_indicators(df_htf)
            processed += 1

            last = df.iloc[-2]
            price = last["close"]

            sig, signal_type = check_signal(df, df_htf, symbol)

            if sig:
                if not is_duplicate(signal_history, symbol, sig["type"], signal_type, COOLDOWN_MINUTES):
                    trends = get_trends_for_symbol(symbol)
                    signal_history = update_history(signal_history, symbol, sig["type"], signal_type)
                    signals_found += 1
                    msg = build_signal_message(sig, now, signal_type, trends)
                    await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
                    print("سیگنال: " + symbol + " | " + signal_type)
                else:
                    duplicates_skipped += 1

            if symbol in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]:
                support, resistance = find_support_resistance(df)
                if support and resistance and last["atr"] > 0:
                    dist_support = abs((price - support) / price) * 100
                    dist_resistance = abs((resistance - price) / price) * 100

                    if dist_support > 0.5 and dist_resistance > 0.5:
                        if not is_duplicate(scenario_history, symbol, "scenario", "both", SCENARIO_COOLDOWN_MINUTES):
                            trends = get_trends_for_symbol(symbol)
                            msg = build_scenario_message(
                                symbol, price, support, resistance,
                                last["atr"], last["rsi"], last["adx"], trends
                            )
                            if msg:
                                scenario_history = update_history(scenario_history, symbol, "scenario", "both")
                                scenarios_found += 1
                                await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
                                print("سناریو: " + symbol)

        except Exception as e:
            print("خطا در " + symbol + ": " + str(e))
            continue

    save_history(signal_history, HISTORY_FILE)
    save_history(scenario_history, SCENARIO_HISTORY_FILE)

    print(now + " | پردازش: " + str(processed) + " | سیگنال: " + str(signals_found) + " | سناریو: " + str(scenarios_found) + " | تکراری: " + str(duplicates_skipped))

    if signals_found == 0 and scenarios_found == 0:
        no_signal_msg = (
            "📭 <b>گزارش - " + now + "</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "✅ پردازش: " + str(processed) + " ارز\n"
            "❌ هیچ سیگنالی شرایط را پاس نکرده است.\n"
            "⏱ تایم‌فریم: " + INTERVAL + "\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "⏰ این گزارش خودکار است."
        )
        await bot.send_message(chat_id=CHAT_ID, text=no_signal_msg, parse_mode="HTML")
        print("پیام 'هیچ سیگنالی نیست' ارسال شد.")


if __name__ == "__main__":
    asyncio.run(main())
