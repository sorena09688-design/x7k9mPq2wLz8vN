import os
print("BOT_TOKEN exists:", 'BOT_TOKEN' in os.environ)
print("CHAT_ID exists:", 'CHAT_ID' in os.environ)
print("BOT_TOKEN length:", len(os.environ.get('BOT_TOKEN', '')))
print("CHAT_ID value:", os.environ.get('CHAT_ID', 'NOT FOUND'))
