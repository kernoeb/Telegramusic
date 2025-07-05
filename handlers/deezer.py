import asyncio
import hashlib
import math
import os
import re
import ssl
import traceback
from pathlib import Path
from urllib.parse import quote
from zipfile import ZipFile, ZIP_DEFLATED
import functools
import aiohttp
import aioshutil
import certifi  # SSL certificates
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
from unidecode import unidecode

from bot import bot

from utils import (
    __,
    is_downloading,
    add_downloading,
    remove_downloading,
    TMP_DIR,
)
from dl_utils.deezer_utils import clean_filename, get_audio_duration
from dl_utils.deezer_download import (
    init_deezer_session,
    get_song_infos_from_deezer_website,
    download_song,
    deezer_search,
    TYPE_TRACK,
    TYPE_ALBUM,
    DeezerApiException,
    get_file_format,
)


deezer_router = Router()


class TelegramNetworkError(Exception):
    pass


DEFAULT_QUALITY = "flac" if os.environ.get("ENABLE_FLAC") == "1" else "mp3"
print("Default quality: " + DEFAULT_QUALITY)
init_deezer_session("", DEFAULT_QUALITY)

MAX_RETRIES = int(os.environ.get("MAX_RETRIES", 5))
print("Max retries: " + str(MAX_RETRIES))

SEND_ALBUM_COVER = False if os.environ.get("SEND_ALBUM_COVER") == "false" else True
print("Send album cover: " + str(SEND_ALBUM_COVER))

# Constants
DEEZER_URL = "https://deezer.com"
API_URL = "https://api.deezer.com"
API_TRACK = API_URL + "/track/%s"
API_ALBUM = API_URL + "/album/%s"

TRACK_REGEX = r"https?://(?:www\.)?deezer\.com/([a-z]*/)?track/(\d+)/?$"
ALBUM_REGEX = r"https?://(?:www\.)?deezer\.com/([a-z]*/)?album/(\d+)/?$"
PLAYLIST_REGEX = r"https?://(?:www\.)?deezer\.com/([a-z]*/)?playlist/(\d+)/?$"  # Note: Playlist handling not fully implemented

COPY_FILES_PATH = os.environ.get("COPY_FILES_PATH")
FILE_LINK_TEMPLATE = os.environ.get("FILE_LINK_TEMPLATE")


async def download_track(track_id, retries=MAX_RETRIES):
    """Downloads a single track from Deezer using imported functions."""
    tmp_track_base_dir = (
        None  # Define outside the try/except to avoid "possibly unbound" errors
    )

    for attempt in range(retries):
        try:
            # Fetch track metadata from Deezer website (may include download details)
            track_infos = get_song_infos_from_deezer_website("track", track_id)
            if not track_infos:
                print(f"Attempt {attempt + 1}: Could not get track info for {track_id}")
                if attempt < retries - 1:
                    await asyncio.sleep(1 * (attempt + 1))
                    continue
                else:
                    raise ValueError(
                        f"Failed to get track info for {track_id} after {retries} attempts."
                    )

            # Make sure track_infos is a dictionary, not a list
            if isinstance(track_infos, list):
                if len(track_infos) > 0:
                    track_infos = track_infos[0]  # Take the first item if it's a list
                else:
                    raise ValueError(
                        f"Empty track info list received for track {track_id}"
                    )

            file_extension, deezer_format = get_file_format(track_infos)

            # Create a temporary directory for this track
            tmp_track_base_dir = Path(TMP_DIR) / "deezer" / "track" / str(track_id)
            tmp_track_base_dir.mkdir(parents=True, exist_ok=True)

            # Determine the expected final file path within our base dir
            song_path = tmp_track_base_dir / f"{track_id}{file_extension}"

            # Perform the actual download
            download_song(
                track_infos, deezer_format, str(song_path)
            )  # download_song expects string path

            # Check if download was successful (e.g., file exists and has size)
            if not song_path.exists() or song_path.stat().st_size == 0:
                # Clean up potentially empty file before retrying
                if song_path.exists():
                    try:
                        song_path.unlink()
                    except OSError:
                        pass
                raise IOError(f"Downloaded file {song_path} is missing or empty.")

            # Add download-specific details to the track_infos dictionary
            # Create a deep copy to avoid modifying the original if it's not a dict
            track_info_dict = {}
            if isinstance(track_infos, dict):
                track_info_dict = track_infos.copy()

            track_info_dict["song_path"] = str(song_path)  # Store as string
            track_info_dict["song_name"] = (
                track_infos.get("SNG_TITLE", f"Track {track_id}")
                if isinstance(track_infos, dict)
                else f"Track {track_id}"
            )
            track_info_dict["artist_name"] = (
                track_infos.get("ART_NAME", "Unknown Artist")
                if isinstance(track_infos, dict)
                else "Unknown Artist"
            )
            track_info_dict["file_extension"] = file_extension
            track_info_dict["download_dir"] = str(
                tmp_track_base_dir
            )  # Store base dir path
            # Carry over track number if present in original info
            if isinstance(track_infos, dict) and "TRACK_NUMBER" in track_infos:
                track_info_dict["TRACK_NUMBER"] = track_infos["TRACK_NUMBER"]

            print(f"Successfully downloaded track {track_id} to {song_path}")
            return track_info_dict  # Success, return details

        except Exception as e:
            print(
                f"Error downloading track {track_id} on attempt {attempt + 1}/{retries}: {e}"
            )
            # No specific directory per attempt to clean here, as we use a consistent base dir.
            # The failed/empty file is handled above before raising IOError.

            if attempt < retries - 1:
                sleep_time = 1 * (attempt + 1)
                print(f"Retrying in {sleep_time} seconds...")
                await asyncio.sleep(sleep_time)
            else:
                print(f"Failed to download track {track_id} after {retries} attempts.")
                # Clean up the base directory if the track ultimately failed
                if tmp_track_base_dir and tmp_track_base_dir.exists():
                    await aioshutil.rmtree(tmp_track_base_dir, ignore_errors=True)
                raise  # Re-raise the last exception

    # This part should ideally not be reached if retries are exhausted (exception raised)
    # Clean up the base directory if we somehow exit the loop without success
    if tmp_track_base_dir and tmp_track_base_dir.exists():
        await aioshutil.rmtree(tmp_track_base_dir, ignore_errors=True)
    return None


