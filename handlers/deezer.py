import asyncio
import hashlib
import math
import os
import re
import traceback
from pathlib import Path
from urllib.parse import quote
from zipfile import ZipFile, ZIP_DEFLATED

import aiohttp
import aioshutil
import deezloader.deezloader
import requests
from aiogram import F, types
from aiogram import Router
from aiogram.types import (
    FSInputFile,
    BufferedInputFile,
    InputMediaAudio,
    InlineQuery,
    InputTextMessageContent,
    InlineQueryResultArticle,
)
from aioify import aioify
from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from unidecode import unidecode

from bot import bot
from utils import __, is_downloading, add_downloading, remove_downloading, TMP_DIR

deezloader_async = aioify(obj=deezloader.deezloader, name="deezloader_async")
download = deezloader_async.DeeLogin(os.environ.get("DEEZER_TOKEN"))

deezer_router = Router()


class TelegramNetworkError(Exception):
    pass


DEFAULT_QUALITY = "FLAC" if os.environ.get("ENABLE_FLAC") == "1" else "MP3_320"
print("Default quality: " + DEFAULT_QUALITY)

# Constants
DEEZER_URL = "https://deezer.com"
API_URL = "https://api.deezer.com"
API_TRACK = API_URL + "/track/%s"
API_ALBUM = API_URL + "/album/%s"
API_SEARCH_TRK = API_URL + "/search/track/?q=%s"
API_PLAYLIST = API_URL + "/playlist/%s"

TRACK_REGEX = r"https?://(?:www\.)?deezer\.com/([a-z]*/)?track/(\d+)/?$"
ALBUM_REGEX = r"https?://(?:www\.)?deezer\.com/([a-z]*/)?album/(\d+)/?$"
PLAYLIST_REGEX = r"https?://(?:www\.)?deezer\.com/([a-z]*/)?playlist/(\d+)/?$"

COPY_FILES_PATH = os.environ.get("COPY_FILES_PATH")
FILE_LINK_TEMPLATE = os.environ.get("FILE_LINK_TEMPLATE")


def clean_filename(filename):
    # replace ".." at the beginning of the filename
    filename = re.sub(r"^\.\.", "__", filename)
    # replace "." at the beginning of the filename
    filename = re.sub(r"^\.", "_", filename)
    # replace characters that are not allowed in filenames
    return re.sub(r'[\\/*?:"<>|]', "_", filename)


async def download_track(url, retries=5):
    for attempt in range(retries):
        try:
            return await download.download_trackdee(
                url,
                output_dir=TMP_DIR,
                quality_download=DEFAULT_QUALITY,
                recursive_download=True,
                recursive_quality=True,
                not_interface=False,
            )
        except Exception as e:
            if attempt < retries - 1:
                sleep_time = 1 * (attempt + 1)
                print(
                    f"Error occurred while downloading track. Retrying... ({attempt + 1}/{retries}) (Sleeping for {sleep_time} seconds)"
                )
                await asyncio.sleep(1 * (attempt + 1))
            else:
                print(f"Failed to download track after {retries} attempts. Error: {e}")
                raise


async def download_album(url, retries=5):
    for attempt in range(retries):
        try:
            return await download.download_albumdee(
                url,
                output_dir=TMP_DIR,
                quality_download=DEFAULT_QUALITY,
                recursive_download=True,
                recursive_quality=True,
                not_interface=False,
            )
        except Exception as e:
            if attempt < retries - 1:
                sleep_time = 1 * (attempt + 1)
                print(
                    f"Error occurred while downloading album. Retrying... ({attempt + 1}/{retries}) (Sleeping for {sleep_time} seconds)"
                )
                await asyncio.sleep(1 * (attempt + 1))
            else:
                print(f"Failed to download album after {retries} attempts. Error: {e}")
                raise


def add_file_to_zip(zipf, file, track_file_mapping):
    """Helper function to add a file to the zip."""
    final_name = track_file_mapping.get(file, os.path.basename(file))
    zipf.write(file, final_name)


def create_single_zip(files, track_file_mapping, output_name):
    """Create a single zip file."""
    zip_name = f"{output_name}.zip"
    with ZipFile(zip_name, "w", ZIP_DEFLATED) as zipf:
        for file in files:
            add_file_to_zip(zipf, file, track_file_mapping)
    return [zip_name]


