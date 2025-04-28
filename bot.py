import os

from aiogram import Bot, Dispatcher

telegram_token = os.environ.get("TELEGRAM_TOKEN")
if telegram_token is None:
    raise ValueError("TELEGRAM_TOKEN environment variable is not set")

bot = Bot(token=telegram_token)
dp = Dispatcher()