async def download_album(album_id, retries=MAX_RETRIES):
    """Downloads all tracks from a Deezer album using imported functions, with per-track retries."""
    album_info_attempt = 0
    album_tracks_infos = None
    tmp_download_dir = None  # Define outside the loop for cleanup

    # --- Retry fetching album metadata ---
    while album_info_attempt < retries:
        try:
            album_tracks_infos = get_song_infos_from_deezer_website("album", album_id)
            if not album_tracks_infos:
                raise ValueError(
                    f"Could not get album info for {album_id} (empty list received)"
                )

            # Create a temporary directory for this album download ONCE after successful metadata fetch
            tmp_download_dir = Path(TMP_DIR) / "deezer" / "album" / str(album_id)
            tmp_download_dir.mkdir(parents=True, exist_ok=True)
            print(
                f"Album metadata fetched successfully. Download dir: {tmp_download_dir}"
            )
            break  # Exit metadata retry loop on success

        except Exception as e:
            album_info_attempt += 1
            print(
                f"Attempt {album_info_attempt}/{retries}: Error fetching album info for {album_id}: {e}"
            )
            if album_info_attempt < retries:
                sleep_time = 1 * album_info_attempt
                print(f"Retrying album info fetch in {sleep_time} seconds...")
                await asyncio.sleep(sleep_time)
            else:
                print(
                    f"Failed to get album info for {album_id} after {retries} attempts."
                )
                # Clean up dir if it was created in a previous failed attempt (unlikely here, but safe)
                if tmp_download_dir and tmp_download_dir.exists():
                    await aioshutil.rmtree(tmp_download_dir, ignore_errors=True)
                raise  # Re-raise the last exception related to fetching album info

    if not album_tracks_infos or not tmp_download_dir:
        # This should not happen if the loop above works correctly, but as a safeguard:
        print(f"Failed to initialize album download for {album_id}.")
        return None  # Indicate failure

    # --- Download individual tracks with retries ---
    downloaded_tracks_details = []
    tasks = []

    # Prepare download tasks for each track
    for i, track_infos in enumerate(album_tracks_infos):
        track_sng_id = track_infos.get("SNG_ID", f"album_{album_id}_track_{i}")
        file_extension, deezer_format = get_file_format(track_infos)
        # Define the final path within the album's download directory
        song_path = tmp_download_dir / f"{track_sng_id}{file_extension}"

        # Create a closure to capture loop variables correctly for async task
        # This inner function now includes the retry logic for a single track
        async def download_single_with_retry(ti, fe, df, sp, track_retries=MAX_RETRIES):
            track_id = ti.get("SNG_ID", "N/A")
            for attempt in range(track_retries):
                try:
                    # Ensure download_song doesn't create its own conflicting temp dirs if possible
                    download_song(ti, df, str(sp))  # download_song expects string path

                    if not sp.exists() or sp.stat().st_size == 0:
                        # Clean up potentially empty file before retrying
                        if sp.exists():
                            try:
                                sp.unlink()
                            except OSError:
                                pass
                        raise IOError(f"Downloaded file {sp} is missing or empty.")

                    # Add details after successful download
                    ti_copy = ti.copy()  # Work on a copy
                    ti_copy["song_path"] = str(sp)
                    ti_copy["song_name"] = ti_copy.get("SNG_TITLE", f"Track {track_id}")
                    ti_copy["artist_name"] = ti_copy.get("ART_NAME", "Unknown Artist")
                    ti_copy["file_extension"] = fe
                    # Keep track number if available
                    if "TRACK_NUMBER" in ti:
                        ti_copy["TRACK_NUMBER"] = ti["TRACK_NUMBER"]

                    print(
                        f"Successfully downloaded track {track_id} to {sp} (attempt {attempt + 1})"
                    )
                    return ti_copy  # Success for this track

                except Exception as track_e:
                    print(
                        f"Error downloading track {track_id} (attempt {attempt + 1}/{track_retries}): {track_e}"
                    )
                    # Clean up potentially failed/partial file for this attempt
                    if sp.exists():
                        try:
                            sp.unlink()
                        except OSError:
                            pass

                    if attempt < track_retries - 1:
                        sleep_time = 1 * (
                            attempt + 1
                        )  # Exponential backoff might be better
                        print(f"Retrying track {track_id} in {sleep_time} seconds...")
                        await asyncio.sleep(sleep_time)
                    else:
                        print(
                            f"Failed to download track {track_id} after {track_retries} attempts."
                        )
                        return None  # Indicate failure for this specific track after all retries

            return None  # Should not be reached, but indicates failure

        tasks.append(
            download_single_with_retry(
                track_infos, file_extension, deezer_format, song_path
            )
        )  # Pass original dict and path

    # Run downloads concurrently
    results = await asyncio.gather(*tasks)

    # Filter out failed downloads (None results)
    downloaded_tracks_details = [res for res in results if res is not None]

    # Check if *any* tracks were successfully downloaded
    if not downloaded_tracks_details:
        print(f"Failed to download any tracks for album {album_id}.")
        # Clean up the main album directory as the entire process failed
        if tmp_download_dir and tmp_download_dir.exists():
            await aioshutil.rmtree(tmp_download_dir, ignore_errors=True)
        # Raising an exception here will be caught by the handler's main try/except
        raise Exception(
            f"Failed to download any tracks for album {album_id} after retries."
        )

    # Add the download directory to all *successful* track dicts
    # This is needed for zipping later
    for track_detail in downloaded_tracks_details:
        track_detail["download_dir"] = str(tmp_download_dir)

    print(
        f"Successfully downloaded {len(downloaded_tracks_details)} out of {len(album_tracks_infos)} tracks for album {album_id} to {tmp_download_dir}"
    )
    # Return list of successfully downloaded track details
    # The calling handler will manage cleanup of the tmp_download_dir
    return downloaded_tracks_details