def create_multi_part_zip(source_dir, output_name, dl_tracks, max_size_mb=45):
    """Create a multi-part zip file."""
    max_size = max_size_mb * 1024 * 1024  # Convert to bytes
    all_files = set(os.path.join(source_dir, f) for f in os.listdir(source_dir))

    # Find and prioritize the cover file
    cover_file = next(
        (f for f in all_files if os.path.basename(f) == "cover.jpg"), None
    )
    files = [cover_file] if cover_file else []
    if cover_file:
        all_files.discard(cover_file)

    # Map track paths to their corresponding file names
    track_file_mapping = {}
    for track in dl_tracks:
        track_file = os.path.join(source_dir, os.path.basename(track.song_path))
        if track_file in all_files:
            files.append(track_file)
            all_files.remove(track_file)
            track_file_mapping[track_file] = (
                f"{clean_filename(track.song_name)}{track.file_format}"
            )

    # Add any remaining files
    files.extend(sorted(all_files))

    # Check total size of all files
    total_size = sum(os.path.getsize(f) for f in files if f)

    if total_size <= max_size:
        return create_single_zip(files, track_file_mapping, output_name)

    # Handle multi-part zip creation
    tmp_zip_files = []
    current_files = files[:]
    num_parts = math.ceil(total_size / max_size)

    for i in range(num_parts):
        zip_name = f"{output_name}_part{i + 1}.zip"
        with ZipFile(zip_name, "w", ZIP_DEFLATED) as zipf:
            current_size = 0
            while current_files and current_size < max_size:
                file = current_files[0]  # Peek the first file
                file_size = os.path.getsize(file)

                # Handle case where a single file is larger than max_size
                if file_size > max_size:
                    raise ValueError(
                        f"File {file} exceeds the maximum allowed zip size."
                    )

                # Check if file can be added to the current zip part
                if (
                    current_size + file_size <= max_size
                    or len(tmp_zip_files) == num_parts - 1
                ):
                    add_file_to_zip(zipf, file, track_file_mapping)
                    current_files.pop(0)  # Actually remove the file after adding
                    current_size += file_size
                else:
                    break

        tmp_zip_files.append(zip_name)

    # If there are any remaining files, ensure they are added to the last zip part
    if current_files:
        with ZipFile(tmp_zip_files[-1], "a", ZIP_DEFLATED) as zipf:
            for file in current_files:
                add_file_to_zip(zipf, file, track_file_mapping)

    return tmp_zip_files


async def get_track_info(track_id):
    """Get track information from Deezer API."""
    track_json = requests.get(API_TRACK % quote(str(track_id))).json()
    cover_url = (
        track_json["album"]["cover_xl"]
        or f"https://e-cdns-images.dzcdn.net/images/cover/{track_json['album']['md5_image']}/1200x0-000000-100-0-0.jpg"
    )
    cover = requests.get(cover_url, stream=True).raw
    artists = [c["name"] for c in track_json["contributors"]]
    release_date = track_json["release_date"].split("-")
    release_date = f"{release_date[2]}/{release_date[1]}/{release_date[0]}"
    year = release_date.split("/")[2]
    clean_title = re.sub(r'[\\/*?:"<>|]', "", track_json["title"])
    clean_artist = re.sub(r'[\\/*?:"<>|]', "", track_json["artist"]["name"])
    final_title = f"{clean_artist} - {clean_title} ({year})"
    return track_json, cover, artists, release_date, final_title


async def get_album_info(album_id):
    """Get album information from Deezer API."""
    album = requests.get(API_ALBUM % quote(str(album_id))).json()
    tracks = requests.get(API_ALBUM % quote(str(album_id)) + "/tracks?limit=100").json()
    cover_url = (
        album["cover_xl"]
        or f"https://e-cdns-images.dzcdn.net/images/cover/{album['md5_image']}/1200x0-000000-100-0-0.jpg"
    )
    cover = requests.get(cover_url, stream=True).raw
    titles = [track["title"] for track in tracks["data"]]
    artists = [
        [
            c["name"]
            for c in requests.get(API_TRACK % quote(str(track["id"]))).json()[
                "contributors"
            ]
        ]
        for track in tracks["data"]
    ]
    release_date = album["release_date"].split("-")
    release_date = f"{release_date[2]}/{release_date[1]}/{release_date[0]}"
    year = release_date.split("/")[2]
    clean_title = re.sub(r'[\\/*?:"<>|]', "", album["title"])
    clean_artist = re.sub(r'[\\/*?:"<>|]', "", album["artist"]["name"])
    final_title = f"{clean_artist} - {clean_title} ({year})"
    return album, tracks, cover, titles, artists, release_date, final_title


