import asyncio
import locale
import logging
import os
import sys

from aiogram import types
from aiogram.filters import CommandStart

from handlers.deezer import deezer_router
from handlers.youtube import youtube_router

from bot import bot, dp

if (
    sys.version_info.major != 3
    or sys.version_info.minor != 9
    or sys.version_info.micro != 18
):
    print("Python 3.9.18 is required")
    sys.exit(1)

locale.setlocale(locale.LC_TIME, "")


try:
    os.mkdir("tmp")
except FileExistsError:
    pass

try:
    os.mkdir("tmp/yt/")
except FileExistsError:
    pass

logging.basicConfig(level=logging.INFO)


@dp.message(CommandStart())
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
    msg += "Or just send an *Deezer* album or track *link* \\!"
    await event.answer(msg, parse_mode="MarkdownV2")


async def main() -> None:
    dp.include_routers(youtube_router, deezer_router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