def get_track_metadata_from_api(track_id):
    """Gets track metadata from the official Deezer API."""
    try:
        response = requests.get(API_TRACK % quote(str(track_id)))
        response.raise_for_status()  # Raise an exception for bad status codes
        track_json = response.json()

        if "error" in track_json:
            raise ValueError(f"API Error for track {track_id}: {track_json['error']}")

        # Extract cover URL, preferring larger sizes
        cover_url = (
            track_json.get("album", {}).get("cover_xl")
            or track_json.get("album", {}).get("cover_big")
            or track_json.get("album", {}).get("cover_medium")
            or f"https://e-cdns-images.dzcdn.net/images/cover/{track_json.get('album', {}).get('md5_image', '')}/1200x0-000000-100-0-0.jpg"
        )

        # Fetch cover image data
        cover_response = requests.get(cover_url, stream=True)
        cover_response.raise_for_status()
        cover_data = cover_response.content  # Read content directly

        # Extract other metadata
        artists = [c["name"] for c in track_json.get("contributors", [])]
        release_date_str = track_json.get("release_date", "0000-00-00")
        try:
            year = release_date_str.split("-")[0]
            # Format date as DD/MM/YYYY
            release_date_formatted = "/".join(reversed(release_date_str.split("-")))
        except:
            year = "0000"
            release_date_formatted = "00/00/0000"

        title = track_json.get("title", f"Track {track_id}")
        artist_name = track_json.get("artist", {}).get("name", "Unknown Artist")
        album_title = track_json.get("album", {}).get("title", "Unknown Album")
        album_link = track_json.get("album", {}).get("link", "")
        track_link = track_json.get("link", "")

        # Clean names for file system use
        clean_title = clean_filename(title)
        clean_artist = clean_filename(artist_name)
        clean_album_title = clean_filename(album_title)

        # Prepare metadata dictionary
        metadata = {
            "id": track_id,
            "title": title,
            "artist": artist_name,
            "album_title": album_title,
            "artists_list": artists,
            "release_date": release_date_formatted,
            "year": year,
            "album_link": album_link,
            "track_link": track_link,
            "cover_data": cover_data,
            "api_json": track_json,  # Keep original json if needed
            # For zip naming/structure
            "clean_artist": clean_artist,
            "clean_album_title": clean_album_title,
            "clean_title": clean_title,
        }
        print(f"Fetched metadata for track {track_id}: {artist_name} - {title}")
        return metadata

    except requests.exceptions.RequestException as e:
        print(f"Network error fetching metadata for track {track_id}: {e}")
        raise
    except Exception as e:
        print(f"Error processing metadata for track {track_id}: {e}")
        raise


def get_album_metadata_from_api(album_id):
    """Gets album and its tracks' metadata from the official Deezer API."""
    try:
        # Fetch main album info
        album_response = requests.get(API_ALBUM % quote(str(album_id)))
        album_response.raise_for_status()
        album_json = album_response.json()
        if "error" in album_json:
            raise ValueError(f"API Error for album {album_id}: {album_json['error']}")

        # Fetch track list (handle pagination if necessary, though 1000 limit is high)
        tracks_response = requests.get(
            API_ALBUM % quote(str(album_id)) + "/tracks?limit=1000"
        )
        tracks_response.raise_for_status()
        tracks_json = tracks_response.json()
        if "error" in tracks_json:
            # Might happen if album is empty or restricted
            print(
                f"API Error fetching tracks for album {album_id}: {tracks_json['error']}"
            )
            tracks_data = []
        else:
            tracks_data = tracks_json.get("data", [])

        # Extract cover URL
        cover_url = (
            album_json.get("cover_xl")
            or album_json.get("cover_big")
            or album_json.get("cover_medium")
            or f"https://e-cdns-images.dzcdn.net/images/cover/{album_json.get('md5_image', '')}/1200x0-000000-100-0-0.jpg"
        )

        # Fetch cover image data
        cover_response = requests.get(cover_url, stream=True)
        cover_response.raise_for_status()
        cover_data = cover_response.content

        # Extract album metadata
        release_date_str = album_json.get("release_date", "0000-00-00")
        try:
            year = release_date_str.split("-")[0]
            release_date_formatted = "/".join(reversed(release_date_str.split("-")))
        except:
            year = "0000"
            release_date_formatted = "00/00/0000"

        album_title = album_json.get("title", f"Album {album_id}")
        artist_name = album_json.get("artist", {}).get("name", "Unknown Artist")
        album_link = album_json.get("link", "")

        # Clean names for file system use
        clean_artist = clean_filename(artist_name)
        clean_album_title = clean_filename(album_title)

        # Prepare metadata dictionary
        metadata = {
            "id": album_id,
            "title": album_title,  # Album title
            "artist": artist_name,  # Main album artist
            "release_date": release_date_formatted,
            "year": year,
            "album_link": album_link,
            "track_link": None,  # No single track link for album
            "cover_data": cover_data,
            "api_json": album_json,
            "tracks_api_data": tracks_data,  # List of track dicts from API
            # For zip naming/structure
            "clean_artist": clean_artist,
            "clean_album_title": clean_album_title,
            "clean_title": clean_album_title,  # Use album title for clean_title contextually
        }
        print(f"Fetched metadata for album {album_id}: {artist_name} - {album_title}")
        return metadata

    except requests.exceptions.RequestException as e:
        print(f"Network error fetching metadata for album {album_id}: {e}")
        raise
    except Exception as e:
        print(f"Error processing metadata for album {album_id}: {e}")
        raise


def get_track_caption(metadata):
    """Generates caption for a single track using imported __ function."""
    return (
        "<b>Track: {title}</b>\n"
        "{artist} - {release_date}\n"
        '<a href="{album_link}">' + __("album_link") + "</a>\n"
        '<a href="{track_link}">' + __("track_link") + "</a>"
    ).format(**metadata)


def get_album_caption(metadata):
    """Generates caption for an album using imported __ function."""
    return (
        "<b>Album: {title}</b>\n"
        "{artist} - {release_date}\n"
        '<a href="{album_link}">' + __("album_link") + "</a>"
    ).format(**metadata)


def get_user_infos(event: types.Message):
    user_id = None
    username = None
    first_name = None

    if event.from_user:
        user_id = event.from_user.id
        username = event.from_user.username
        first_name = event.from_user.first_name

    return user_id, username, first_name


