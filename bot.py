import os

from aiogram import Bot, Dispatcher

bot = Bot(token=os.environ.get("TELEGRAM_TOKEN"))
dp = Dispatcher()
