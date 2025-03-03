import asyncio
import locale
import logging
import os
import sys
from pathlib import Path

import aiogram
from aiogram import types
from aiogram.filters import Command

from bot import bot, dp
from handlers.deezer import deezer_router
from handlers.youtube import youtube_router
from utils import TMP_DIR

if (
    sys.version_info.major != 3
    or sys.version_info.minor != 9
    or sys.version_info.micro != 18
):
    print(
        "Python 3.9.18 is required, but you are using Python {}.{}.{}".format(
            sys.version_info.major, sys.version_info.minor, sys.version_info.micro
        )
    )
    sys.exit(1)

# Print the version of all modules
print("Python version: ", sys.version)
print("aiogram version: ", aiogram.__version__)

locale.setlocale(locale.LC_TIME, "")

try:
    os.mkdir(TMP_DIR)
except FileExistsError:
    pass

try:
    os.mkdir(Path(TMP_DIR, "yt"))
except FileExistsError:
    pass

logging.basicConfig(level=logging.INFO)


@dp.message(Command(commands=["start", "help"]))
async def help_start(event: types.Message):
    bot_info = await bot.get_me()
    bot_name = (
        bot_info.first_name.replace("_", "\\_")
        .replace("*", "\\*")
        .replace("[", "\\[")
        .replace("`", "\\`")
    )
    bot_username = (
        bot_info.username.replace("_", "\\_")
        .replace("*", "\\*")
        .replace("[", "\\[")
        .replace("`", "\\`")
    )
    msg = "Hey, I'm *{}*\n".format(bot_name)
    msg += "_You can use me in inline mode :_\n"
    msg += "@{} \\(album\\|track\\|artist\\) \\<search\\>\n".format(bot_username)
    msg += "Or just send an *Deezer* album, track *link* or YouTube *link*"
    await event.answer(msg, parse_mode="MarkdownV2")


async def main() -> None:
    dp.include_routers(youtube_router, deezer_router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