async def send_track_audio(event: types.Message, metadata, dl_track_info):
    """Sends a single track as an audio file."""
    user_id, username, first_name = get_user_infos(event)
    print(
        f"USER_DEBUG: Sending track audio to user_id={user_id} username={username} first_name={first_name}"
    )

    title = metadata.get("title", dl_track_info["song_name"])
    caption = get_track_caption(metadata)
    song_path = dl_track_info["song_path"]
    duration = get_audio_duration(song_path)
    performer = ", ".join(metadata.get("artists_list", [metadata["artist"]]))

    if SEND_ALBUM_COVER:
        # Send cover photo first
        await event.answer_photo(
            BufferedInputFile(metadata["cover_data"], filename="cover.jpg"),
            caption=caption,
            parse_mode="HTML",
        )

    # Send audio file
    await event.answer_audio(
        FSInputFile(
            song_path,
            filename=f"{clean_filename(performer)} - {clean_filename(title)}{dl_track_info['file_extension']}",
        ),
        title=metadata["title"],
        performer=performer,
        duration=duration,
        disable_notification=True,
    )


async def send_album_audio(event: types.Message, metadata, dl_tracks_info):
    """Sends album tracks as audio files (individually or as media group)."""
    user_id, username, first_name = get_user_infos(event)
    print(
        f"USER_DEBUG: Sending album audio to user_id={user_id} username={username} first_name={first_name}"
    )

    caption = get_album_caption(metadata)

    if SEND_ALBUM_COVER:
        # Send cover photo first
        await event.answer_photo(
            BufferedInputFile(metadata["cover_data"], filename="cover.jpg"),
            caption=caption,
            parse_mode="HTML",
        )

    # Map API track data to downloaded files (using SNG_ID if available)
    api_tracks_by_id = {
        str(t.get("id", "")): t for t in metadata.get("tracks_api_data", [])
    }
    media_group = []
    processed_files = []

    # Sort downloaded tracks based on track number if available
    try:
        dl_tracks_info.sort(
            key=lambda t: int(t.get("TRACK_NUMBER", "999"))
            if str(t.get("TRACK_NUMBER", "999")).isdigit()
            else 999
        )
    except Exception as sort_e:
        print(
            f"Warning: Could not sort tracks by track number for sending. Error: {sort_e}"
        )

    for dl_info in dl_tracks_info:
        song_path = dl_info["song_path"]
        # Try to find matching API data for better titles/artists
        # Extract potential ID from filename if SNG_ID wasn't stored reliably
        potential_id = Path(song_path).stem  # e.g., '12345' from '12345.flac'
        api_track = api_tracks_by_id.get(dl_info.get("SNG_ID")) or api_tracks_by_id.get(
            potential_id
        )

        if api_track:
            title = api_track.get("title", dl_info["song_name"])
            # Get contributors from the specific track API data if possible
            artists = [c["name"] for c in api_track.get("contributors", [])]
            if not artists:  # Fallback to main album artist
                artists = [metadata["artist"]]
            performer = ", ".join(artists)
        else:
            # Fallback if no matching API data found
            title = dl_info["song_name"]
            performer = dl_info["artist_name"]  # Artist info from download step

        duration = get_audio_duration(song_path)
        file_input = FSInputFile(song_path)  # Use FSInputFile for media group

        media_item = InputMediaAudio(
            media=file_input,
            filename=f"{clean_filename(performer)} - {clean_filename(title)}{dl_info['file_extension']}",
            title=title,
            performer=performer,
            duration=duration,
        )
        media_group.append(media_item)
        processed_files.append(
            {
                "path": song_path,
                "title": title,
                "performer": performer,
                "duration": duration,
                "extension": dl_info["file_extension"],
            }
        )

    # Try sending as media group (2-10 items)
    if 2 <= len(media_group) <= 10:
        try:
            print(
                f"Attempting to send album {metadata['id']} as media group ({len(media_group)} items)"
            )
            await event.answer_media_group(media_group, disable_notification=True)
            print("Media group sent successfully.")
            return  # Done if media group works
        except Exception as e:
            print(f"Failed to send as media group, sending individually: {e}")
            # Fallback to individual sending below if media group fails

    # Send individually if media group failed or not applicable
    print(
        f"Sending album {metadata['id']} tracks individually ({len(processed_files)} items)"
    )
    for i, item in enumerate(processed_files):
        try:
            print(
                f"USER_DEBUG: Sending individual track {i + 1}/{len(processed_files)} to user_id={user_id} username={username} first_name={first_name}"
            )
            # Use BufferedInputFile for individual sending to avoid potential issues with FSInputFile reuse
            with open(item["path"], "rb") as f:
                audio_data = f.read()
            await event.answer_audio(
                BufferedInputFile(
                    audio_data,
                    filename=f"{clean_filename(item['performer'])} - {clean_filename(item['title'])}{item['extension']}",
                ),
                title=item["title"],
                performer=item["performer"],
                duration=item["duration"],
                disable_notification=True,
            )
            await asyncio.sleep(0.2)  # Small delay between messages
        except Exception as e:
            print(f"Error sending individual track {item['title']}: {e}")
            await event.answer(f"⚠️ Error sending track: {item['title']}")


