import os
import requests

BOT_TOKEN = os.environ.get('BOT_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')

print("تست شروع شد...")
print("BOT_TOKEN وجود دارد: " + str(bool(BOT_TOKEN)))
print("CHAT_ID وجود دارد: " + str(bool(CHAT_ID)))

if not BOT_TOKEN or not CHAT_ID:
    print("خطا: توکن یا Chat ID تنظیم نشده!")
    exit(1)

# تست getMe
url = "https://api.telegram.org/bot" + BOT_TOKEN + "/getMe"
r = requests.get(url, timeout=10)
data = r.json()
print("getMe response: " + str(data))

# تست sendMessage
url = "https://api.telegram.org/bot" + BOT_TOKEN + "/sendMessage"
payload = {"chat_id": CHAT_ID, "text": "🧪 تست: ربات به تلگرام وصله!"}
r = requests.post(url, data=payload, timeout=10)
data = r.json()
print("sendMessage response: " + str(data))

print("تست تموم شد.")
