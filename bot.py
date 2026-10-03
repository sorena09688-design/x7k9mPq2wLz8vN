import os
import time
import requests
import pandas as pd
import numpy as np
import asyncio
from datetime import datetime
from telegram import Bot

# ==========================================
# ⚙️ تنظیمات اصلی (از سکرت‌ها خونده میشه)
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

if not BOT_TOKEN or not CHAT_ID:
    print("❌ خطا: متغیرهای محیطی BOT_TOKEN یا CHAT_ID یافت نشدند!")
    print("لطفاً سکرت‌ها را در گیت‌هاب یا فایل .env تنظیم کنید.")
    exit(1)

INTERVAL = "45min"            # تایم‌فریم 45 دقیقه
COOLDOWN_MINUTES = 360        # کول‌داون 6 ساعته (360 دقیقه)
EMA_TREND = 200               # برای روند 4 ساعته

# لیست ارزهایی که می‌خوای ربات چک کنه
SYMBOLS = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT", "XRP-USDT", 
           "ADA-USDT", "DOGE-USDT", "AVAX-USDT", "DOT-USDT", "LINK-USDT"]

# ==========================================
# 🌐 توابع دریافت داده و محاسبات
# ==========================================
def get_klines(symbol, interval="45min", limit=200):
    url = f"https://api.kucoin.com/api/v1/market/candles?type={interval}&symbol={symbol}"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        if data['code'] != '200000':
            print(f"خطا در دریافت دیتای {symbol}: {data.get('msg', 'Unknown error')}")
            return None
        df = pd.DataFrame(data['data'], columns=['time', 'open', 'close', 'high', 'low', 'volume', 'turnover'])
        df = df.astype({'open': float, 'close': float, 'high': float, 'low': float, 'volume': float})
        df = df.iloc[::-1].reset_index(drop=True) # ترتیب رو از قدیم به جدید کن
        return df
    except Exception as e:
        print(f"Error fetching klines for {symbol}: {e}")
        return None

def calc_indicators(df):
    if df is None or len(df) < 50:
        return df

    # --- اندیکاتورهای پایه ---
    df["ema_9"] = df["close"].ewm(span=9, adjust=False).mean()
    df["ema_21"] = df["close"].ewm(span=21, adjust=False).mean()
    
    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))
    
    df["macd"] = df["close"].ewm(span=12, adjust=False).mean() - df["close"].ewm(span=26, adjust=False).mean()
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    
    # --- ایچیموکو ---
    high_9 = df['high'].rolling(window=9).max()
    low_9 = df['low'].rolling(window=9).min()
    df['tenkan_sen'] = (high_9 + low_9) / 2

    high_26 = df['high'].rolling(window=26).max()
    low_26 = df['low'].rolling(window=26).min()
    df['kijun_sen'] = (high_26 + low_26) / 2

    df['senkou_span_a'] = ((df['tenkan_sen'] + df['kijun_sen']) / 2).shift(26)
    high_52 = df['high'].rolling(window=52).max()
    low_52 = df['low'].rolling(window=52).min()
    df['senkou_span_b'] = ((high_52 + low_52) / 2).shift(26)

    # --- حجم و ATR و ADX ---
    df['avg_volume_20'] = df['volume'].rolling(window=20).mean()
    
    df['tr0'] = abs(df['high'] - df['low'])
    df['tr1'] = abs(df['high'] - df['close'].shift())
    df['tr2'] = abs(df['low'] - df['close'].shift())
    df['tr'] = df[['tr0', 'tr1', 'tr2']].max(axis=1)
    df['atr'] = df['tr'].rolling(window=14).mean()
    
    df['up_move'] = df['high'].diff()
    df['down_move'] = df['low'].shift() - df['low']
    df['plus_dm'] = np.where((df['up_move'] > df['down_move']) & (df['up_move'] > 0), df['up_move'], 0)
    df['minus_dm'] = np.where((df['down_move'] > df['up_move']) & (df['down_move'] > 0), df['down_move'], 0)
    df['tr14'] = df['tr'].rolling(window=14).sum()
    df['plus_di'] = 100 * (df['plus_dm'].rolling(window=14).sum() / df['tr14'])
    df['minus_di'] = 100 * (df['minus_dm'].rolling(window=14).sum() / df['tr14'])
    df['dx'] = 100 * abs(df['plus_di'] - df['minus_di']) / (df['plus_di'] + df['minus_di'])
    df['adx'] = df['dx'].rolling(window=14).mean()

    return df