async def create_and_send_zip(
    event: types.Message, metadata, dl_tracks_info, is_album: bool
):
    """
    Creates a zip archive (single or multipart) and sends it.
    Handles both copying to a path and sending directly to Telegram.
    Places files inside 'Artist - Album [Year]' directory within the zip.
    """
    user_id, username, first_name = get_user_infos(event)
    print(
        f"USER_DEBUG: Creating and sending zip to user_id={user_id} username={username} first_name={first_name} is_album={is_album}"
    )
    # Determine source directory (assuming all tracks are in the same dir)
    if not dl_tracks_info:
        raise ValueError("No downloaded tracks provided for zipping.")

    # Ensure all track dicts have 'download_dir' before accessing it
    source_dir_str = None
    for track in dl_tracks_info:
        if "download_dir" in track:
            source_dir_str = track["download_dir"]
            break
    if not source_dir_str:
        raise ValueError(
            "Could not determine source directory from downloaded tracks info."
        )
    source_dir = Path(source_dir_str)

    cover_path = source_dir / "cover.jpg"  # Standardized cover name

    # Write cover data to the source directory
    try:
        with open(cover_path, "wb") as f:
            f.write(metadata["cover_data"])
    except IOError as e:
        print(f"Error writing cover file {cover_path}: {e}")
        cover_path = None  # Proceed without cover
    except TypeError as e:
        print(
            f"Error with cover data type: {e}. Cover data: {metadata.get('cover_data')}"
        )
        cover_path = None  # Proceed without cover

    # --- Prepare Zip Contents ---
    internal_dir_name = clean_filename(
        f"{metadata['clean_artist']} - {metadata['clean_album_title']} [{metadata['year']}]"
    )
    files_to_zip = {}  # {source_path: destination_in_zip}

    if cover_path and cover_path.exists():
        files_to_zip[str(cover_path)] = f"{internal_dir_name}/cover.jpg"
    else:
        print("Cover file not available or not written, skipping inclusion in zip.")

    # Sort tracks by track number before adding to zip
    try:
        dl_tracks_info.sort(
            key=lambda t: int(t.get("TRACK_NUMBER", "999"))
            if str(t.get("TRACK_NUMBER", "999")).isdigit()
            else 999
        )
    except Exception as sort_e:
        print(
            f"Warning: Could not sort tracks by track number for zipping. Proceeding in potentially unsorted order. Error: {sort_e}"
        )

    for i, track in enumerate(dl_tracks_info):
        track_num_val = track.get("TRACK_NUMBER")
        track_num_str = (
            str(track_num_val).zfill(2)
            if track_num_val and str(track_num_val).isdigit()
            else str(i + 1).zfill(
                2
            )  # Fallback to index if track number missing/invalid
        )
        # Try to get artist/title from API metadata if available, fallback to download info
        api_track = None
        if "tracks_api_data" in metadata:
            api_tracks_by_id = {
                str(t.get("id", "")): t for t in metadata.get("tracks_api_data", [])
            }
            potential_id = Path(track.get("song_path", "")).stem
            api_track = api_tracks_by_id.get(
                track.get("SNG_ID")
            ) or api_tracks_by_id.get(potential_id)

        if api_track:
            title = api_track.get(
                "title", track.get("song_name", f"Track {track_num_str}")
            )
            artists = [c["name"] for c in api_track.get("contributors", [])]
            if not artists:
                artists = [metadata.get("artist", "Unknown Artist")]
            artist_name = ", ".join(artists)
        else:  # Fallback to info from download step
            title = track.get("song_name", f"Track {track_num_str}")
            artist_name = track.get("artist_name", "Unknown Artist")

        file_extension = track.get("file_extension")
        song_path = track.get("song_path")

        if not song_path or not Path(song_path).exists():
            print(
                f"Warning: Missing or non-existent 'song_path' for track {i} ('{title}'), skipping zip inclusion."
            )
            continue

        # Use cleaned names for the file inside the zip
        file_name_inside_zip = clean_filename(
            f"{track_num_str} - {artist_name} - {title}{file_extension}"
        )
        destination_path = f"{internal_dir_name}/{file_name_inside_zip}"
        files_to_zip[song_path] = destination_path
        print(f"[Zip Prep] Mapping {song_path} -> {destination_path}")

    # --- Handle Copy Mode vs Direct Send Mode ---
    # Use album title for hash/naming if it's an album, otherwise track title
    base_name_title = (
        metadata["title"] if is_album else metadata["title"]
    )  # Already correct contextually
    final_title_for_hash = (
        f"{metadata['artist']} - {base_name_title} [{metadata['year']}]"
    )
    caption = get_album_caption(metadata) if is_album else get_track_caption(metadata)

    try:
        # Send cover photo before zip/link
        await event.answer_photo(
            BufferedInputFile(metadata["cover_data"], filename="cover.jpg"),
            caption=caption,
            parse_mode="HTML",
        )
    except Exception as photo_e:
        print(f"Error sending cover photo: {photo_e}")
        # Send caption anyway if photo fails
        await event.answer(
            f"⚠️ Could not send cover image.\n{caption}", parse_mode="HTML"
        )

    if COPY_FILES_PATH and FILE_LINK_TEMPLATE:
        # --- Copy Mode ---
        print("Using Copy Mode for Zip")
        md5_hash = hashlib.md5(final_title_for_hash.encode()).hexdigest()[:8]
        # Use clean names for the zip filename itself
        base_zip_name = f"{unidecode(metadata['clean_artist'])} - {unidecode(metadata['clean_title'])} ({md5_hash})"
        safe_base_name = re.sub(r"[^.a-zA-Z0-9()_-]", "_", base_zip_name)
        final_zip_path = Path(COPY_FILES_PATH) / f"{safe_base_name}.zip"
        final_zip_path.parent.mkdir(parents=True, exist_ok=True)

        print(f"Creating zip file at: {final_zip_path}")
        try:
            with ZipFile(final_zip_path, "w", ZIP_DEFLATED) as zipf:
                for src, dest in files_to_zip.items():
                    if Path(src).exists():
                        zipf.write(src, dest)
                        print(f"  Adding {src} as {dest}")
                    else:
                        print(f"  Warning: Source file not found, skipping: {src}")

            file_link = FILE_LINK_TEMPLATE.format(quote(final_zip_path.name))
            print(
                f"USER_DEBUG: Sending download link to user_id={user_id} username={username} first_name={first_name}"
            )
            await event.answer(f"Download link: {file_link}")
            print(f"Sent download link: {file_link}")

        except Exception as e:
            print(f"Error creating zip in copy mode: {e}")
            await event.answer(f"❌ Error creating zip file: {e}")
            if final_zip_path.exists():
                try:
                    final_zip_path.unlink()
                except OSError:
                    pass

    else:
        # --- Direct Send Mode ---
        print("Using Direct Send Mode for Zip")
        max_size_bytes = (
            48 * 1024 * 1024
        )  # Telegram's limit is 50MB, use 48MB as buffer
        total_size = sum(
            Path(f).stat().st_size for f in files_to_zip if Path(f).exists()
        )
        # Use clean names for the temporary zip file base name
        output_base_path = Path(TMP_DIR) / clean_filename(
            f"{metadata['clean_artist']} - {metadata['clean_title']} [{metadata['year']}]"
        )
        zip_files_created = []

        if not files_to_zip:
            print("No valid files found to add to the zip archive.")
            await event.answer("❌ No files could be added to the zip archive.")
            return  # Exit if nothing to zip

        if total_size <= max_size_bytes:
            # --- Single Zip File ---
            zip_path = Path(f"{output_base_path}.zip")
            print(
                f"Creating single zip: {zip_path} (Total size: {total_size / (1024 * 1024):.2f} MB)"
            )
            try:
                with ZipFile(zip_path, "w", ZIP_DEFLATED) as zipf:
                    for src, dest in files_to_zip.items():
                        if Path(src).exists():
                            zipf.write(src, dest)
                        else:
                            print(f"  Warning: Source file not found, skipping: {src}")
                zip_files_created.append(zip_path)
            except Exception as e:
                print(f"Error creating single zip: {e}")
                await event.answer(f"❌ Error creating zip file: {e}")

        else:
            # --- Multi-part Zip ---
            num_parts = math.ceil(total_size / max_size_bytes)
            print(
                f"Creating multi-part zip ({num_parts} parts estimate, Total size: {total_size / (1024 * 1024):.2f} MB)"
            )
            # Use the sorted list of (src, dest) items from files_to_zip dictionary
            files_remaining = list(files_to_zip.items())
            current_part = 1

            while files_remaining:
                zip_path = Path(f"{output_base_path}_part{current_part}.zip")
                current_zip_size = 0
                files_in_this_part = []
                indices_processed_in_part = set()  # Track indices added to this part

                try:
                    with ZipFile(zip_path, "w", ZIP_DEFLATED) as zipf:
                        # Iterate through remaining files to fill the current part
                        for idx, (src, dest) in enumerate(files_remaining):
                            if not Path(src).exists():
                                print(f"  Skipping non-existent file: {src}")
                                indices_processed_in_part.add(
                                    idx
                                )  # Mark as processed (skipped)
                                continue

                            file_size = Path(src).stat().st_size
                            # Check if file itself is too large (should ideally not happen with audio)
                            if file_size > max_size_bytes:
                                print(
                                    f"Error: File {src} ({file_size / (1024 * 1024):.2f} MB) exceeds max part size {max_size_bytes / (1024 * 1024):.2f} MB. Skipping."
                                )
                                indices_processed_in_part.add(
                                    idx
                                )  # Mark as processed (skipped)
                                continue

                            # Check if adding this file exceeds the limit for *this* part
                            if current_zip_size + file_size <= max_size_bytes:
                                zipf.write(src, dest)
                                current_zip_size += file_size
                                files_in_this_part.append((src, dest))
                                indices_processed_in_part.add(
                                    idx
                                )  # Mark as added to this part
                            else:
                                # Cannot add this file to the current part, leave for the next
                                continue

                    # After iterating through all remaining files for the current part:
                    if files_in_this_part:  # Only save the zip if files were added
                        zip_files_created.append(zip_path)
                        print(
                            f"  Created part {current_part}: {zip_path.name} (Size: {current_zip_size / (1024 * 1024):.2f} MB, {len(files_in_this_part)} files)"
                        )
                    else:
                        # If no files could be added (e.g., next file is too large), delete empty zip
                        print(
                            f"  Warning: Part {current_part} was not created (no files added)."
                        )
                        if zip_path.exists():
                            zip_path.unlink()
                        # Safety break: if no files were added and there are still files remaining, something is wrong
                        if files_remaining and not indices_processed_in_part:
                            print("Error: Stuck in multi-part zip creation. Aborting.")
                            break

                    # Remove the processed files from files_remaining *after* the loop
                    # Iterate backwards to avoid index issues
                    new_files_remaining = []
                    for idx, item in enumerate(files_remaining):
                        if idx not in indices_processed_in_part:
                            new_files_remaining.append(item)
                    files_remaining = new_files_remaining

                    if not files_remaining:
                        break  # All files processed

                    current_part += 1
                    # Safety break: prevent infinite loops if something goes wrong
                    if current_part > num_parts * 1.5 + 1:  # Allow some leeway
                        print(
                            f"Error: Exceeded expected number of parts ({num_parts}). Aborting multi-part zip."
                        )
                        break

                except Exception as e:
                    print(f"Error creating zip part {current_part}: {e}")
                    await event.answer(
                        f"❌ Error creating zip part {current_part}: {e}"
                    )
                    if zip_path.exists():
                        try:
                            zip_path.unlink()
                        except OSError:
                            pass
                    # Stop creating further parts if one fails critically
                    break

            # After loop, check if any files were left unprocessed
            if files_remaining:
                print(
                    f"Warning: {len(files_remaining)} files could not be added to any zip part."
                )
                for src, dest in files_remaining:
                    print(
                        f"  - Unadded: {src} (Size: {Path(src).stat().st_size if Path(src).exists() else 'N/A'})"
                    )

        # --- Send Created Zip Files ---
        if zip_files_created:
            print(f"Sending {len(zip_files_created)} zip file(s)...")
            num_sent = len(zip_files_created)
            for idx, zip_file in enumerate(zip_files_created):
                try:
                    part_caption = (
                        f"Zip Archive (Part {idx + 1}/{num_sent})"
                        if num_sent > 1
                        else "Zip Archive"
                    )
                    print(
                        f"USER_DEBUG: Sending zip file {idx + 1}/{num_sent} to user_id={user_id} username={username} first_name={first_name}"
                    )
                    await event.answer_document(
                        FSInputFile(zip_file),
                        caption=part_caption,
                        disable_notification=True,
                    )
                    print(f"Sent {zip_file.name}")
                    await asyncio.sleep(0.5)  # Small delay between uploads
                except Exception as e:
                    print(f"Error sending zip file {zip_file.name}: {e}")
                    await event.answer(f"❌ Error sending file: {zip_file.name}")
        else:
            print("No zip files were created or finalized to send.")
            # Avoid sending error if copy mode was used (link was sent instead)
            if not (COPY_FILES_PATH and FILE_LINK_TEMPLATE):
                await event.answer("❌ Failed to create any zip files.")

        # --- Cleanup Temporary Zip Files ---
        print("Cleaning up temporary zip files...")
        for zip_file in zip_files_created:
            if zip_file.exists():
                try:
                    zip_file.unlink()
                    print(f"  Removed {zip_file.name}")
                except OSError as e:
                    print(f"  Error removing {zip_file.name}: {e}")


