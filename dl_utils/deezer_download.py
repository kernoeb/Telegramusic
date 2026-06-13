# From https://github.com/kmille/deezer-downloader/blob/master/deezer_downloader/deezer.py
# MIT License

from __future__ import annotations

import html.parser
import json
import os
import re
import urllib.parse
from binascii import a2b_hex, b2a_hex
from typing import Any

import requests
from Crypto.Cipher import Blowfish
from Crypto.Hash import MD5
from mutagen import MutagenError
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, TALB, TDRC, TIT2, TPOS, TPE1, TPE2, TRCK, PictureType
from mutagen.mp3 import MP3

# BEGIN TYPES
TYPE_TRACK = "track"
TYPE_ALBUM = "album"
TYPE_PLAYLIST = "playlist"
TYPE_ALBUM_TRACK = "album_track"  # used for listing songs of an album
# END TYPES

session = None
license_token = {}
sound_format = ""
USER_AGENT = "Mozilla/5.0 (X11; Linux i686; rv:135.0) Gecko/20100101 Firefox/135.0"


def get_user_data() -> tuple[Any, Any] | None:
    if not session:
        raise DeezerApiException("Error: Deezer session not initialized")

    try:
        user_data = session.get(
            "https://www.deezer.com/ajax/gw-light.php?method=deezer.getUserData&input=3&api_version=1.0&api_token="
        )
        user_data_json = user_data.json()["results"]
        options = user_data_json["USER"]["OPTIONS"]
        return options["license_token"], options["web_sound_quality"]
    except (requests.exceptions.RequestException, KeyError) as e:
        print(f"ERROR: Could not get license token: {e}")
        return None


# quality_config comes from config file
# web_sound_quality is a dict coming from Deezer API and depends on ARL cookie (premium subscription)
def set_default_song_quality(quality_config: str, web_sound_quality: dict):
    global sound_format
    flac_supported = web_sound_quality["lossless"] is True
    if flac_supported:
        if quality_config == "flac":
            sound_format = "FLAC"
        else:
            sound_format = "MP3_320"
    else:
        if quality_config == "flac":
            print(
                "WARNING: flac quality is configured in config file but not supported (no premium subscription?). Falling back to mp3"
            )
        sound_format = "MP3_128"


def get_file_format(s: dict) -> tuple[str, str]:
    if sound_format == "FLAC":
        if int(s.get("FILESIZE_FLAC", 0)) > 0:
            return ".flac", "FLAC"
        elif int(s.get("FILESIZE_MP3_320", 0)) > 0:
            print("Debug: FLAC not available, falling back to MP3_320")
            return ".mp3", "MP3_320"
        else:
            print("Debug: FLAC and MP3_320 not available, falling back to MP3_128")
            return ".mp3", "MP3_128"

    if sound_format == "MP3_320":
        if int(s.get("FILESIZE_MP3_320", 0)) > 0:
            return ".mp3", "MP3_320"
        else:
            print("Debug: MP3_320 not available, falling back to MP3_128")
            return ".mp3", "MP3_128"

    # Default
    return ".mp3", "MP3_128"


