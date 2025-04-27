import asyncio
import io
import os
import traceback
from pathlib import Path

import requests
import yt_dlp
from PIL import Image
from aiogram import F, types
from aiogram.types import BufferedInputFile, FSInputFile
from mutagen.id3 import ID3, error, APIC
from mutagen.mp3 import MP3
from yt_dlp import YoutubeDL
from aiogram import Router

# Assuming utils provides these functions and constants
from utils import __, is_downloading, add_downloading, remove_downloading, TMP_DIR

print("yt-dlp version: ", yt_dlp.version.__version__)

youtube_router = Router()
soundcloud_router = Router()  # New router for SoundCloud

COOKIES_PATH = os.environ.get("COOKIES_PATH")

# Define separate temp directories
YT_TMP_DIR = Path(TMP_DIR, "yt")
SC_TMP_DIR = Path(TMP_DIR, "sc")

# Ensure temp directories exist
YT_TMP_DIR.mkdir(parents=True, exist_ok=True)
SC_TMP_DIR.mkdir(parents=True, exist_ok=True)


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
    print(f"Processing YouTube link from user {event.from_user.id}")
    if is_downloading(event.from_user.id) is False:
        add_downloading(event.from_user.id)
        tmp_msg = await event.answer(__("downloading"))
        try:
            ydl_opts = {
                "outtmpl": str(YT_TMP_DIR / "%(id)s.%(ext)s"),  # Use YT_TMP_DIR
                "format": "bestaudio/best",
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "320",
                    }
                ],
                "quiet": True,  # Suppress yt-dlp console output
                "no_warnings": True,
            }

            # if cookies.txt exists, use it
            if (
                COOKIES_PATH is not None
                and os.path.exists(COOKIES_PATH)
                and os.path.isfile(COOKIES_PATH)
                and os.path.getsize(COOKIES_PATH) > 0
            ):
                print("Using cookies for YouTube")
                ydl_opts["cookiefile"] = COOKIES_PATH

            # Download file
            ydl = YoutubeDL(ydl_opts)
            # Run in executor to avoid blocking asyncio loop
            dict_info = await asyncio.to_thread(
                ydl.extract_info, event.text, download=True
            )

            thumb_url = dict_info.get("thumbnail")
            track_title = dict_info.get("title", "Unknown Title")
            uploader = dict_info.get("uploader", "Unknown Artist")
            track_id = dict_info.get("id", "unknown_id")
            webpage_url = dict_info.get(
                "webpage_url", event.text
            )  # Use original link if webpage_url is missing

            # Get thumb
            image_bytes = None
            if thumb_url:
                try:
                    content = requests.get(thumb_url).content
                    image_bytes = io.BytesIO(content)
                except Exception as img_err:
                    print(f"Error downloading/processing thumbnail: {img_err}")

            upload_date_str = "Unknown date"
            upload_date = dict_info.get("upload_date")  # YYYYMMDD
            if upload_date and len(upload_date) == 8:
                try:
                    upload_date_str = (
                        f"{upload_date[6:8]}/{upload_date[4:6]}/{upload_date[0:4]}"
                    )
                except Exception:
                    pass  # Keep default if formatting fails

            # Send cover
            if image_bytes:
                try:
                    await event.answer_photo(
                        BufferedInputFile(image_bytes.getvalue(), filename="cover.jpg"),
                        caption=(
                            "<b>Track: {}</b>"
                            '\n{} - {}\n\n<a href="{}">' + __("track_link") + "</a>"
                        ).format(
                            track_title,
                            uploader,
                            upload_date_str,
                            webpage_url,
                        ),
                        parse_mode="HTML",
                    )
                    image_bytes.seek(0)  # Reset stream position for tagging
                except Exception as photo_err:
                    print(f"Error sending photo: {photo_err}")
            else:
                # Send caption as text if no thumbnail
                await event.answer(
                    (
                        "<b>Track: {}</b>"
                        '\n{} - {}\n\n<a href="{}">' + __("track_link") + "</a>"
                    ).format(
                        track_title,
                        uploader,
                        upload_date_str,
                        webpage_url,
                    ),
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )

            # Delete user message
            await event.delete()

            location = YT_TMP_DIR / f"{track_id}.mp3"

            # Check if file exists
            if not location.exists():
                raise FileNotFoundError(f"Expected audio file not found at {location}")

            # TAG audio
            thumb_for_tagging = None
            thumb_for_sending = None
            if image_bytes:
                try:
                    # Prepare thumbnail for tagging
                    thumb_for_tagging = image_bytes.getvalue()

                    # Create smaller thumb for sending with audio message
                    image_bytes.seek(0)  # Reset again
                    roi_img = crop_center(Image.open(image_bytes), 80, 80)
                    img_byte_arr = io.BytesIO()
                    if roi_img.mode in ("RGBA", "P"):
                        roi_img = roi_img.convert("RGB")
                    roi_img.save(img_byte_arr, format="jpeg")
                    thumb_for_sending = BufferedInputFile(
                        img_byte_arr.getvalue(), filename="thumb.jpg"
                    )
                except Exception as thumb_proc_err:
                    print(
                        f"Error processing thumbnail for tagging/sending: {thumb_proc_err}"
                    )
                    thumb_for_tagging = None
                    thumb_for_sending = None

            try:
                audio = MP3(location, ID3=ID3)
                try:
                    audio.add_tags()
                except error:
                    pass  # Ignore if tags already exist
                if thumb_for_tagging:
                    audio.tags.add(
                        APIC(
                            mime="image/jpeg",
                            type=3,
                            desc="Cover",
                            data=thumb_for_tagging,
                        )
                    )
                # Add other tags if needed (e.g., title, artist)
                # audio.tags.add(mutagen.id3.TIT2(encoding=3, text=track_title))
                # audio.tags.add(mutagen.id3.TPE1(encoding=3, text=uploader))
                audio.save()
            except Exception as tag_err:
                print(f"Error tagging audio file: {tag_err}")

            # Send audio
            await event.answer_audio(
                FSInputFile(location),
                title=track_title,
                performer=uploader,
                thumbnail=thumb_for_sending,  # Use the prepared thumb or None
                disable_notification=True,
            )
            try:
                os.remove(location)
            except FileNotFoundError:
                pass
        except yt_dlp.utils.DownloadError as dl_err:
            print(f"yt-dlp download error: {dl_err}")
            await event.answer(__("download_error_specific").format(str(dl_err)))
        except Exception as e:
            traceback.print_exc()
            await event.answer(
                __("download_error") + f"\n<code>{e}</code>", parse_mode="HTML"
            )
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