# --- Message Handlers ---


@deezer_router.message(F.text.regexp(TRACK_REGEX))
async def handle_track_link(event: types.Message, real_link=None):
    """Handles Deezer track links using imported utils and functions."""
    user_id, username, first_name = get_user_infos(event)
    print(
        f"USER_DEBUG: Track link request from user_id={user_id} username={username} first_name={first_name}"
    )
    print(f"User {user_id}: Received track link: {event.text}")
    link_to_process = real_link or event.text and event.text.strip() or None
    if not link_to_process:
        await event.answer("Invalid track link format.")
        return
    track_match = re.search(TRACK_REGEX, link_to_process)
    if not track_match:
        await event.answer("Invalid track link format.")
        return
    track_id = track_match.group(2)

    if is_downloading(user_id):
        print(
            f"USER_DEBUG: Rejected download request from user_id={user_id} username={username} first_name={first_name} - already downloading"
        )
        await event.answer(
            __("running_download"), reply_markup=types.ReplyKeyboardRemove()
        )
        return

    add_downloading(user_id)
    tmp_msg = await event.answer(__("downloading"))

    download_dir_to_clean = None  # Store the path to clean up

    try:
        # Download the track
        dl_track_info = await download_track(track_id)
        if not dl_track_info or "song_path" not in dl_track_info:
            raise ValueError("Track download failed or did not return path.")

        # Store the directory path for cleanup *after* successful download
        if "download_dir" in dl_track_info:
            download_dir_to_clean = Path(dl_track_info["download_dir"])

        # Fetch metadata (can happen after download)
        metadata = get_track_metadata_from_api(track_id)

        # Send based on format preference
        if os.environ.get("FORMAT") == "zip":
            await create_and_send_zip(event, metadata, [dl_track_info], is_album=False)
        else:
            await send_track_audio(event, metadata, dl_track_info)

        await tmp_msg.delete()
        # Delete the original user message after successful processing
        try:
            await event.delete()
            print(
                f"USER_DEBUG: Deleted original message from user_id={user_id} username={username} first_name={first_name}"
            )
            print(f"Deleted original message from user {user_id}")
        except Exception as delete_e:
            print(f"Could not delete original message: {delete_e}")

    except Exception as e:
        print(
            f"USER_DEBUG: Error processing track download for user_id={user_id} username={username} first_name={first_name}: {e}"
        )
        print(f"Error processing track {track_id}: {e}")
        print(traceback.format_exc())
        await tmp_msg.delete()
        error_message = str(e) if str(e) else "An unknown error occurred."
        await event.answer(f"{__('download_error')} {error_message}")
    finally:
        remove_downloading(user_id)
        # Cleanup the download directory if it was set
        if download_dir_to_clean and download_dir_to_clean.exists():
            try:
                print(f"Cleaning up download directory: {download_dir_to_clean}")
                await aioshutil.rmtree(download_dir_to_clean)
            except Exception as cleanup_e:
                print(
                    f"Error cleaning up directory {download_dir_to_clean}: {cleanup_e}"
                )


