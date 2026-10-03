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
ACTIVE_SIGNALS_FILE = "active_signals.json"
DAILY_SIGNALS_FILE = "daily_signals.json"
DAILY_SUMMARY_COOLDOWN_MINUTES = 1440
COOLDOWN_MINUTES = 60
SCENARIO_COOLDOWN_MINUTES = 60
NO_SIGNAL_COOLDOWN_MINUTES = 180
VALIDITY_CHECK_MINUTES = 30
MAX_VALIDITY_CHECKS = 3

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

INTERVAL = "45min"
TREND_TFS = [
    ("30min", "۳۰ دقیقه"),
    ("2hour", "۲ ساعته"),
    ("4hour", "۴ ساعته")
]

RSI_PERIOD = 14
EMA_FAST = 9
EMA_SLOW = 21
EMA_TREND = 100

ADX_THRESHOLD = 25
VOLUME_MULT = 1.5
RSI_LONG_MIN = 40
RSI_LONG_MAX = 60
RSI_SHORT_MIN = 40
RSI_SHORT_MAX = 60
RSI_REVERSAL_LONG = 30
RSI_REVERSAL_SHORT = 70


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


def get_price(symbol):
    try:
        symbol_kucoin = symbol.replace("USDT", "-USDT")
        url = "https://api.kucoin.com/api/v1/market/orderbook/level1?symbol=" + symbol_kucoin
        r = requests.get(url, timeout=10)
        data = r.json()
        if data.get("code") == "200000":
            return float(data["data"]["price"])
    except Exception:
        pass
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
    # --- محاسبات ایچیموکو ---
    high_9 = df["high"].rolling(window=9).max()
    low_9 = df["low"].rolling(window=9).min()
    df["tenkan_sen"] = (high_9 + low_9) / 2

    high_26 = df["high"].rolling(window=26).max()
    low_26 = df["low"].rolling(window=26).min()
    df["kijun_sen"] = (high_26 + low_26) / 2

    df["senkou_span_a"] = ((df["tenkan_sen"] + df["kijun_sen"]) / 2).shift(26)

    high_52 = df["high"].rolling(window=52).max()
    low_52 = df["low"].rolling(window=52).min()
    df["senkou_span_b"] = ((high_52 + low_52) / 2).shift(26)
    # --- پایان محاسبات ایچیموکو ---
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
    return 8


def calc_rr(entry, sl, tp):
    risk = abs(entry - sl)
    if risk <= 0:
        return 0
    return round(abs(tp - entry) / risk, 2)


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


def get_today_key():
    return datetime.now(IRAN_TZ).strftime("%Y-%m-%d")


