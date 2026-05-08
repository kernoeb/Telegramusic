import asyncio
import locale
import logging
import os
import re
import sys
from pathlib import Path

from aiogram import types, __version__ as aiogram_version
from aiogram.filters import Command, CommandObject

from bot import bot, dp
from dl_utils.deezer_download import TYPE_ALBUM, TYPE_TRACK
from handlers.deezer import (
    DEEZER_URL,
    deezer_router,
    handle_album_link,
    handle_track_link,
)
from handlers.yt_dlp import youtube_router, soundcloud_router
from utils import TMP_DIR

DEEP_LINK_PAYLOAD_REGEX = re.compile(
    rf"^({TYPE_TRACK}|{TYPE_ALBUM})_(\d+)$"
)

if sys.version_info < (3, 13):
    print(
        "Python 3.13 is required, but you are using Python {}.{}".format(
            sys.version_info.major, sys.version_info.minor
        )
    )
    sys.exit(1)

# Print the version of all modules
print("Python version: ", sys.version)
print("aiogram version: ", aiogram_version)

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
async def help_start(event: types.Message, command: CommandObject):
    if command.command == "start" and command.args:
        payload_match = DEEP_LINK_PAYLOAD_REGEX.match(command.args.strip())
        if payload_match:
            kind, item_id = payload_match.group(1), payload_match.group(2)
            real_link = f"{DEEZER_URL}/{kind}/{item_id}"
            if kind == TYPE_TRACK:
                await handle_track_link(event, real_link=real_link)
            else:
                await handle_album_link(event, real_link=real_link)
            return

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
    dp.include_routers(youtube_router, soundcloud_router, deezer_router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