def get_htf_trend(symbol):
    """دریافت روند تایم‌فریم 4 ساعته بر اساس EMA 200"""
    url = f"https://api.kucoin.com/api/v1/market/candles?type=4hour&symbol={symbol}"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        if data['code'] != '200000':
            return "NEUTRAL"
        closes = [float(candle[2]) for candle in data['data']]
        closes.reverse()
        
        if len(closes) < EMA_TREND:
            return "NEUTRAL"
            
        ema_200 = pd.Series(closes).ewm(span=EMA_TREND, adjust=False).mean().iloc[-1]
        current_price = closes[-1]
        
        if current_price > ema_200:
            return "UP"
        else:
            return "DOWN"
    except Exception as e:
        print(f"Error fetching HTF trend: {e}")
        return "NEUTRAL"

# ==========================================
# 🧠 منطق سیگنال‌دهی (تک‌تیرانداز)
# ==========================================
def check_signal(symbol, df):
    if df is None or len(df) < 50:
        return None
        
    htf_trend = get_htf_trend(symbol)
    
    current_price = df['close'].iloc[-1]
    current_volume = df['volume'].iloc[-1]
    avg_volume = df['avg_volume_20'].iloc[-1]
    current_adx = df['adx'].iloc[-1]
    current_atr = df['atr'].iloc[-1]
    
    kumo_a = df['senkou_span_a'].iloc[-1]
    kumo_b = df['senkou_span_b'].iloc[-1]

    # --- 1. فیلتر حجم (حداقل 1.5 برابر میانگین) ---
    if current_volume < (avg_volume * 1.5):
        return None

    # --- 2. فیلتر ADX (روند قوی بالای 25) ---
    if current_adx < 25:
        return None

    # --- شرط‌های سیگنال خرید (LONG) ---
    long_conditions = (
        (df['ema_9'].iloc[-1] > df['ema_21'].iloc[-1]) and
        (df['macd'].iloc[-1] > df['macd_signal'].iloc[-1]) and
        (df['rsi'].iloc[-1] > 50) and (df['rsi'].iloc[-1] < 70) and
        (df['close'].iloc[-1] > df['ema_9'].iloc[-1])
    )

    if long_conditions: 
        if htf_trend != "UP": return None
        if current_price < kumo_a or current_price < kumo_b: return None
            
        sl = current_price - (current_atr * 1.5)
        tp1 = current_price + (current_atr * 3.0)
        tp2 = current_price + (current_atr * 5.0)
        tp3 = current_price + (current_atr * 8.0)
        
        return {"type": "لانگ", "price": current_price, "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3, "open_time": time.time()}

    # --- شرط‌های سیگنال فروش (SHORT) ---
    short_conditions = (
        (df['ema_9'].iloc[-1] < df['ema_21'].iloc[-1]) and
        (df['macd'].iloc[-1] < df['macd_signal'].iloc[-1]) and
        (df['rsi'].iloc[-1] < 50) and (df['rsi'].iloc[-1] > 30) and
        (df['close'].iloc[-1] < df['ema_9'].iloc[-1])
    )

    if short_conditions:
        if htf_trend != "DOWN": return None
        if current_price > kumo_a or current_price > kumo_b: return None
            
        sl = current_price + (current_atr * 1.5)
        tp1 = current_price - (current_atr * 3.0)
        tp2 = current_price - (current_atr * 5.0)
        tp3 = current_price - (current_atr * 8.0)
        
        return {"type": "شورت", "price": current_price, "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3, "open_time": time.time()}

    return None

# ==========================================
# 📊 مدیریت سیگنال‌های فعال
# ==========================================
async def check_active_signals(bot, active_signals):
    for symbol, info in list(active_signals.items()):
        try:
            response = requests.get(f"https://api.kucoin.com/api/v1/market/orderbook/level1?symbol={symbol}")
            current_price = float(response.json()['data']['price'])
            
            # 1. بریک‌ایون (انتقال حد ضرر به نقطه ورود بعد از رسیدن به TP1)
            if info["type"] == "لانگ" and current_price >= info["tp1"]:
                if not info.get("moved_to_be", False):
                    info["sl"] = info["price"]
                    info["moved_to_be"] = True
                    await bot.send_message(chat_id=CHAT_ID, text=f"🛡 <b>حد ضرر {symbol} به بریک‌ایون منتقل شد.</b>", parse_mode="HTML")
            elif info["type"] == "شورت" and current_price <= info["tp1"]:
                if not info.get("moved_to_be", False):
                    info["sl"] = info["price"]
                    info["moved_to_be"] = True
                    await bot.send_message(chat_id=CHAT_ID, text=f"🛡 <b>حد ضرر {symbol} به بریک‌ایون منتقل شد.</b>", parse_mode="HTML")

            # 2. بررسی حد ضرر (SL)
            if info["type"] == "لانگ" and current_price <= info["sl"]:
                await bot.send_message(chat_id=CHAT_ID, text=f"❌ <b>حد ضرر {symbol} فعال شد.</b>\n💰 قیمت: {current_price}", parse_mode="HTML")
                del active_signals[symbol]
                continue
            elif info["type"] == "شورت" and current_price >= info["sl"]:
                await bot.send_message(chat_id=CHAT_ID, text=f"❌ <b>حد ضرر {symbol} فعال شد.</b>\n💰 قیمت: {current_price}", parse_mode="HTML")
                del active_signals[symbol]
                continue

            # 3. بررسی حد سود نهایی (TP3)
            if info["type"] == "لانگ" and current_price >= info["tp3"]:
                await bot.send_message(chat_id=CHAT_ID, text=f"✅ <b>حد سود نهایی {symbol} فعال شد.</b>\n💰 قیمت: {current_price}", parse_mode="HTML")
                del active_signals[symbol]
                continue
            elif info["type"] == "شورت" and current_price <= info["tp3"]:
                await bot.send_message(chat_id=CHAT_ID, text=f"✅ <b>حد سود نهایی {symbol} فعال شد.</b>\n💰 قیمت: {current_price}", parse_mode="HTML")
                del active_signals[symbol]
                continue

            # 4. حد ضرر زمانی (بعد از 24 ساعت)
            if "open_time" in info:
                if time.time() - info["open_time"] > (24 * 3600):
                    await bot.send_message(chat_id=CHAT_ID, text=f"⏳ <b>زمان معامله {symbol} به پایان رسید.</b>\n💰 قیمت فعلی: {current_price}", parse_mode="HTML")
                    del active_signals[symbol]
                    continue

        except Exception as e:
            print(f"خطا در بررسی سیگنال فعال {symbol}: {e}")

# ==========================================
# 🚀 حلقه اصلی ربات
# ==========================================
async def main_loop():
    bot = Bot(token=BOT_TOKEN)
    active_signals = {}
    last_signal_time = {}
    
    print("🤖 ربات شروع به کار کرد...")
    await bot.send_message(chat_id=CHAT_ID, text="🤖 ربات با تنظیمات جدید (تک‌تیرانداز) روشن شد.", parse_mode="HTML")

    while True:
        try:
            # 1. مدیریت سیگنال‌های باز
            if active_signals:
                await check_active_signals(bot, active_signals)

            # 2. اسکن بازار برای سیگنال جدید
            for symbol in SYMBOLS:
                # چک کردن کول‌داون (جلوگیری از سیگنال تکراری)
                if symbol in last_signal_time:
                    elapsed = time.time() - last_signal_time[symbol]
                    if elapsed < (COOLDOWN_MINUTES * 60):
                        continue # هنوز توی کول‌داونه، برو بعدی
                
                df = get_klines(symbol, INTERVAL)
                if df is None: continue
                
                df = calc_indicators(df)
                sig = check_signal(symbol, df)
                
                if sig:
                    # ذخیره زمان سیگنال برای کول‌داون
                    last_signal_time[symbol] = time.time()
                    active_signals[symbol] = sig
                    
                    # ارسال پیام تلگرام
                    msg = (
                        f"🚀 <b>سیگنال جدید: {symbol}</b>\n"
                        f"📈 نوع: <b>{sig['type']}</b>\n"
                        f"💰 قیمت ورود: {sig['price']}\n"
                        f"🛑 حد ضرر: {sig['sl']:.6f}\n"
                        f"🎯 هدف اول: {sig['tp1']:.6f}\n"
                        f"🎯 هدف دوم: {sig['tp2']:.6f}\n"
                        f"🎯 هدف سوم: {sig['tp3']:.6f}\n"
                        f"⏰ زمان: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                    )
                    await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="HTML")
                    print(f"✅ سیگنال {sig['type']} برای {symbol} ارسال شد.")
                
                time.sleep(0.5) # جلوگیری از محدودیت API صرافی

            # 3. استراحت تا اسکن بعدی (هر 5 دقیقه یک بار)
            await asyncio.sleep(300)

        except Exception as e:
            print(f"❌ خطا در حلقه اصلی: {e}")
            await asyncio.sleep(60) # در صورت خطا، 1 دقیقه صبر کن و دوباره تلاش کن

if __name__ == "__main__":
    asyncio.run(main_loop())