def get_yesterday_key():
    return (datetime.now(IRAN_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")


def load_daily():
    try:
        with open(DAILY_SIGNALS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}


def save_daily(data):
    try:
        with open(DAILY_SIGNALS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print("خطا در ذخیره daily: " + str(e))


def add_to_daily(symbol, sig, signal_type):
    today = get_today_key()
    data = load_daily()
    if today not in data:
        data[today] = {"signals": [], "summary_sent": False}
    data[today]["signals"].append({
        "symbol": symbol,
        "type": sig["type"],
        "signal_type": signal_type,
        "entry": sig["price"],
        "sl": sig["sl"],
        "tp1": sig["tp1"],
        "tp2": sig["tp2"],
        "tp3": sig["tp3"],
        "outcome": "pending",
        "profit_pct": 0.0,
    })
    save_daily(data)


def update_daily_outcome(symbol, outcome, profit_pct):
    today = get_today_key()
    data = load_daily()
    if today not in data:
        return
    for s in data[today]["signals"]:
        if s["symbol"] == symbol and s["outcome"] == "pending":
            s["outcome"] = outcome
            s["profit_pct"] = profit_pct
            break
    save_daily(data)


def calc_profit_pct(entry, exit_price, direction):
    if entry <= 0:
        return 0.0
    if "لانگ" in direction:
        return ((exit_price - entry) / entry) * 100
    else:
        return ((entry - exit_price) / entry) * 100


async def send_daily_summary(bot, now):
    try:
        current_hour = datetime.now(IRAN_TZ).hour
    except:
        return
# اجازه ارسال خلاصه از ساعت ۰۰:۰۰ تا ۰۲:۵۹ بامداد
    if current_hour > 2:
        return

    yesterday = get_yesterday_key()
    data = load_daily()
    if yesterday not in data:
        return
    if data[yesterday].get("summary_sent", False):
        return

    signals = data[yesterday]["signals"]
    data[yesterday]["summary_sent"] = True
    save_daily(data)

    if not signals:
        try:
            await bot.send_message(chat_id=CHAT_ID, text="📊 خلاصه " + yesterday + "\nهیچ سیگنالی صادر نشد.", parse_mode="HTML")
        except: pass
        return

    tp1_list = []
    tp2_list = []
    tp3_list = []
    sl_list = []
    pending_list = []
    total_pct = 0.0

    for s in signals:
        o = s.get("outcome", "pending")
        if o == "tp3":
            tp3_list.append(s["symbol"])
        elif o == "tp2":
            tp2_list.append(s["symbol"])
        elif o == "tp1":
            tp1_list.append(s["symbol"])
        elif o == "sl":
            sl_list.append(s["symbol"])
        else:
            pending_list.append(s["symbol"])
        total_pct += s.get("profit_pct", 0.0)

    msg = "📊 <b>خلاصه روزانه - " + yesterday + "</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━\n"
    msg += "📌 مجموع سیگنال: <b>" + str(len(signals)) + "</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━\n"
    if tp3_list:
        msg += "🥇 هدف سوم: " + "، ".join(tp3_list) + "\n"
    if tp2_list:
        msg += "🥈 هدف دوم: " + "، ".join(tp2_list) + "\n"
    if tp1_list:
        msg += "🥉 هدف اول: " + "، ".join(tp1_list) + "\n"
    if sl_list:
        msg += "❌ حد ضرر: " + "، ".join(sl_list) + "\n"
    if pending_list:
        msg += "⏳ در انتظار: " + "، ".join(pending_list) + "\n"
    msg += "━━━━━━━━━━━━━━━━━━\n"
    if total_pct >= 0:
        msg += "💰 <b>برآیند سود روز:</b> +" + str(round(total_pct, 2)) + "%\n"
    else:
        msg += "💰 <b>برآیند سود روز:</b> " + str(round(total_pct, 2)) + "%\n"
    msg += "⏰ " + now

    try:
        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
        print("خلاصه روزانه ارسال شد.")
    except Exception as e:
        print("خطا در ارسال خلاصه: " + str(e))


def make_signal(symbol, price, last, reasons, direction):
    dec = get_decimals(price)
    atr = last["atr"]
    if direction == "لانگ 🟢":
        sl = round(price - (atr * 1.5), dec)   # اصلاح: 1.5 به جای 2.0 (کم‌ریسک‌تر)
        tp1 = round(price + (atr * 3.0), dec)  # اصلاح: 3.0 به جای 2.5 (نسبت 1:2)
        tp2 = round(price + (atr * 5.0), dec)
        tp3 = round(price + (atr * 8.0), dec)
    else:
        sl = round(price + (atr * 1.5), dec)   # اصلاح
        tp1 = round(price - (atr * 3.0), dec)  # اصلاح
        tp2 = round(price - (atr * 5.0), dec)
        tp3 = round(price - (atr * 8.0), dec)
    return {
        "type": direction, "symbol": symbol, "price": round(price, dec),
        "rsi": round(last["rsi"], 2), "adx": round(last["adx"], 2),
        "reasons": reasons, "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "rr1": calc_rr(price, sl, tp1), "rr2": calc_rr(price, sl, tp2), "rr3": calc_rr(price, sl, tp3),
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
if rsi < RSI_REVERSAL_LONG and rsi > prev["rsi"] and last["close"] > prev["close"]:
        macd_required = last["macd"] > last["macd_signal"]
        if not (volume_required and macd_required and adx_required and htf_up):
            return None, None
        reasons = ["🔄 برگشت از اشباع فروش (RSI: " + str(round(rsi, 2)) + ")",
                   "✅ حجم بالا", "✅ MACD صعودی",
                   "✅ ADX = " + str(round(last["adx"], 2)), "✅ روند ۴ساعته صعودی"]
        return make_signal(symbol, price, last, reasons, "لانگ 🟢"), "برگشت"

    if rsi > RSI_REVERSAL_SHORT and rsi < prev["rsi"] and last["close"] < prev["close"]:
        macd_required = last["macd"] < last["macd_signal"]
        if not (volume_required and macd_required and adx_required and htf_down):
            return None, None
        reasons = ["🔄 برگشت از اشباع خرید (RSI: " + str(round(rsi, 2)) + ")",
                   "✅ حجم بالا", "✅ MACD نزولی",
                   "✅ ADX = " + str(round(last["adx"], 2)), "✅ روند ۴ساعته نزولی"]
        return make_signal(symbol, price, last, reasons, "شورت 🔴"), "برگشت"

    cross_up = (prev["ema_fast"] <= prev["ema_slow"]) and (last["ema_fast"] > last["ema_slow"])
    cross_down = (prev["ema_fast"] >= prev["ema_slow"]) and (last["ema_fast"] < last["ema_slow"])

    if cross_up:
        macd_required = last["macd"] > last["macd_signal"]
        rsi_ok = (rsi > RSI_LONG_MIN) and (rsi < RSI_LONG_MAX)
        if not (volume_required and macd_required and adx_required and htf_up and rsi_ok):
            return None, None
        reasons = ["✅ کراس صعودی EMA9/21", "✅ حجم بالا", "✅ MACD صعودی",
                   "✅ ADX = " + str(round(last["adx"], 2)), "✅ روند ۴ساعته صعودی",
                   "✅ RSI = " + str(round(rsi, 2))]
        return make_signal(symbol, price, last, reasons, "لانگ 🟢"), "کراس"

    if cross_down:
        macd_required = last["macd"] < last["macd_signal"]
        rsi_ok = (rsi > RSI_SHORT_MIN) and (rsi < RSI_SHORT_MAX)
        htf_strong_down = df_htf["close"].iloc[-1] < df_htf["ema_trend"].iloc[-1]
        if not (volume_required and macd_required and adx_required and htf_strong_down and rsi_ok):
            return None, None
        reasons = ["✅ کراس نزولی EMA9/21", "✅ حجم بالا", "✅ MACD نزولی",
                   "✅ ADX = " + str(round(last["adx"], 2)), "✅ روند ۴ساعته نزولی",
                   "✅ RSI = " + str(round(rsi, 2))]
        return make_signal(symbol, price, last, reasons, "شورت 🔴"), "کراس"

    return None, None


def build_signal_message(sig, now, signal_type, trends):
    reasons_text = "\n".join(sig["reasons"])
    trends_text = ""
    for tf_name, (trend, diff) in trends.items():
        trends_text += "⏱ " + tf_name + ": <b>" + trend + "</b> (" + str(round(diff, 2)) + "%)\n"
    return (
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
        "🎯 <b>هدف اول:</b> " + str(sig["tp1"]) + " | <b>R/R:</b> 1:" + str(sig["rr1"]) + "\n"
        "🎯 <b>هدف دوم:</b> " + str(sig["tp2"]) + " | <b>R/R:</b> 1:" + str(sig["rr2"]) + "\n"
        "🎯 <b>هدف سوم:</b> " + str(sig["tp3"]) + " | <b>R/R:</b> 1:" + str(sig["rr3"]) + "\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⏰ <b>زمان:</b> " + now + "\n"
        "⏱ <b>تایم‌فریم سیگنال:</b> " + INTERVAL
    )


def build_scenario_message(symbol, price, support, resistance, atr, rsi, adx, trends):
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
        rr1 = calc_rr(long_entry, long_sl, long_tp1)
        rr2 = calc_rr(long_entry, long_sl, long_tp2)
        msg += (
            "🟢 <b>سناریو لانگ:</b>\n"
            "اگه قیمت به <b>" + str(long_entry) + "</b> رسید (حمایت)\n"
            "→ ورود لانگ\n"
            "→ 🛑 حد ضرر: <b>" + str(long_sl) + "</b>\n"
            "→ 🎯 هدف اول: <b>" + str(long_tp1) + "</b> | R/R: 1:" + str(rr1) + "\n"
            "→ 🎯 هدف دوم: <b>" + str(long_tp2) + "</b> | R/R: 1:" + str(rr2) + "\n"
            "━━━━━━━━━━━━━━━━━━\n"
        )
    if show_short:
        short_entry = round(resistance, dec)
        short_sl = round(resistance + (atr * 1.5), dec)
        short_tp1 = round(resistance - (atr * 1.5), dec)
        short_tp2 = round(resistance - (atr * 3), dec)
        rr1 = calc_rr(short_entry, short_sl, short_tp1)
        rr2 = calc_rr(short_entry, short_sl, short_tp2)
        msg += (
            "🔴 <b>سناریو شورت:</b>\n"
            "اگه قیمت به <b>" + str(short_entry) + "</b> رسید (مقاومت)\n"
            "→ ورود شورت\n"
            "→ 🛑 حد ضرر: <b>" + str(short_sl) + "</b>\n"
            "→ 🎯 هدف اول: <b>" + str(short_tp1) + "</b> | R/R: 1:" + str(rr1) + "\n"
            "→ 🎯 هدف دوم: <b>" + str(short_tp2) + "</b> | R/R: 1:" + str(rr2) + "\n"
            "━━━━━━━━━━━━━━━━━━\n"
        )
    msg += ("⚠️ <b>توجه:</b> این سناریو شرطیه، نه پیش‌بینی.\n"
            "⏰ " + datetime.now(IRAN_TZ).strftime("%Y-%m-%d %H:%M"))
    return msg


def add_active_signal(symbol, sig, signal_type, trends, message_id):
    data = load_history(ACTIVE_SIGNALS_FILE)
    data[symbol] = {
        "type": sig["type"], "price": sig["price"], "sl": sig["sl"],
        "tp1": sig["tp1"], "tp2": sig["tp2"], "tp3": sig["tp3"],
        "signal_type": signal_type, "message_id": message_id,
        "created": datetime.now(IRAN_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "tp1_hit": False, "tp2_hit": False, "tp3_hit": False,
        "validity_count": 0, "last_validity_check": None,
    }
    save_history(data, ACTIVE_SIGNALS_FILE)
    add_to_daily(symbol, sig, signal_type)


async def check_active_signals(bot, now):
    data = load_history(ACTIVE_SIGNALS_FILE)
    if not data:
        return
    updated = False
    now_dt = datetime.now(IRAN_TZ).replace(tzinfo=None)
    for symbol in list(data.keys()):
        info = data[symbol]
        price = get_price(symbol)
        if price is None:
            continue
        direction = info["type"]
        sl = info["sl"]
        tp1 = info["tp1"]
        tp2 = info["tp2"]
        tp3 = info["tp3"]
        msg_id = info.get("message_id")
        dec = get_decimals(info["price"])
        entry = info["price"]

        sl_hit = False
        if "لانگ" in direction and price <= sl:
            sl_hit = True
        elif "شورت" in direction and price >= sl:
            sl_hit = True

        if sl_hit:
            msg = ("❌ <b>سیگنال باطل شد</b>\n━━━━━━━━━━━━━━━━━━\n"
                   "🔴 <b>حد ضرر لمس شد:</b> " + str(sl) + "\n"
                   "💰 <b>قیمت فعلی:</b> " + str(round(price, dec)) + "\n⏰ " + now)
            try:
                if msg_id:
                    await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML", reply_to_message_id=msg_id)
                else:
                    await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
            except: pass
            profit = calc_profit_pct(entry, sl, direction)
            update_daily_outcome(symbol, "sl", profit)
            del data[symbol]
            updated = True
            continue

        tp_hit = False
        if "لانگ" in direction:
            if price >= tp3 and not info.get("tp3_hit"):
                info["tp3_hit"] = True
                updated = True
                tp_hit = True
                msg = "🎯🎯🎯 <b>هدف سوم لمس شد!</b>\n💰 " + str(round(price, dec)) + "\n🎯 TP3: " + str(tp3)
                try:
                    if msg_id:
                        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML", reply_to_message_id=msg_id)
                    else:
                        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
                except: pass
                profit = calc_profit_pct(entry, tp3, direction)
                update_daily_outcome(symbol, "tp3", profit)
del data[symbol]
                updated = True
                continue
            elif price >= tp2 and not info.get("tp2_hit"):
                info["tp2_hit"] = True
                updated = True
                tp_hit = True
                msg = "🎯🎯 <b>هدف دوم لمس شد!</b>\n💰 " + str(round(price, dec)) + "\n🎯 TP2: " + str(tp2)
                try:
                    if msg_id:
                        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML", reply_to_message_id=msg_id)
                    else:
                        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
                except: pass
                profit = calc_profit_pct(entry, tp2, direction)
                update_daily_outcome(symbol, "tp2", profit)
            elif price >= tp1 and not info.get("tp1_hit"):
                info["tp1_hit"] = True
                updated = True
                tp_hit = True
                msg = "🎯 <b>هدف اول لمس شد!</b>\n💰 " + str(round(price, dec)) + "\n🎯 TP1: " + str(tp1)
                try:
                    if msg_id:
                        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML", reply_to_message_id=msg_id)
                    else:
                        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
                except: pass
                profit = calc_profit_pct(entry, tp1, direction)
                update_daily_outcome(symbol, "tp1", profit)
        
        elif "شورت" in direction:
            if price <= tp3 and not info.get("tp3_hit"):
                info["tp3_hit"] = True
                updated = True
                tp_hit = True
                msg = "🎯🎯🎯 <b>هدف سوم لمس شد!</b>\n💰 " + str(round(price, dec)) + "\n🎯 TP3: " + str(tp3)
                try:
                    if msg_id:
                        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML", reply_to_message_id=msg_id)
                    else:
                        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
                except: pass
                profit = calc_profit_pct(entry, tp3, direction)
                update_daily_outcome(symbol, "tp3", profit)
                del data[symbol]
                updated = True
                continue
            elif price <= tp2 and not info.get("tp2_hit"):
                info["tp2_hit"] = True
                updated = True
                tp_hit = True
                msg = "🎯🎯 <b>هدف دوم لمس شد!</b>\n💰 " + str(round(price, dec)) + "\n🎯 TP2: " + str(tp2)
                try:
                    if msg_id:
                        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML", reply_to_message_id=msg_id)
                    else:
                        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
                except: pass
                profit = calc_profit_pct(entry, tp2, direction)
                update_daily_outcome(symbol, "tp2", profit)
            elif price <= tp1 and not info.get("tp1_hit"):
                info["tp1_hit"] = True
                updated = True
                tp_hit = True
                msg = "🎯 <b>هدف اول لمس شد!</b>\n💰 " + str(round(price, dec)) + "\n🎯 TP1: " + str(tp1)
                try:
                    if msg_id:
                        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML", reply_to_message_id=msg_id)
                    else:
                        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
                except: pass
                profit = calc_profit_pct(entry, tp1, direction)
                update_daily_outcome(symbol, "tp1", profit)

        if not tp_hit:
            try:
                created = datetime.strptime(info["created"], "%Y-%m-%d %H:%M:%S")
                minutes_passed = (now_dt - created).total_seconds() / 60
            except:
                minutes_passed = 0
            last_validity = info.get("last_validity_check")
            validity_count = info.get("validity_count", 0)
            should_send = False
            if validity_count < MAX_VALIDITY_CHECKS:
async def check_active_signals(bot, now):
    data = load_history(ACTIVE_SIGNALS_FILE)
    if not data:
        return
    updated = False
    now_dt = datetime.now(IRAN_TZ).replace(tzinfo=None)
    
    for symbol in list(data.keys()):
        info = data[symbol]
        price = get_price(symbol)
        if price is None:
            continue
        direction = info["type"]
        sl = info["sl"]
        tp1 = info["tp1"]
        tp2 = info["tp2"]
        tp3 = info["tp3"]
        msg_id = info.get("message_id")
        dec = get_decimals(info["price"])
        entry = info["price"]

        # ====== ۱. بررسی بریک‌ایون (Breakeven) ======
        if "لانگ" in direction and price >= tp1:
            if not info.get("moved_to_be", False):
                info["sl"] = entry
                info["moved_to_be"] = True
                updated = True
                sl = entry  # آپدیت مقدار sl برای چک کردن مرحله بعد
                be_msg = "🛡 <b>حد ضرر به بریک‌ایون منتقل شد.</b>\n💰 قیمت فعلی: " + str(round(price, dec)) + "\n🛑 حد ضرر جدید: " + str(entry)
                try:
                    if msg_id:
                        await bot.send_message(chat_id=CHAT_ID, text=be_msg, parse_mode="HTML", reply_to_message_id=msg_id)
                    else:
                        await bot.send_message(chat_id=CHAT_ID, text=be_msg, parse_mode="HTML")
                except: pass
        elif "شورت" in direction and price <= tp1:
            if not info.get("moved_to_be", False):
                info["sl"] = entry
                info["moved_to_be"] = True
                updated = True
                sl = entry
                be_msg = "🛡 <b>حد ضرر به بریک‌ایون منتقل شد.</b>\n💰 قیمت فعلی: " + str(round(price, dec)) + "\n🛑 حد ضرر جدید: " + str(entry)
                try:
                    if msg_id:
                        await bot.send_message(chat_id=CHAT_ID, text=be_msg, parse_mode="HTML", reply_to_message_id=msg_id)
                    else:
                        await bot.send_message(chat_id=CHAT_ID, text=be_msg, parse_mode="HTML")
                except: pass

        # ====== ۲. بررسی حد ضرر زمانی (۲۴ ساعت) ======
        if "created" in info:
            try:
                created_time = datetime.strptime(info["created"], "%Y-%m-%d %H:%M:%S")
                minutes_passed = (now_dt - created_time).total_seconds() / 60
                if minutes_passed > 1440:  # 24 ساعت = 1440 دقیقه
                    profit = calc_profit_pct(entry, price, direction)
                    update_daily_outcome(symbol, "time", profit)
                    time_msg = "⏳ <b>زمان معامله به پایان رسید (۲۴ ساعت).</b>\n💰 قیمت فعلی: " + str(round(price, dec))
                    try:
                        if msg_id:
                            await bot.send_message(chat_id=CHAT_ID, text=time_msg, parse_mode="HTML", reply_to_message_id=msg_id)
                        else:
                            await bot.send_message(chat_id=CHAT_ID, text=time_msg, parse_mode="HTML")
                    except: pass
                    del data[symbol]
                    updated = True
                    continue
            except: pass

        # ====== ادامه کدهای قبلی خودت برای چک کردن SL و TPها ======
        sl_hit = False
        if "لانگ" in direction and price <= sl:
            sl_hit = True
        elif "شورت" in direction and price >= sl:
            sl_hit = True

        if sl_hit:
            msg = ("❌ <b>سیگنال باطل شد</b>\n━━━━━━━━━━━━━━━━━━\n"
                   "🔴 <b>حد ضرر لمس شد:</b> " + str(sl) + "\n"
                   "💰 <b>قیمت فعلی:</b> " + str(round(price, dec)) + "\n⏰ " + now)
            try:
                if msg_id:
                    await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML", reply_to_message_id=msg_id)
                else:
                    await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
            except: pass
            profit = calc_profit_pct(entry, sl, direction)
            update_daily_outcome(symbol, "sl", profit)
            del data[symbol]
            updated = True
            continue

        tp_hit = False
        if "لانگ" in direction:
            if price >= tp3 and not info.get("tp3_hit"):
                info["tp3_hit"] = True
                updated = True
                tp_hit = True
                msg = "🎯🎯🎯 <b>هدف سوم لمس شد!</b>\n💰 " + str(round(price, dec)) + "\n🎯 TP3: " + str(tp3)
                try:
                    if msg_id:
                        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML", reply_to_message_id=msg_id)
                    else:
                        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
                except: pass
                profit = calc_profit_pct(entry, tp3, direction)
                update_daily_outcome(symbol, "tp3", profit)
                del data[symbol] # حذف از اکتیو
                updated = True
                continue
            elif price >= tp2 and not info.get("tp2_hit"):
                info["tp2_hit"] = True
                updated = True
                tp_hit = True
                msg = "🎯🎯 <b>هدف دوم لمس شد!</b>\n💰 " + str(round(price, dec)) + "\n🎯 TP2: " + str(tp2)
                try:
                    if msg_id:
                        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML", reply_to_message_id=msg_id)
                    else:
                        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
                except: pass
                profit = calc_profit_pct(entry, tp2, direction)
                update_daily_outcome(symbol, "tp2", profit)
            elif price >= tp1 and not info.get("tp1_hit"):
                info["tp1_hit"] = True
                updated = True
                tp_hit = True
                msg = "🎯 <b>هدف اول لمس شد!</b>\n💰 " + str(round(price, dec)) + "\n🎯 TP1: " + str(tp1)
                try:
                    if msg_id:
                        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML", reply_to_message_id=msg_id)
                    else:
                        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
                except: pass
                profit = calc_profit_pct(entry, tp1, direction)
                update_daily_outcome(symbol, "tp1", profit)
        
        elif "شورت" in direction:
            if price <= tp3 and not info.get("tp3_hit"):
                info["tp3_hit"] = True
                updated = True
                tp_hit = True
                msg = "🎯🎯🎯 <b>هدف سوم لمس شد!</b>\n💰 " + str(round(price, dec)) + "\n🎯 TP3: " + str(tp3)
                try:
                    if msg_id:
                        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML", reply_to_message_id=msg_id)
                    else:
                        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
                except: pass
                profit = calc_profit_pct(entry, tp3, direction)
                update_daily_outcome(symbol, "tp3", profit)
                del data[symbol] # حذف از اکتیو
                updated = True
                continue
            elif price <= tp2 and not info.get("tp2_hit"):
                info["tp2_hit"] = True
                updated = True
                tp_hit = True
                msg = "🎯🎯 <b>هدف دوم لمس شد!</b>\n💰 " + str(round(price, dec)) + "\n🎯 TP2: " + str(tp2)
                try:
                    if msg_id:
                        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML", reply_to_message_id=msg_id)
                    else:
                        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
                except: pass
                profit = calc_profit_pct(entry, tp2, direction)
                update_daily_outcome(symbol, "tp2", profit)
            elif price <= tp1 and not info.get("tp1_hit"):
                info["tp1_hit"] = True
                updated = True
                tp_hit = True
                msg = "🎯 <b>هدف اول لمس شد!</b>\n💰 " + str(round(price, dec)) + "\n🎯 TP1: " + str(tp1)
                try:
                    if msg_id:
                        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML", reply_to_message_id=msg_id)
                    else:
                        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
                except: pass
                profit = calc_profit_pct(entry, tp1, direction)
                update_daily_outcome(symbol, "tp1", profit)

        if not tp_hit:
            try:
                created = datetime.strptime(info["created"], "%Y-%m-%d %H:%M:%S")
                minutes_passed = (now_dt - created).total_seconds() / 60
            except:
                minutes_passed = 0
            last_validity = info.get("last_validity_check")
            validity_count = info.get("validity_count", 0)
            should_send = False
            if validity_count < MAX_VALIDITY_CHECKS:
                if last_validity is None and minutes_passed >= VALIDITY_CHECK_MINUTES:
                    should_send = True
                elif last_validity is not None:
                    try:
                        last_dt = datetime.strptime(last_validity, "%Y-%m-%d %H:%M:%S")
                        if (now_dt - last_dt).total_seconds() / 60 >= VALIDITY_CHECK_MINUTES:
                            should_send = True
                    except: pass
            if should_send:
                diff_pct = ((price - entry) / entry) * 100
                if "لانگ" in direction:
                    status_emoji = "🟢" if diff_pct >= 0 else "🔴"
                else:
                    status_emoji = "🟢" if diff_pct <= 0 else "🔴"
                msg = (
                    "🔄 <b>سیگنال هنوز معتبر است</b>\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    "💰 <b>قیمت ورود:</b> " + str(entry) + "\n"
                    "💵 <b>قیمت فعلی:</b> " + str(round(price, dec)) + "\n"
                    + status_emoji + " <b>تغییر:</b> " + str(round(diff_pct, 2)) + "%\n"
                    "🛑 <b>حد ضرر:</b> " + str(sl) + "\n"
                    "🎯 <b>هدف اول:</b> " + str(tp1) + "\n"
                    "✅ <b>وضعیت:</b> هنوز می‌توان وارد شد\n⏰ " + now
                )
                try:
                    if msg_id:
                        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML", reply_to_message_id=msg_id)
                    else:
                        await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
                except: pass
                info["last_validity_check"] = now_dt.strftime("%Y-%m-%d %H:%M:%S")
                info["validity_count"] = validity_count + 1
                updated = True

    if updated:
        save_history(data, ACTIVE_SIGNALS_FILE)


async def main():
    bot = Bot(token=BOT_TOKEN)
    signal_history = load_history(HISTORY_FILE)
    scenario_history = load_history(SCENARIO_HISTORY_FILE)
    now = datetime.now(IRAN_TZ).strftime("%Y-%m-%d %H:%M")

    signals_found = 0
    scenarios_found = 0
    duplicates_skipped = 0
    processed = 0

    await check_active_signals(bot, now)
    await send_daily_summary(bot, now)

    for symbol in SYMBOLS:
        try:
            df = get_klines(symbol, INTERVAL)
            time.sleep(0.15)
            df_htf = get_klines(symbol, "4hour")
            time.sleep(0.15)

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
                    try:
                        sent = await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
                        add_active_signal(symbol, sig, signal_type, trends, sent.message_id)
                        print("سیگنال: " + symbol + " | " + signal_type)
                    except Exception as e:
                        print("خطا در ارسال: " + str(e))
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
                                try:
                                    await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
                                    print("سناریو: " + symbol)
                                except Exception as e:
                                    print("خطا در ارسال سناریو: " + str(e))

        except Exception as e:
            print("خطا در " + symbol + ": " + str(e))
            continue

    save_history(signal_history, HISTORY_FILE)
    save_history(scenario_history, SCENARIO_HISTORY_FILE)

    print(now + " | پردازش: " + str(processed) + " | سیگنال: " + str(signals_found) + " | سناریو: " + str(scenarios_found) + " | تکراری: " + str(duplicates_skipped))

    if signals_found == 0 and scenarios_found == 0 and not is_duplicate(signal_history, "GLOBAL", "none", "no_signal", NO_SIGNAL_COOLDOWN_MINUTES):
        no_signal_msg = (
            "📭 <b>گزارش - " + now + "</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "✅ پردازش: " + str(processed) + " ارز\n"
            "❌ هیچ سیگنالی شرایط را پاس نکرده است.\n"
            "⏱ تایم‌فریم: " + INTERVAL + "\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "⏰ این گزارش خودکار است."
        )
        try:
            await bot.send_message(chat_id=CHAT_ID, text=no_signal_msg, parse_mode="HTML")
            print("پیام 'هیچ سیگنالی نیست' ارسال شد.")
            signal_history = update_history(signal_history, "GLOBAL", "none", "no_signal")
            save_history(signal_history, HISTORY_FILE)
        except Exception as e:
            print("خطا در ارسال گزارش: " + str(e))


if __name__ == "__main__":
    asyncio.run(main())