# quality is mp3 or flac
def init_deezer_session(proxy_server: str, quality: str) -> None:
    global session, license_token

    deezer_token = os.environ.get("DEEZER_TOKEN")
    if not deezer_token:
        print("Error: DEEZER_TOKEN environment variable not set")
        return

    header = {
        "Pragma": "no-cache",
        "Origin": "https://www.deezer.com",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept": "*/*",
        "Cache-Control": "no-cache",
        "X-Requested-With": "XMLHttpRequest",
        "Connection": "keep-alive",
        "Referer": "https://www.deezer.com/login",
        "DNT": "1",
    }
    session = requests.session()
    session.headers.update(header)
    session.cookies.update({"arl": deezer_token, "comeback": "1"})
    if len(proxy_server.strip()) > 0:
        print(f"Using proxy {proxy_server}")
        session.proxies.update({"https": proxy_server})
    user_data = get_user_data()
    if user_data is None:
        raise Exception("Error: Failed to get user data")
    license_token, web_sound_quality = user_data
    set_default_song_quality(quality, web_sound_quality)


class Deezer404Exception(Exception):
    pass


class Deezer403Exception(Exception):
    pass


class DeezerApiException(Exception):
    pass


class ScriptExtractor(html.parser.HTMLParser):
    """extract <script> tag contents from a html page"""

    def __init__(self):
        html.parser.HTMLParser.__init__(self)
        self.scripts = []
        self.curtag = None

    def handle_starttag(self, tag, attrs):
        self.curtag = tag.lower()

    def handle_data(self, data):
        if self.curtag == "script":
            self.scripts.append(data)

    def handle_endtag(self, tag):
        self.curtag = None


def md5hex(data):
    """return hex string of md5 of the given string"""
    # type(data): bytes
    # returns: bytes
    h = MD5.new()
    h.update(data)
    return b2a_hex(h.digest())


def calcbfkey(songid):
    """Calculate the Blowfish decrypt key for a given songid"""
    key = b"g4el58wc0zvf9na1"
    songid_md5 = md5hex(songid.encode())

    def xor_op(i):
        return chr(songid_md5[i] ^ songid_md5[i + 16] ^ key[i])

    decrypt_key = "".join([xor_op(i) for i in range(16)])
    return decrypt_key


def blowfishDecrypt(data, key):
    iv = a2b_hex("0001020304050607")
    c = Blowfish.new(key.encode(), Blowfish.MODE_CBC, iv)
    return c.decrypt(data)


def decryptfile(fh, key, fo):
    """
    Decrypt data from file <fh>, and write to file <fo>.
    decrypt using blowfish with <key>.
    Only every third 2048 byte block is encrypted.
    """
    blockSize = 2048
    i = 0

    for data in fh.iter_content(blockSize):
        if not data:
            break

        isEncrypted = (i % 3) == 0
        isWholeBlock = len(data) == blockSize

        if isEncrypted and isWholeBlock:
            data = blowfishDecrypt(data, key)

        fo.write(data)
        i += 1


def get_artists(song: dict) -> str:
    """Build the full artist string from the per-track ARTISTS array.

    Deezer's ART_NAME only holds the lead artist, dropping co-main and
    featured artists. The ARTISTS array carries every contributor with a
    ROLE_ID ("0" = main, "5" = featured) and the correct casing, so we
    rebuild "Main1, Main2 feat. Feat1, Feat2" from it. Falls back to
    ART_NAME when the array is missing."""
    artists = song.get("ARTISTS") or []
    main, feat = [], []
    for a in artists:
        name = a.get("ART_NAME")
        if not name:
            continue
        bucket = feat if a.get("ROLE_ID") == "5" else main
        if name not in bucket:
            bucket.append(name)
    result = ", ".join(main)
    if feat:
        result = f"{result} feat. {', '.join(feat)}" if result else ", ".join(feat)
    return result or song.get("ART_NAME", "")


def write_song_metadata(output_file: str, song: dict, is_flac: bool) -> None:
    """Write metadata tags to a downloaded song file using mutagen.
    Ported from upstream kmille/deezer-downloader."""

    def set_metadata(audio, key, value):
        if not value:
            return
        if isinstance(audio, MP3):
            if key == "artist":
                audio["TPE1"] = TPE1(encoding=3, text=value)
            elif key == "albumartist":
                audio["TPE2"] = TPE2(encoding=3, text=value)
            elif key == "title":
                audio["TIT2"] = TIT2(encoding=3, text=value)
            elif key == "album":
                audio["TALB"] = TALB(encoding=3, text=value)
            elif key == "discnumber":
                audio["TPOS"] = TPOS(encoding=3, text=value)
            elif key == "tracknumber":
                audio["TRCK"] = TRCK(encoding=3, text=value)
            elif key == "date":
                audio["TDRC"] = TDRC(encoding=3, text=value)
            elif key == "picture":
                audio["APIC"] = APIC(
                    encoding=3,
                    mime="image/jpeg",
                    type=PictureType.COVER_FRONT,
                    desc="Cover",
                    data=value,
                )
        else:
            if key == "picture":
                pic = Picture()
                pic.mime = "image/jpeg"
                pic.type = PictureType.COVER_FRONT
                pic.desc = "Cover"
                pic.data = value
                audio.add_picture(pic)
            else:
                audio[key] = value

    audio = FLAC(output_file) if is_flac else MP3(output_file)
    set_metadata(audio, "artist", get_artists(song))
    set_metadata(audio, "title", song.get("SNG_TITLE"))
    set_metadata(audio, "album", song.get("ALB_TITLE"))
    set_metadata(audio, "tracknumber", song.get("TRACK_NUMBER"))
    set_metadata(audio, "discnumber", song.get("DISK_NUMBER"))
    if "album_Data" in globals() and album_Data and "PHYSICAL_RELEASE_DATE" in album_Data:
        set_metadata(audio, "date", album_Data.get("PHYSICAL_RELEASE_DATE", "")[:4])
    try:
        set_metadata(audio, "picture", downloadpicture(song["ALB_PICTURE"]))
    except Exception as e:
        print(f"Warning: could not embed album cover: {e}")
    set_metadata(
        audio, "albumartist", song.get("ALB_ART_NAME", song.get("ART_NAME"))
    )
    audio.save()


def downloadpicture(pic_idid):
    if not session:
        raise DeezerApiException("Error: Deezer session not initialized")

    resp = session.get(get_picture_link(pic_idid))
    resp.raise_for_status()
    return resp.content


def get_picture_link(pic_idid):
    setting_domain_img = "https://e-cdns-images.dzcdn.net/images"
    url = setting_domain_img + "/cover/" + pic_idid + "/1200x1200.jpg"
    return url


def get_song_url(track_token: str, format: str) -> str:
    try:
        response = requests.post(
            "https://media.deezer.com/v1/get_url",
            json={
                "license_token": license_token,
                "media": [
                    {
                        "type": "FULL",
                        "formats": [{"cipher": "BF_CBC_STRIPE", "format": format}],
                    }
                ],
                "track_tokens": [
                    track_token,
                ],
            },
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 401:
            raise DeezerApiException(f"Could not retrieve song URL: {e}")
        raise RuntimeError(f"Could not retrieve song URL: {e}")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Could not retrieve song URL: {e}")

    if not data.get("data") or "errors" in data["data"][0]:
        raise RuntimeError(
            f"Could not get download url from API: {data['data'][0]['errors'][0]['message']}"
        )

    if not data["data"][0].get("media"):
        raise RuntimeError(
            "Could not get download url: API returned no media sources (track may not be available in your region)"
        )

    url = data["data"][0]["media"][0]["sources"][0]["url"]
    return url


def download_song(song: dict, deezer_format: str, output_file: str) -> None:
    # downloads and decrypts the song from Deezer. Adds ID3 and art cover
    # song: dict with information of the song (grabbed from Deezer.com)
    # output_file: absolute file name of the output file
    assert type(song) is dict, "song must be a dict"
    assert type(output_file) is str, "output_file must be a str"

    if not session:
        raise DeezerApiException("Error: Deezer session not initialized")

    url = None
    try:
        url = get_song_url(song["TRACK_TOKEN"], deezer_format)
    except DeezerApiException:
        raise  # Session-level error (e.g. expired token), don't try fallback
    except Exception as e:
        print(
            f"Could not download song (https://www.deezer.com/us/track/{song['SNG_ID']}). Maybe it's not available anymore or at least not in your country. {e}"
        )
        if "FALLBACK" in song:
            song = song["FALLBACK"]
            print(
                f"Trying fallback song https://www.deezer.com/us/track/{song['SNG_ID']}"
            )
            try:
                url = get_song_url(song["TRACK_TOKEN"], deezer_format)
            except Exception:
                pass
            else:
                print("Fallback song seems to work")
        else:
            raise

    if url is None:
        raise Exception("Error: Failed to get song URL")

    key = calcbfkey(song["SNG_ID"])
    is_flac = deezer_format == "FLAC"
    try:
        with session.get(url, stream=True) as response:
            response.raise_for_status()
            with open(output_file, "w+b") as fo:
                decryptfile(response, key, fo)
        write_song_metadata(output_file, song, is_flac)
    except MutagenError as e:
        print(f"Warning: Could not write metadata to file: {e}")
    except Exception as e:
        raise DeezerApiException(f"Could not write song to disk: {e}") from e

    print("Download finished: {}".format(output_file))


def get_song_infos_from_deezer_website(search_type, id):
    # search_type: either one of the constants: TYPE_TRACK|TYPE_ALBUM|TYPE_PLAYLIST
    # id: deezer_id of the song/album/playlist (like https://www.deezer.com/de/track/823267272)
    # return: if TYPE_TRACK => song (dict grabbed from the website with information about a song)
    # return: if TYPE_ALBUM|TYPE_PLAYLIST => list of songs
    # raises
    # Deezer404Exception if
    # 1. open playlist https://www.deezer.com/de/playlist/1180748301 and click on song Honey from Moby in a new tab:
    # 2. Deezer gives you a 404: https://www.deezer.com/de/track/68925038
    # Deezer403Exception if we are not logged in

    if not session:
        raise DeezerApiException("Error: Deezer session not initialized")

    url = "https://www.deezer.com/us/{}/{}".format(search_type, id)
    resp = session.get(url)
    print(url)
    if resp.status_code == 404:
        raise Deezer404Exception("ERROR: Got a 404 for {} from Deezer".format(url))
    if "MD5_ORIGIN" not in resp.text:
        raise Deezer403Exception(
            "ERROR: we are not logged in on deezer.com. Please update the cookie"
        )

    parser = ScriptExtractor()
    parser.feed(resp.text)
    parser.close()

    songs = []
    for script in parser.scripts:
        regex = re.search(r'{"DATA":.*', script)
        if regex:
            DZR_APP_STATE = json.loads(regex.group())
            global album_Data
            album_Data = DZR_APP_STATE.get("DATA")
            if (
                DZR_APP_STATE["DATA"]["__TYPE__"] == "playlist"
                or DZR_APP_STATE["DATA"]["__TYPE__"] == "album"
            ):
                # songs if you searched for album/playlist
                for song in DZR_APP_STATE["SONGS"]["data"]:
                    songs.append(song)
            elif DZR_APP_STATE["DATA"]["__TYPE__"] == "song":
                # just one song on that page
                song = DZR_APP_STATE["DATA"]
                # Fetch album artist separately — may differ from track artist on compilations
                alb_id = DZR_APP_STATE["DATA"].get("ALB_ID")
                if alb_id:
                    try:
                        alb_resp = session.get(
                            "https://www.deezer.com/us/{}/{}".format(TYPE_ALBUM, alb_id)
                        )
                        alb_parser = ScriptExtractor()
                        alb_parser.feed(alb_resp.text)
                        alb_parser.close()
                        for alb_script in alb_parser.scripts:
                            alb_regex = re.search(r'{"DATA":.*', alb_script)
                            if alb_regex:
                                alb_data = json.loads(alb_regex.group()).get("DATA", {})
                                song["ALB_ART_NAME"] = alb_data.get(
                                    "ART_NAME", song.get("ART_NAME", "")
                                )
                                break
                    except Exception:
                        pass  # Non-critical, fall back to track artist
                songs.append(song)
    return songs[0] if search_type == TYPE_TRACK else songs


def deezer_search(search, search_type):
    # search: string (What are you looking for?)
    # search_type: either one of the constants: TYPE_TRACK|TYPE_ALBUM|TYPE_ALBUM_TRACK (TYPE_PLAYLIST is not supported)
    # return: list of dicts (keys depend on search_type)

    if not session:
        raise DeezerApiException("Error: Deezer session not initialized")

    if search_type not in [TYPE_TRACK, TYPE_ALBUM, TYPE_ALBUM_TRACK]:
        print("ERROR: search_type is wrong: {}".format(search_type))
        return []
    search = urllib.parse.quote_plus(search)
    try:
        if search_type == TYPE_ALBUM_TRACK:
            data = get_song_infos_from_deezer_website(TYPE_ALBUM, search)
        else:
            resp = session.get(
                "https://api.deezer.com/search/{}?q={}".format(search_type, search)
            )
            resp.raise_for_status()
            data = resp.json()
            data = data["data"]
    except (requests.exceptions.RequestException, KeyError) as e:
        raise DeezerApiException(f"Could not search for track '{search}': {e}") from e
    return_nice = []
    for item in data:
        i = {}
        if search_type == TYPE_ALBUM:
            i["id"] = str(item["id"])
            i["id_type"] = TYPE_ALBUM
            i["album"] = item["title"]
            i["album_id"] = item["id"]
            i["img_url"] = item["cover_small"]
            i["artist"] = item["artist"]["name"]
            i["title"] = ""
            i["preview_url"] = ""

        if search_type == TYPE_TRACK:
            i["id"] = str(item["id"])
            i["id_type"] = TYPE_TRACK
            i["title"] = item["title"]
            i["img_url"] = item["album"]["cover_small"]
            i["album"] = item["album"]["title"]
            i["album_id"] = item["album"]["id"]
            i["artist"] = item["artist"]["name"]
            i["preview_url"] = item["preview"]

        if search_type == TYPE_ALBUM_TRACK:
            i["id"] = str(item["SNG_ID"])
            i["id_type"] = TYPE_TRACK
            i["title"] = item["SNG_TITLE"]
            i["img_url"] = ""  # item['album']['cover_small']
            i["album"] = item["ALB_TITLE"]
            i["album_id"] = item["ALB_ID"]
            i["artist"] = item["ART_NAME"]
            i["preview_url"] = next(
                media["HREF"] for media in item["MEDIA"] if media["TYPE"] == "preview"
            )

        return_nice.append(i)
    return return_nice


def test_deezer_login():
    print("Let's check if the deezer login is still working")
    try:
        song = get_song_infos_from_deezer_website(TYPE_TRACK, "917265")
    except (Deezer403Exception, Deezer404Exception) as msg:
        print(msg)
        print("Login is not working anymore.")
        return False

    if song:
        print("Login is still working.")
        return True
    else:
        print("Login is not working anymore.")
        return False