async def send_track(event, track_json, cover, artists, release_date, final_title, dl):
    """Send the track to the user."""
    if os.environ.get("FORMAT") == "zip":
        await send_zip(event, track_json, cover, release_date, final_title, dl)
    else:
        await send_audio(event, track_json, cover, artists, release_date, dl)


async def send_zip(event, json_data, cover, release_date, final_title, dl):
    """Send the track as a zip file."""
    songs_parent_dir = os.path.dirname(dl.song_path)
    read_cover = cover.read()
    with open(os.path.join(songs_parent_dir, "cover.jpg"), "wb") as cover_file:
        cover_file.write(read_cover)

    if COPY_FILES_PATH is not None and FILE_LINK_TEMPLATE is not None:
        md5_hash = hashlib.md5(final_title.encode()).hexdigest()[:8]
        zip_name = f"{unidecode(json_data['artist']['name'])} - {unidecode(json_data['title'])} ({md5_hash}).zip"
        url_safe_zip_name = re.sub(r"[^.a-zA-Z0-9()_-]", "_", zip_name)

        with ZipFile(
            Path(COPY_FILES_PATH) / url_safe_zip_name, "w", ZIP_DEFLATED
        ) as zipf:
            zipf.write(dl.song_path, clean_filename(dl.song_name) + dl.file_format)
            zipf.write(os.path.join(songs_parent_dir, "cover.jpg"), "cover.jpg")

        await event.answer_photo(
            BufferedInputFile(read_cover, filename="cover.jpg"),
            caption=get_caption(json_data, release_date),
            parse_mode="HTML",
        )

        await event.answer(FILE_LINK_TEMPLATE.format(url_safe_zip_name))
    else:
        await aioshutil.make_archive(
            Path(TMP_DIR) / final_title, "zip", songs_parent_dir
        )

        await event.answer_document(
            FSInputFile(Path(TMP_DIR) / f"{final_title}.zip"),
            caption=get_caption(json_data, release_date),
            parse_mode="HTML",
        )

    await event.delete()
    # Check if the file exists and remove it if it does
    zip_path = Path(TMP_DIR) / f"{final_title}.zip"
    if zip_path.exists():
        zip_path.unlink()


async def send_audio(event, json_data, cover, artists, release_date, dl):
    """Send the track as an audio file."""
    await event.answer_photo(
        BufferedInputFile(cover.read(), filename="cover.jpg"),
        caption=get_caption(json_data, release_date),
        parse_mode="HTML",
    )
    await event.delete()

    tmp_song = open(dl.song_path, "rb")
    duration = get_audio_duration(tmp_song, dl.song_path)
    tmp_song.seek(0)

    await event.answer_audio(
        FSInputFile(dl.song_path),
        title=json_data["title"],
        performer=", ".join(artists),
        duration=duration,
        disable_notification=True,
    )
    tmp_song.close()


async def send_album_media_group(event, tracks, titles, artists):
    """Send the album as a media group."""
    group_media = []
    for i, track in enumerate(tracks):
        tmp_song = open(track.song_path, "rb")
        duration = get_audio_duration(tmp_song, track.song_path)
        tmp_song.seek(0)
        group_media.append(
            InputMediaAudio(
                media=BufferedInputFile(
                    tmp_song.read(),
                    filename=titles[i] + os.path.splitext(track.song_path)[1],
                ),
                title=titles[i],
                performer=", ".join(artists[i]),
                duration=duration,
            )
        )
        tmp_song.close()
    await event.answer_media_group(group_media, disable_notification=True)


async def send_album_tracks_individually(event, tracks, titles, artists):
    """Send the album tracks individually."""
    for i, track in enumerate(tracks):
        tmp_song = open(track.song_path, "rb")
        duration = get_audio_duration(tmp_song, track.song_path)
        tmp_song.seek(0)
        await event.answer_audio(
            BufferedInputFile(
                tmp_song.read(),
                filename=titles[i] + os.path.splitext(track.song_path)[1],
            ),
            title=titles[i],
            performer=", ".join(artists[i]),
            duration=duration,
            disable_notification=True,
        )
        tmp_song.close()


def get_caption(json_data, release_date):
    """Get the caption for the track."""
    return (
        "<b>Track: {}</b>"
        '\n{} - {}\n<a href="{}">'
        + __("album_link")
        + '</a>\n<a href="{}">'
        + __("track_link")
        + "</a>"
    ).format(
        json_data["title"],
        json_data["artist"]["name"],
        release_date,
        json_data["album"]["link"],
        json_data["link"],
    )


