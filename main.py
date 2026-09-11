import os
import time
import requests

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_message(text):
    if not BOT_TOKEN or not CHAT_ID:
        print(text, flush=True)
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=20)

def main():
    print("404 TradePulse started.", flush=True)
    send_message("🤖 404 TradePulse is online.")
    while True:
        print("404 TradePulse heartbeat", flush=True)
        time.sleep(300)

if __name__ == "__main__":
    main()
