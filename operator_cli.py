#!/usr/bin/env python3
import os
import sys

import requests
from dotenv import load_dotenv


def telegram_request(method, payload=None):
    load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID in .env")
        return 1

    url = f"https://api.telegram.org/bot{token}/{method}"
    response = requests.post(url, json=payload or {}, timeout=20)
    data = response.json()
    if not data.get("ok"):
        print(f"Telegram error: {data}")
        return 1
    return 0


def send_operator_on():
    message = (
        "Operator is on.\n\n"
        "Send completed tasks like:\n"
        "completed affidavit of service +\n\n"
        "I will log them when the Life OS bot is running."
    )
    return telegram_request("sendMessage", {
        "chat_id": os.environ["TELEGRAM_CHAT_ID"],
        "text": message,
    })


def status():
    code = telegram_request("getMe")
    if code == 0:
        print("Telegram credentials are valid. If messages are not replying, start the bot.")
    return code


def main():
    command = (sys.argv[1] if len(sys.argv) > 1 else "on").lower()
    if command == "on":
        raise SystemExit(send_operator_on())
    if command == "status":
        raise SystemExit(status())
    print("Use: operator on")
    print("     operator status")
    raise SystemExit(2)


if __name__ == "__main__":
    main()