def get_album_caption(album, release_date):
    """Get the caption for the album."""
    return (
        '<b>Album: {}</b>\n{} - {}\n<a href="{}">' + __("album_link") + "</a>"
    ).format(
        album["title"],
        album["artist"]["name"],
        release_date,
        album["link"],
    )


def get_audio_duration(file, path):
    """Get the duration of the audio file."""
    extension = os.path.splitext(path)[1]
    if extension == ".mp3":
        return int(MP3(file).info.length)
    elif extension == ".flac":
        return int(FLAC(file).info.length)
    return 0


@deezer_router.message(F.text.regexp(TRACK_REGEX))
async def get_track(event: types.Message, real_link=None):
    print(event.from_user, event.text)
    copy_text = real_link or event.text
    while not copy_text.startswith("h"):
        copy_text = copy_text[1:]
    copy_text = copy_text.strip()

    if not is_downloading(event.from_user.id):
        add_downloading(event.from_user.id)
        tmp = copy_text.rstrip("/")
        tmp_msg = await event.answer(__("downloading"))
        try:
            dl = await download_track(tmp)
            track_id = copy_text.split("/")[-1]
            (
                track_json,
                cover,
                artists,
                release_date,
                final_title,
            ) = await get_track_info(track_id)
            await send_track(
                event, track_json, cover, artists, release_date, final_title, dl
            )
            await tmp_msg.delete()
            await aioshutil.rmtree(os.path.dirname(dl.song_path))
            zip_path = Path(TMP_DIR) / f"{final_title}.zip"
            if os.path.exists(zip_path):
                os.remove(zip_path)
        except Exception as e:
            print(e)
            await tmp_msg.delete()
            await event.answer(__("download_error") + " " + str(e))
        finally:
            try:
                remove_downloading(event.from_user.id)
            except ValueError:
                pass
    else:
        tmp_err_msg = await event.answer(__("running_download"))
        await event.delete()
        await asyncio.sleep(2)
        await tmp_err_msg.delete()


@deezer_router.message(F.text.regexp(ALBUM_REGEX))
async def get_album(event: types.Message, real_link=None):
    print(event.from_user, event.text)
    copy_text = real_link or event.text
    while not copy_text.startswith("h"):
        copy_text = copy_text[1:]
    copy_text = copy_text.strip()

    if not is_downloading(event.from_user.id):
        add_downloading(event.from_user.id)
        tmp = copy_text.rstrip("/")
        tmp_msg = await event.answer(__("downloading"))
        try:
            dl = await download_album(tmp)
            album_id = copy_text.split("/")[-1]
            (
                album,
                tracks,
                cover,
                titles,
                artists,
                release_date,
                final_title,
            ) = await get_album_info(album_id)

            if os.environ.get("FORMAT") == "zip":
                await send_album_zip(event, album, cover, release_date, final_title, dl)
            else:
                await send_album_audio(
                    event, album, cover, titles, artists, release_date, dl
                )

            await tmp_msg.delete()
            await aioshutil.rmtree(os.path.dirname(dl.tracks[0].song_path))
        except Exception as e:
            print(e)
            traceback.print_exc()
            await tmp_msg.delete()
            await event.answer(__("download_error") + " " + str(e))
        finally:
            try:
                remove_downloading(event.from_user.id)
            except ValueError:
                pass
    else:
        tmp_err_msg = await event.answer(__("running_download"))
        await event.delete()
        await asyncio.sleep(2)
        await tmp_err_msg.delete()


async def send_album_zip(event, album, cover, release_date, final_title, dl):
    songs_parent_dir = os.path.dirname(dl.tracks[0].song_path)
    read_cover = cover.read()
    with open(os.path.join(songs_parent_dir, "cover.jpg"), "wb") as cover_file:
        cover_file.write(read_cover)

    if COPY_FILES_PATH is not None and FILE_LINK_TEMPLATE is not None:
        md5_hash = hashlib.md5(final_title.encode()).hexdigest()[:8]
        zip_name = f"{unidecode(album['artist']['name'])} - {unidecode(album['title'])} ({md5_hash}).zip"
        url_safe_zip_name = re.sub(r"[^.a-zA-Z0-9()_-]", "_", zip_name)

        with ZipFile(
            Path(COPY_FILES_PATH) / url_safe_zip_name, "w", ZIP_DEFLATED
        ) as zipf:
            for track in dl.tracks:
                zipf.write(
                    track.song_path, clean_filename(track.song_name) + track.file_format
                )
            zipf.write(os.path.join(songs_parent_dir, "cover.jpg"), "cover.jpg")

        await event.answer_photo(
            BufferedInputFile(read_cover, filename="cover.jpg"),
            caption=get_album_caption(album, release_date),
            parse_mode="HTML",
        )

        await event.answer(FILE_LINK_TEMPLATE.format(url_safe_zip_name))
    else:
        zip_files = create_multi_part_zip(
            songs_parent_dir, Path(TMP_DIR) / final_title, dl.tracks
        )
        for zip_file in zip_files:
            await event.answer_document(
                FSInputFile(zip_file),
                caption=get_album_caption(album, release_date),
                parse_mode="HTML",
            )

        for zip_file in zip_files:
            if os.path.exists(zip_file):
                os.remove(zip_file)

    await event.delete()