@deezer_router.message(F.text.regexp(ALBUM_REGEX))
async def handle_album_link(event: types.Message, real_link=None):
    """Handles Deezer album links using imported utils and functions."""
    user_id, username, first_name = get_user_infos(event)
    print(
        f"USER_DEBUG: Album link request from user_id={user_id} username={username} first_name={first_name}"
    )
    print(f"User {user_id}: Received album link: {event.text}")
    link_to_process = real_link or event.text and event.text.strip()
    if not link_to_process:
        await event.answer("Invalid album link format.")
        return
    album_match = re.search(ALBUM_REGEX, link_to_process)
    if not album_match:
        await event.answer("Invalid album link format.")
        return
    album_id = album_match.group(2)

    if is_downloading(user_id):
        print(
            f"USER_DEBUG: Rejected album download request from user_id={user_id} username={username} first_name={first_name} - already downloading"
        )
        await event.answer(
            __("running_download"), reply_markup=types.ReplyKeyboardRemove()
        )
        return

    add_downloading(user_id)
    tmp_msg = await event.answer(__("downloading"))
    download_dir_to_clean = None  # Store the path to clean up

    try:
        # Download the album tracks (with internal retries per track)
        dl_tracks_info = await download_album(album_id)
        if not dl_tracks_info:  # Check if *any* tracks were successfully downloaded
            raise ValueError("Album download failed or returned no successful tracks.")

        # Determine the download directory from the first successful track for cleanup
        # All successful tracks should share the same base directory
        if dl_tracks_info and "download_dir" in dl_tracks_info[0]:
            download_dir_to_clean = Path(dl_tracks_info[0]["download_dir"])
        else:
            print(
                "Warning: Could not determine download directory for cleanup from track info."
            )
            # Attempt to construct the expected path as a fallback
            download_dir_to_clean = Path(TMP_DIR) / "deezer" / "album" / str(album_id)

        # Fetch album metadata (can happen after download)
        metadata = get_album_metadata_from_api(album_id)

        # Send based on format preference
        if os.environ.get("FORMAT") == "zip":
            await create_and_send_zip(event, metadata, dl_tracks_info, is_album=True)
        else:
            await send_album_audio(event, metadata, dl_tracks_info)

        await tmp_msg.delete()
        # Delete the original user message after successful processing
        try:
            await event.delete()
            print(
                f"USER_DEBUG: Deleted original message from user_id={user_id} username={username} first_name={first_name}"
            )
            print(f"Deleted original message from user {user_id}")
        except Exception as delete_e:
            print(f"Could not delete original message: {delete_e}")

    except Exception as e:
        print(
            f"USER_DEBUG: Error processing album download for user_id={user_id} username={username} first_name={first_name}: {e}"
        )
        print(f"Error processing album {album_id}: {e}")
        print(traceback.format_exc())
        await tmp_msg.delete()
        error_message = str(e) if str(e) else "An unknown error occurred."
        await event.answer(f"{__('download_error')} {error_message}")
    finally:
        remove_downloading(user_id)
        # Cleanup the download directory if it was set or constructed
        if download_dir_to_clean and download_dir_to_clean.exists():
            try:
                print(f"Cleaning up download directory: {download_dir_to_clean}")
                await aioshutil.rmtree(download_dir_to_clean)
            except Exception as cleanup_e:
                print(
                    f"Error cleaning up directory {download_dir_to_clean}: {cleanup_e}"
                )