@soundcloud_router.message(
    F.text.regexp(
        r"^(?:https?:\/\/)?(?:www\.)?soundcloud\.com\/([a-zA-Z0-9_-]+)\/([a-zA-Z0-9_-]+)\/?(?:\?.*)?$"
    )
)
async def get_soundcloud_audio(event: types.Message):
    print(f"Processing SoundCloud link from user {event.from_user.id}")
    if is_downloading(event.from_user.id) is False:
        add_downloading(event.from_user.id)
        tmp_msg = await event.answer(__("downloading"))
        try:
            ydl_opts = {
                "outtmpl": str(SC_TMP_DIR / "%(id)s.%(ext)s"),  # Use SC_TMP_DIR
                "format": "bestaudio/best",
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "320",
                    }
                ],
                "quiet": True,  # Suppress yt-dlp console output
                "no_warnings": True,
            }

            # Cookies generally aren't needed for public SoundCloud tracks,
            # but you could add the logic here if required for private tracks/sets
            # if COOKIES_PATH ... etc.

            # Download file
            ydl = YoutubeDL(ydl_opts)
            # Run in executor to avoid blocking asyncio loop
            dict_info = await asyncio.to_thread(
                ydl.extract_info, event.text, download=True
            )

            # Extract metadata (keys might differ slightly from YouTube)
            thumb_url = dict_info.get("thumbnail")
            # SoundCloud often has 'track' and 'artist' instead of 'title' and 'uploader'
            track_title = dict_info.get("track") or dict_info.get(
                "title", "Unknown Title"
            )
            uploader = dict_info.get("artist") or dict_info.get(
                "uploader", "Unknown Artist"
            )
            track_id = dict_info.get("id", "unknown_sc_id")
            webpage_url = dict_info.get("webpage_url", event.text)

            # Get thumb
            image_bytes = None
            if thumb_url:
                try:
                    content = requests.get(thumb_url).content
                    image_bytes = io.BytesIO(content)
                except Exception as img_err:
                    print(
                        f"Error downloading/processing SoundCloud thumbnail: {img_err}"
                    )

            # SoundCloud doesn't usually provide an 'upload_date' in the same format
            # You might find it in 'timestamp' or other fields if needed, requires inspection
            description = dict_info.get("description", "")  # Or other relevant info

            # Send cover
            if image_bytes:
                try:
                    await event.answer_photo(
                        BufferedInputFile(image_bytes.getvalue(), filename="cover.jpg"),
                        caption=(
                            "<b>Track: {}</b>"
                            '\nArtist: {}\n\n<a href="{}">' + __("track_link") + "</a>"
                            # Add description or other info if desired
                            # "\n\n{}"
                        ).format(
                            track_title,
                            uploader,
                            webpage_url,
                            # description[:200] # Example: truncate description
                        ),
                        parse_mode="HTML",
                    )
                    image_bytes.seek(0)  # Reset stream position for tagging
                except Exception as photo_err:
                    print(f"Error sending SoundCloud photo: {photo_err}")
            else:
                # Send caption as text if no thumbnail
                await event.answer(
                    (
                        "<b>Track: {}</b>"
                        '\nArtist: {}\n\n<a href="{}">' + __("track_link") + "</a>"
                    ).format(
                        track_title,
                        uploader,
                        webpage_url,
                    ),
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )

            # Delete user message
            await event.delete()

            location = SC_TMP_DIR / f"{track_id}.mp3"

            # Check if file exists
            if not location.exists():
                raise FileNotFoundError(f"Expected audio file not found at {location}")

            # TAG audio
            thumb_for_tagging = None
            thumb_for_sending = None
            if image_bytes:
                try:
                    # Prepare thumbnail for tagging
                    thumb_for_tagging = image_bytes.getvalue()

                    # Create smaller thumb for sending with audio message
                    image_bytes.seek(0)  # Reset again
                    roi_img = crop_center(Image.open(image_bytes), 80, 80)
                    img_byte_arr = io.BytesIO()
                    if roi_img.mode in ("RGBA", "P"):
                        roi_img = roi_img.convert("RGB")
                    roi_img.save(img_byte_arr, format="jpeg")
                    thumb_for_sending = BufferedInputFile(
                        img_byte_arr.getvalue(), filename="thumb.jpg"
                    )
                except Exception as thumb_proc_err:
                    print(
                        f"Error processing SoundCloud thumbnail for tagging/sending: {thumb_proc_err}"
                    )
                    thumb_for_tagging = None
                    thumb_for_sending = None

            try:
                audio = MP3(location, ID3=ID3)
                try:
                    audio.add_tags()
                except error:
                    pass  # Ignore if tags already exist
                if thumb_for_tagging:
                    audio.tags.add(
                        APIC(
                            mime="image/jpeg",
                            type=3,
                            desc="Cover",
                            data=thumb_for_tagging,
                        )
                    )
                # Add other tags if needed
                # audio.tags.add(mutagen.id3.TIT2(encoding=3, text=track_title))
                # audio.tags.add(mutagen.id3.TPE1(encoding=3, text=uploader))
                audio.save()
            except Exception as tag_err:
                print(f"Error tagging SoundCloud audio file: {tag_err}")

            # Send audio
            await event.answer_audio(
                FSInputFile(location),
                title=track_title,
                performer=uploader,
                thumbnail=thumb_for_sending,  # Use the prepared thumb or None
                disable_notification=True,
            )
            try:
                os.remove(location)
            except FileNotFoundError:
                pass
        except yt_dlp.utils.DownloadError as dl_err:
            print(f"yt-dlp download error (SoundCloud): {dl_err}")
            await event.answer(__("download_error_specific").format(str(dl_err)))
        except Exception as e:
            traceback.print_exc()
            await event.answer(
                __("download_error") + f"\n<code>{e}</code>", parse_mode="HTML"
            )
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