async def send_album_audio(event, album, cover, titles, artists, release_date, dl):
    read_cover = cover.read()
    await event.answer_photo(
        BufferedInputFile(read_cover, filename="cover.jpg"),
        caption=get_album_caption(album, release_date),
        parse_mode="HTML",
    )
    await event.delete()

    try:
        if 2 <= len(dl.tracks) <= 10:
            await send_album_media_group(event, dl.tracks, titles, artists)
        else:
            raise TelegramNetworkError
    except Exception:
        await send_album_tracks_individually(event, dl.tracks, titles, artists)


@deezer_router.message(
    F.text.regexp(r"^https?://(?:www\.)?(?:deezer|dzr)\.page\.link/.*$")
)
async def get_shortlink(event: types.Message):
    r = requests.get(event.text)
    real_link = r.url.split("?")[0]
    if re.match(TRACK_REGEX, real_link):
        await get_track(event, real_link)
    elif re.match(ALBUM_REGEX, real_link):
        await get_album(event, real_link)
    else:
        print("Unknown link: " + real_link)
        await event.answer(__("download_error"))


@deezer_router.inline_query()
async def inline_echo(inline_query: InlineQuery):
    items = []

    if inline_query.query:
        album = False
        if inline_query.query.startswith("artist "):
            album = True
            tmp_text = 'artist:"{}"'.format(inline_query.query.split("artist ")[1])
        elif inline_query.query.startswith("track "):
            tmp_text = 'track:"{}"'.format(inline_query.query.split("track ")[1])
        elif inline_query.query.startswith("album "):
            album = True
            tmp_text = 'album:"{}"'.format(inline_query.query.split("album ")[1])
        else:
            tmp_text = inline_query.query

        text = API_SEARCH_TRK % quote(str(tmp_text))

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(text) as resp:
                    r = await resp.json()

                all_ids = []
                tasks = []

                for i in r["data"]:
                    tmp_url = i["album"]["tracklist"]
                    tmp_id = re.search("/album/(.*)/tracks", tmp_url).group(1)
                    if not (album and tmp_id in all_ids):
                        # Append tasks to the list in batches of 10
                        tasks.append(fetch_album_data(session, tmp_id, i, album))
                        if len(tasks) >= 10:
                            batch_results = await asyncio.gather(*tasks)
                            items.extend(batch_results)
                            tasks.clear()  # Clear tasks after each batch

                # Handle any remaining tasks (if less than 10)
                if tasks:
                    batch_results = await asyncio.gather(*tasks)
                    items.extend(batch_results)

        except KeyError:
            pass
        except AttributeError:
            pass

    await bot.answer_inline_query(inline_query.id, results=items, cache_time=300)


async def fetch_album_data(session, tmp_id, track_data, album):
    async with session.get(API_ALBUM % quote(str(tmp_id))) as album_resp:
        tmp_album = await album_resp.json()

    tmp_date = tmp_album["release_date"].split("-")
    tmp_date = tmp_date[2] + "/" + tmp_date[1] + "/" + tmp_date[0]

    if album:
        title = track_data["album"]["title"]
        tmp_input = InputTextMessageContent(
            message_text=DEEZER_URL + "/album/%s" % quote(str(tmp_id))
        )
        try:
            nb = str(len(tmp_album["tracks"]["data"])) + " audio(s)"
        except KeyError:
            nb = ""
        show_txt_album = " | " + nb + " (album)"
    else:
        show_txt_album = ""
        tmp_input = InputTextMessageContent(message_text=track_data["link"])
        title = track_data["title"]

    result_id = str(track_data["id"])
    item = InlineQueryResultArticle(
        id=result_id,
        title=title,
        description=track_data["artist"]["name"] + " | " + tmp_date + show_txt_album,
        thumb_url=track_data["album"]["cover_small"],
        input_message_content=tmp_input,
    )

    return item
