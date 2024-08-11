import asyncio
import io
import os
import traceback

import aioshutil
import requests
from PIL import Image
from aiogram import F, types
from aiogram.types import BufferedInputFile, FSInputFile
from mutagen.id3 import ID3, error, APIC
from mutagen.mp3 import MP3
from yt_dlp import YoutubeDL
from aiogram import Router

from utils import __, is_downloading, add_downloading, remove_downloading

youtube_router = Router()

COOKIES_PATH = os.environ.get("COOKIES_PATH")


def crop_center(pil_img, crop_width, crop_height):
    img_width, img_height = pil_img.size
    return pil_img.crop(
        (
            (img_width - crop_width) // 2,
            (img_height - crop_height) // 2,
            (img_width + crop_width) // 2,
            (img_height + crop_height) // 2,
        )
    )


@youtube_router.message(
    F.text.regexp(
        r"(?:http?s?:\/\/)?(?:www.)?(?:m.)?(?:music.)?youtu(?:\.?be)(?:\.com)?(?:("
        r"?:\w*.?:\/\/)?\w*.?\w*-?.?\w*\/(?:embed|e|v|watch|.*\/)?\??(?:feature=\w*\.?\w*)?&?("
        r"?:v=)?\/?)([\w\d_-]{11})(?:\S+)?"
    )
)
async def get_youtube_audio(event: types.Message):
    print(event.from_user)
    if is_downloading(event.from_user.id) is False:
        add_downloading(event.from_user.id)
        tmp_msg = await event.answer(__("downloading"))
        try:
            ydl_opts = {
                "outtmpl": "tmp/yt/%(id)s.%(ext)s",
                "format": "bestaudio/best",
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "320",
                    }
                ],
            }

            # if cookies.txt exists, use it
            if (
                COOKIES_PATH is not None
                and os.path.exists(COOKIES_PATH)
                and os.path.isfile(COOKIES_PATH)
                and os.path.getsize(COOKIES_PATH) > 0
            ):
                print("Using cookies")
                ydl_opts["cookiefile"] = COOKIES_PATH

            # Download file
            ydl = YoutubeDL(ydl_opts)
            dict_info = ydl.extract_info(event.text, download=True)

            thumb = dict_info["thumbnail"]

            # Get thumb
            content = requests.get(thumb).content

            upload_date = "Unknown date"
            try:
                if dict_info is not None and dict_info["upload_date"] is not None:
                    upload_date = dict_info["upload_date"]
                    upload_date = (
                        upload_date[6:8]
                        + "/"
                        + upload_date[4:6]
                        + "/"
                        + upload_date[0:4]
                    )
            except:
                pass

            # Send cover
            image_bytes = io.BytesIO(content)
            await event.answer_photo(
                BufferedInputFile(image_bytes.read(), filename="cover.jpg"),
                caption=(
                    "<b>Track: {}</b>"
                    '\n{} - {}\n\n<a href="{}">' + __("track_link") + "</a>"
                ).format(
                    dict_info["title"],
                    dict_info["uploader"],
                    upload_date,
                    "https://youtu.be/" + dict_info["id"],
                ),
                parse_mode="HTML",
            )

            # Delete user message
            await event.delete()

            location = "tmp/yt/" + dict_info["id"] + ".mp3"

            # TAG audio
            audio = MP3(location, ID3=ID3)
            try:
                audio.add_tags()
            except error:
                pass
            audio.tags.add(
                APIC(mime="image/jpeg", type=3, desc="Cover", data=image_bytes.read())
            )
            audio.save()

            # Create thumb
            roi_img = crop_center(Image.open(image_bytes), 80, 80)
            img_byte_arr = io.BytesIO()
            if roi_img.mode in ("RGBA", "P"):
                roi_img = roi_img.convert("RGB")
            roi_img.save(img_byte_arr, format="jpeg")

            # Send audio
            await event.answer_audio(
                FSInputFile(location),
                title=dict_info["title"],
                performer=dict_info["uploader"],
                thumbnail=BufferedInputFile(
                    img_byte_arr.getvalue(), filename="thumb.jpg"
                ),
                disable_notification=True,
            )
            try:
                await aioshutil.rmtree(os.path.dirname(location))
            except FileNotFoundError:
                pass
        except Exception as e:
            traceback.print_exc()
            await event.answer(__("download_error") + " " + str(e))
        finally:
            await tmp_msg.delete()
            try:
                remove_downloading(event.from_user.id)
            except ValueError:
                pass
    else:
        tmp_err_msg = await event.answer(__("running_download"))
        await event.delete()
        await asyncio.sleep(2)
        await tmp_err_msg.delete()