@deezer_router.message(
    F.text.regexp(r"^https?://(?:www\.)?(?:deezer|dzr)\.page\.link/.*$")
)
async def handle_shortlink(event: types.Message):
    """Handles Deezer shortlinks by resolving them, with improved SSL handling."""
    user_id, username, first_name = get_user_infos(event)
    print(
        f"USER_DEBUG: Shortlink request from user_id={user_id} username={username} first_name={first_name}"
    )
    print(f"User {user_id}: Received shortlink: {event.text}")
    tmp_msg = await event.answer("🔗 Resolving shortlink...")
    ssl_context = ssl.create_default_context(cafile=certifi.where())  # Use certifi CAs
    connector = aiohttp.TCPConnector(ssl=ssl_context)

    if not event.text:
        await event.answer("Invalid shortlink format.")
        return

    try:
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.head(
                event.text.strip(),
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                real_link = str(response.url).split("?")[0]
                print(f"Resolved shortlink to: {real_link}")

        await tmp_msg.delete()

        if re.match(TRACK_REGEX, real_link):
            await handle_track_link(event, real_link)
        elif re.match(ALBUM_REGEX, real_link):
            await handle_album_link(event, real_link)
        # Add playlist handling here if needed
        # elif re.match(PLAYLIST_REGEX, real_link):
        #     await handle_playlist_link(event, real_link)
        else:
            print("Unknown link type after resolving: " + real_link)
            await event.answer(
                __("download_error") + " Unsupported link type after resolving."
            )

    except aiohttp.ClientConnectorCertificateError as e:
        await tmp_msg.delete()
        print(f"SSL Certificate Verification Error resolving {event.text}: {e}")
        await event.answer(
            f"{__('resolve_error')} {__('ssl_error')}. Please check system certificates or network configuration."
        )
    except asyncio.TimeoutError:
        await tmp_msg.delete()
        print(f"Timeout resolving shortlink {event.text}")
        await event.answer(f"{__('resolve_error')} Timeout while resolving the link.")
    except aiohttp.ClientError as e:
        await tmp_msg.delete()
        print(f"Error resolving shortlink {event.text}: {e}")
        await event.answer(f"{__('resolve_error')} Could not resolve shortlink: {e}")
    except Exception as e:
        await tmp_msg.delete()
        print(f"Unexpected error handling shortlink {event.text}: {e}")
        print(traceback.format_exc())
        await event.answer(f"{__('resolve_error')} Unexpected error: {e}")


# --- Inline Query ---


@deezer_router.inline_query()
async def inline_search_handler(inline_query: InlineQuery):
    """
    Handles inline queries to search Deezer using the imported deezer_search function.
    Runs the synchronous search function in an executor to avoid blocking.
    """
    user_id = inline_query.from_user.id
    username = inline_query.from_user.username
    first_name = inline_query.from_user.first_name
    query = inline_query.query.strip()
    print(
        f"USER_DEBUG: Inline search from user_id={user_id} username={username} first_name={first_name} query='{query}'"
    )

    items = []
    search_type = TYPE_TRACK  # Default search type

    if not query:
        await bot.answer_inline_query(
            inline_query.id,
            results=[],
            cache_time=10,
            switch_pm_text="Type to search Deezer...",
            switch_pm_parameter="inline_help",
        )
        return

    # Determine search type based on prefixes (case-insensitive)
    words = query.split(maxsplit=1)
    first_word = words[0].lower()

    if first_word == "album":
        search_type = TYPE_ALBUM
        query = words[1] if len(words) > 1 else ""
    elif first_word == "track":
        search_type = TYPE_TRACK
        query = words[1] if len(words) > 1 else ""

    if not query:
        await bot.answer_inline_query(inline_query.id, results=[], cache_time=10)
        return

    print(
        f"Inline query: '{inline_query.query}', Parsed: query='{query}', type='{search_type}'"
    )

    try:
        loop = asyncio.get_running_loop()
        search_results = await loop.run_in_executor(
            None, functools.partial(deezer_search, query, search_type)
        )

        for item_data in search_results[:20]:  # Limit results sent
            try:
                result_id = item_data.get("id", None)
                id_type = item_data.get(
                    "id_type", TYPE_TRACK
                )  # Assume track if missing
                thumb_url = item_data.get("img_url", "")  # Use empty string if missing

                if not result_id:
                    print(f"Skipping item due to missing ID: {item_data}")
                    continue

                if id_type == TYPE_ALBUM:
                    title = item_data.get("album", f"Album {result_id}")
                    artist = item_data.get("artist", "Unknown Artist")
                    description = f"Album by {artist}"
                    link = DEEZER_URL + "/album/%s" % quote(str(result_id))
                    inline_result_id = f"album_{result_id}"
                elif id_type == TYPE_TRACK:
                    title = item_data.get("title", f"Track {result_id}")
                    artist = item_data.get("artist", "Unknown Artist")
                    album_title = item_data.get("album", "")
                    description = f"Track by {artist}"
                    if album_title:
                        description += f" - {album_title}"
                    link = DEEZER_URL + "/track/%s" % quote(str(result_id))
                    inline_result_id = f"track_{result_id}"
                else:
                    print(f"Skipping item with unhandled id_type: {id_type}")
                    continue

                article = InlineQueryResultArticle(
                    id=inline_result_id,
                    title=title,
                    description=description,
                    thumb_url=thumb_url if thumb_url else None,  # Pass None if empty
                    input_message_content=InputTextMessageContent(message_text=link),
                )
                items.append(article)
            except Exception as item_e:
                print(
                    f"Error processing individual search result item {item_data.get('id', 'N/A')}: {item_e}"
                )

    # Handle potential DeezerApiException from deezer_search
    except DeezerApiException as e:
        print(f"Deezer API exception during search: {e}")
        print(traceback.format_exc())
        await bot.answer_inline_query(
            inline_query.id,
            results=[],
            cache_time=10,
            switch_pm_text=__("search_error"),
            switch_pm_parameter="search_error_api",
        )
        return
    except Exception as e:
        print(f"Error running or processing deezer_search: {e}")
        print(traceback.format_exc())
        await bot.answer_inline_query(
            inline_query.id,
            results=[],
            cache_time=10,
            switch_pm_text=__("search_error"),
            switch_pm_parameter="search_error_generic",
        )
        return

    try:
        await bot.answer_inline_query(inline_query.id, results=items, cache_time=10)
    except Exception as e:
        # Catch potential Telegram API errors during sending results
        print(f"Error sending inline query results to Telegram: {e}")
        # Optionally, try sending an empty result set as a fallback
        try:
            await bot.answer_inline_query(inline_query.id, results=[], cache_time=10)
        except Exception as fallback_e:
            print(f"Error sending fallback empty inline query results: {fallback_e}")
