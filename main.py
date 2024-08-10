import asyncio
import io
import json
import locale
import logging
import os
import re
import aioshutil
import sys
import traceback
from urllib.parse import quote

import deezloader.deezloader
import requests
from PIL import Image
from aiogram import Bot, Dispatcher, types
from aiogram import F
from aiogram.filters import CommandStart
from aiogram.types import BufferedInputFile, FSInputFile
from aiogram.types import InlineQuery, InputTextMessageContent, InlineQueryResultArticle, InputMediaAudio
from aioify import aioify
from mutagen.id3 import ID3, APIC, error
from mutagen.mp3 import MP3
from yt_dlp import YoutubeDL

if sys.version_info.major != 3 or sys.version_info.minor != 9 or sys.version_info.micro != 18:
    print("Python 3.9.18 is required")
    sys.exit(1)

locale.setlocale(locale.LC_TIME, '')

DEEZER_URL = "https://deezer.com"
API_URL = "https://api.deezer.com"

API_TRACK = API_URL + "/track/%s"
API_ALBUM = API_URL + "/album/%s"
API_SEARCH_TRK = API_URL + "/search/track/?q=%s"
API_PLAYLIST = API_URL + "/playlist/%s"

DEFAULT_QUALITY = "MP3_320"


# define Python user-defined exceptions
class TelegramNetworkError(Exception):
    "Raised when there is a Telegram network related error"
    pass


try:
    os.mkdir("tmp")
except FileExistsError:
    pass

try:
    os.mkdir("tmp/yt/")
except FileExistsError:
    pass

logging.basicConfig(level=logging.INFO)

deezloader_async = aioify(obj=deezloader.deezloader, name='deezloader_async')

download = deezloader_async.DeeLogin(os.environ.get('DEEZER_TOKEN'))
downloading_users = []

bot = Bot(token=os.environ.get('TELEGRAM_TOKEN'))
dp = Dispatcher()

LANGS_FILE = json.load(open('langs.json'))
LANG = os.environ.get('BOT_LANG')

if LANG is not None:
    print("Lang : " + LANG)
else:
    print("Lang : en")
    LANG = 'en'


def __(s):
    return LANGS_FILE[s][LANG]


def crop_center(pil_img, crop_width, crop_height):
    img_width, img_height = pil_img.size
    return pil_img.crop(((img_width - crop_width) // 2, (img_height - crop_height) // 2, (img_width + crop_width) // 2,
                         (img_height + crop_height) // 2))


TRACK_REGEX = r"https?://(?:www\.)?deezer\.com/([a-z]*/)?track/(\d+)/?$"
ALBUM_REGEX = r"https?://(?:www\.)?deezer\.com/([a-z]*/)?album/(\d+)/?$"
PLAYLIST_REGEX = r"https?://(?:www\.)?deezer\.com/([a-z]*/)?playlist/(\d+)/?$"


@dp.message(F.text.regexp(r"(?:http?s?:\/\/)?(?:www.)?(?:m.)?(?:music.)?youtu(?:\.?be)(?:\.com)?(?:("
                          r"?:\w*.?:\/\/)?\w*.?\w*-?.?\w*\/(?:embed|e|v|watch|.*\/)?\??(?:feature=\w*\.?\w*)?&?("
                          r"?:v=)?\/?)([\w\d_-]{11})(?:\S+)?"))
async def get_youtube_audio(event: types.Message):
    print(event.from_user)
    if event.from_user.id not in downloading_users:
        tmp_msg = await event.answer(__('downloading'))
        downloading_users.append(event.from_user.id)
        try:
            ydl_opts = {
                'outtmpl': 'tmp/yt/%(id)s.%(ext)s',
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '320'
                }],
            }

            # if cookies.txt exists, use it
            if os.environ.get('COOKIES_PATH') is not None and os.path.exists(os.environ.get('COOKIES_PATH')):
                print('Using cookies')
                ydl_opts['cookiefile'] = os.environ.get('COOKIES_PATH')

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
                    upload_date = upload_date[6:8] + "/" + upload_date[4:6] + "/" + upload_date[0:4]
            except:
                pass

            # Send cover
            image_bytes = io.BytesIO(content)
            await event.answer_photo(BufferedInputFile(image_bytes.read(), filename="cover.jpg"),
                                     caption=('<b>Track: {}</b>'
                                              '\n{} - {}\n\n<a href="{}">' + __('track_link') + '</a>')
                                     .format(
                                         dict_info['title'],
                                         dict_info["uploader"], upload_date,
                                         "https://youtu.be/" + dict_info["id"]
                                     ),
                                     parse_mode='HTML'
                                     )

            # Delete user message
            await event.delete()

            location = "tmp/yt/" + dict_info["id"] + '.mp3'

            # TAG audio
            audio = MP3(location, ID3=ID3)
            try:
                audio.add_tags()
            except error:
                pass
            audio.tags.add(APIC(mime='image/jpeg', type=3, desc=u'Cover', data=image_bytes.read()))
            audio.save()

            # Create thumb
            roi_img = crop_center(Image.open(image_bytes), 80, 80)
            img_byte_arr = io.BytesIO()
            if roi_img.mode in ("RGBA", "P"):
                roi_img = roi_img.convert("RGB")
            roi_img.save(img_byte_arr, format='jpeg')

            # Send audio
            print(dict_info)
            await event.answer_audio(FSInputFile(location),
                                     title=dict_info["title"],
                                     performer=dict_info["uploader"],
                                     thumbnail=BufferedInputFile(img_byte_arr.getvalue(), filename="thumb.jpg"),
                                     disable_notification=True)
            try:
                await aioshutil.rmtree(os.path.dirname(location))
            except FileNotFoundError:
                pass
        except Exception as e:
            traceback.print_exc()
            await event.answer(__('download_error') + ' ' + str(e))
        finally:
            await tmp_msg.delete()
            try:
                downloading_users.remove(event.from_user.id)
            except ValueError:
                pass
    else:
        tmp_err_msg = await event.answer(__('running_download'))
        await event.delete()
        await asyncio.sleep(2)
        await tmp_err_msg.delete()


@dp.message(F.text.regexp(TRACK_REGEX))
async def get_track(event: types.Message, real_link=None):
    print(event.from_user)
    if real_link is None:
        copy_text = event.text
    else:
        copy_text = real_link
    while copy_text.startswith('h') is False:
        copy_text = copy_text[1:]
    copy_text = copy_text.strip()

    if event.from_user.id not in downloading_users:
        tmp = copy_text
        if tmp[-1] == '/':
            tmp = tmp[:-1]
        tmp_msg = await event.answer(__('downloading'))
        downloading_users.append(event.from_user.id)
        try:
            try:
                dl = await download.download_trackdee(tmp, output_dir="tmp", quality_download=DEFAULT_QUALITY,
                                                      recursive_download=True, recursive_quality=True,
                                                      not_interface=False)
            except:
                # Let's try again...
                await asyncio.sleep(1)
                dl = await download.download_trackdee(tmp, output_dir="tmp", quality_download=DEFAULT_QUALITY,
                                                      recursive_download=True, recursive_quality=True,
                                                      not_interface=False)
            tmp_track_json = requests.get(API_TRACK % quote(str(copy_text.split('/')[-1]))).json()
            tmp_track_json_cover_url = tmp_track_json['album']['cover_xl']
            if tmp_track_json_cover_url is None:  # If cover is not available, use md5_image
                tmp_track_json_cover_url = f"https://e-cdns-images.dzcdn.net/images" \
                                           f"/cover/{tmp_track_json['album']['md5_image']}/1200x0-000000-100-0-0.jpg"

            tmp_cover = requests.get(tmp_track_json_cover_url, stream=True).raw
            tmp_artist_track = []
            for c in tmp_track_json['contributors']:
                tmp_artist_track.append(c['name'])
            tmp_date = tmp_track_json['release_date'].split('-')
            tmp_date = tmp_date[2] + '/' + tmp_date[1] + '/' + tmp_date[0]
            year = tmp_date.split('/')[2]
            clean_title = re.sub(r'[\\/*?:"<>|]', '', tmp_track_json['title'])
            clean_artist = re.sub(r'[\\/*?:"<>|]', '', tmp_track_json['artist']['name'])
            final_title = clean_artist + ' - ' + clean_title + ' (' + year + ')'

            if os.environ.get('FORMAT') == 'zip':
                songs_parent_dir = os.path.dirname(dl.song_path)
                with open(os.path.join(songs_parent_dir, 'cover.jpg'), 'wb') as cover:
                    cover.write(tmp_cover.read())
                await aioshutil.make_archive('tmp/' + final_title, 'zip', songs_parent_dir)

                await event.answer_document(FSInputFile('tmp/' + final_title + '.zip'),
                                            caption=('<b>Track: {}</b>'
                                                     '\n{} - {}\n<a href="{}">' + __('album_link')
                                                     + '</a>\n<a href="{}">' + __('track_link') + '</a>')
                                            .format(
                                                tmp_track_json['title'], tmp_track_json['artist']['name'],
                                                tmp_date, tmp_track_json['album']['link'], tmp_track_json['link']
                                            ),
                                            parse_mode='HTML')

                # Delete user message
                await event.delete()
            else:
                await event.answer_photo(BufferedInputFile(tmp_cover.read(), filename='cover.jpg'),
                                         caption=('<b>Track: {}</b>'
                                                  '\n{} - {}\n<a href="{}">' + __('album_link')
                                                  + '</a>\n<a href="{}">' + __('track_link') + '</a>')
                                         .format(
                                             tmp_track_json['title'], tmp_track_json['artist']['name'],
                                             tmp_date, tmp_track_json['album']['link'], tmp_track_json['link']),
                                         parse_mode='HTML'
                                         )

                # Delete user message
                await event.delete()

                tmp_song = open(dl.song_path, 'rb')
                duration = int(MP3(tmp_song).info.length)
                tmp_song.seek(0)

                await event.answer_audio(FSInputFile(dl.song_path),
                                         title=tmp_track_json['title'],
                                         performer=', '.join(tmp_artist_track),
                                         duration=duration,
                                         disable_notification=True)

                tmp_song.close()

            await tmp_msg.delete()
            try:
                await aioshutil.rmtree(os.path.dirname(dl.song_path))
            except FileNotFoundError:
                pass
            if os.path.exists('tmp/' + final_title + '.zip'):
                os.remove('tmp/' + final_title + '.zip')
        except Exception as e:
            await tmp_msg.delete()
            await event.answer(__('download_error') + ' ' + str(e))
        finally:
            try:
                downloading_users.remove(event.from_user.id)
            except ValueError:
                pass
    else:
        tmp_err_msg = await event.answer(__('running_download'))
        await event.delete()
        await asyncio.sleep(2)
        await tmp_err_msg.delete()


@dp.message(F.text.regexp(ALBUM_REGEX))
async def get_album(event: types.Message, real_link=None):
    print(event.from_user)
    if real_link is None:
        copy_text = event.text
    else:
        copy_text = real_link
    while copy_text.startswith('h') is False:
        copy_text = copy_text[1:]
    copy_text = copy_text.strip()

    if event.from_user.id not in downloading_users:
        tmp = copy_text
        if tmp[-1] == '/':
            tmp = tmp[:-1]
        tmp_msg = await event.answer(__('downloading'))
        downloading_users.append(event.from_user.id)
        try:
            try:
                dl = await download.download_albumdee(tmp,
                                                      output_dir="tmp",
                                                      quality_download=DEFAULT_QUALITY,
                                                      recursive_download=True,
                                                      recursive_quality=True,
                                                      not_interface=False)
            except:
                # Let's try again...
                await asyncio.sleep(1)
                dl = await download.download_albumdee(tmp,
                                                      output_dir="tmp",
                                                      quality_download=DEFAULT_QUALITY,
                                                      recursive_download=True,
                                                      recursive_quality=True,
                                                      not_interface=False)
            album = requests.get(API_ALBUM % quote(str(copy_text.split('/')[-1]))).json()
            tracks = requests.get(API_ALBUM % quote(str(copy_text.split('/')[-1])) + '/tracks?limit=100').json()
            tmp_track_json_cover_url = album['cover_xl']
            if tmp_track_json_cover_url is None:  # If cover is not available, use md5_image
                tmp_track_json_cover_url = f"https://e-cdns-images.dzcdn.net/images" \
                                           f"/cover/{album['md5_image']}/1200x0-000000-100-0-0.jpg"
            tmp_cover = requests.get(tmp_track_json_cover_url, stream=True).raw
            tmp_titles = []
            tmp_artists = []
            for track in tracks['data']:
                tmp_titles.append(track['title'])
                tmp_track_json = requests.get(API_TRACK % quote(str(track['id']))).json()
                tmp_artist_track = []
                for c in tmp_track_json['contributors']:
                    tmp_artist_track.append(c['name'])
                tmp_artists.append(tmp_artist_track)
            tmp_date = album['release_date'].split('-')
            tmp_date = tmp_date[2] + '/' + tmp_date[1] + '/' + tmp_date[0]
            year = tmp_date.split('/')[2]
            clean_title = re.sub(r'[\\/*?:"<>|]', '', album['title'])
            clean_artist = re.sub(r'[\\/*?:"<>|]', '', album['artist']['name'])
            final_title = clean_artist + ' - ' + clean_title + ' (' + year + ')'

            if os.environ.get('FORMAT') == 'zip':
                songs_parent_dir = os.path.dirname(dl.tracks[0].song_path)
                with open(os.path.join(songs_parent_dir, 'cover.jpg'), 'wb') as cover:
                    cover.write(tmp_cover.read())
                await aioshutil.make_archive('tmp/' + final_title, 'zip', songs_parent_dir)

                await event.answer_document(FSInputFile('tmp/' + final_title + '.zip'),
                                            caption=('<b>Album: {}</b>\n{} - {}\n<a href="{}">' + __(
                                                'album_link') + '</a>')
                                            .format(
                                                album['title'], album['artist']['name'],
                                                tmp_date, album['link']
                                            ),
                                            parse_mode='HTML')

                # Delete user message
                await event.delete()
            else:
                await event.answer_photo(BufferedInputFile(tmp_cover.read(), filename='cover.jpg'),
                                         caption=('<b>Album: {}</b>\n{} - {}\n<a href="{}">' + __(
                                             'album_link') + '</a>')
                                         .format(
                                             album['title'], album['artist']['name'],
                                             tmp_date, album['link']
                                         ),
                                         parse_mode='HTML')

                # Delete user message
                await event.delete()

                try:
                    tmp_count = 0
                    group_media = []

                    if len(dl.tracks) < 2 or len(dl.tracks) > 10:
                        raise TelegramNetworkError

                    all_tracks = []
                    for i in dl.tracks:
                        tmp_song = open(i.song_path, 'rb')
                        all_tracks.append(tmp_song)

                    for track in all_tracks:
                        duration = int(MP3(track).info.length)
                        track.seek(0)
                        # Expected type 'Union[str, InputFile]', got 'BinaryIO' instead
                        group_media.append(InputMediaAudio(media=BufferedInputFile(
                            track.read(),
                            filename=tmp_titles[tmp_count] + '.mp3'
                        ),
                            title=tmp_titles[tmp_count],
                            performer=', '.join(tmp_artists[tmp_count]), duration=duration))
                        tmp_count += 1
                    await event.answer_media_group(group_media, disable_notification=True)

                    for track in all_tracks:
                        track.close()
                except TelegramNetworkError:
                    tmp_count = 0

                    all_tracks = []
                    for i in dl.tracks:
                        tmp_song = open(i.song_path, 'rb')
                        all_tracks.append(tmp_song)

                    for track in all_tracks:
                        duration = int(MP3(track).info.length)
                        track.seek(0)
                        await event.answer_audio(
                            BufferedInputFile(track.read(), filename=tmp_titles[tmp_count] + '.mp3'),
                            title=tmp_titles[tmp_count],
                            performer=', '.join(tmp_artists[tmp_count]),
                            duration=duration,
                            disable_notification=True)
                        tmp_count += 1

                    for track in all_tracks:
                        track.close()

            await tmp_msg.delete()
            try:
                await aioshutil.rmtree(os.path.dirname(dl.tracks[0].song_path))
            except FileNotFoundError:
                pass
            if os.path.exists('tmp/' + final_title + '.zip'):
                os.remove('tmp/' + final_title + '.zip')
        except Exception as e:
            await tmp_msg.delete()
            await event.answer(__('download_error') + ' ' + str(e))
        finally:
            try:
                downloading_users.remove(event.from_user.id)
            except ValueError:
                pass

    else:
        tmp_err_msg = await event.answer(__('running_download'))
        await event.delete()
        await asyncio.sleep(2)
        await tmp_err_msg.delete()


@dp.message(F.text.regexp(r"^https?://(?:www\.)?deezer.page.link/.*$"))
async def get_shortlink(event: types.Message):
    r = requests.get(event.text)
    real_link = r.url.split('?')[0]
    if re.match(TRACK_REGEX, real_link):
        await get_track(event, real_link)
    elif re.match(ALBUM_REGEX, real_link):
        await get_album(event, real_link)
    else:
        await event.answer(__('download_error'))


@dp.message(CommandStart())
async def help_start(event: types.Message):
    bot_info = await bot.get_me()
    bot_name = bot_info.first_name.replace("_", "\\_").replace("*", "\\*").replace("[", "\\[").replace("`", "\\`")
    bot_username = bot_info.username.replace("_", "\\_").replace("*", "\\*").replace("[", "\\[").replace("`", "\\`")
    msg = "Hey, I'm *{}*\n".format(bot_name)
    msg += "_You can use me in inline mode :_\n"
    msg += "@{} \\(album\\|track\\|artist\\) \\<search\\>\n".format(bot_username)
    msg += "Or just send an *Deezer* album or track *link* \\!"
    await event.answer(msg, parse_mode="MarkdownV2")


@dp.inline_query()
async def inline_echo(inline_query: InlineQuery):
    items = []
    print(inline_query)
    if inline_query.query:
        album = False
        if inline_query.query.startswith('artist '):
            album = True
            tmp_text = 'artist:"{}"'.format(inline_query.query.split('artist ')[1])
            text = API_SEARCH_TRK % quote(str(tmp_text))
        elif inline_query.query.startswith('track '):
            tmp_text = 'track:"{}"'.format(inline_query.query.split('track ')[1])
            text = API_SEARCH_TRK % quote(str(tmp_text))
        elif inline_query.query.startswith('album '):
            album = True
            tmp_text = 'album:"{}"'.format(inline_query.query.split('album ')[1])
            text = API_SEARCH_TRK % quote(str(tmp_text))
        else:
            text = API_SEARCH_TRK % quote(str(inline_query.query))

        try:
            print(text)
            r = requests.get(text).json()
            print(r)
            all_ids = []
            for i in r['data']:
                tmp_url = i['album']['tracklist']
                tmp_id = re.search('/album/(.*)/tracks', tmp_url).group(1)
                if not (album and tmp_id in all_ids):
                    tmp_album = requests.get(API_ALBUM % quote(str(tmp_id))).json()
                    print(tmp_album)
                    all_ids.append(tmp_id)
                    tmp_date = tmp_album['release_date'].split('-')
                    tmp_date = tmp_date[2] + '/' + tmp_date[1] + '/' + tmp_date[0]
                    if album:
                        title = i['album']['title']
                        tmp_input = InputTextMessageContent(message_text=DEEZER_URL + "/album/%s" % quote(str(tmp_id)))
                        try:
                            nb = str(len(tmp_album['tracks']['data'])) + ' audio(s)'
                        except KeyError:
                            nb = ''
                        show_txt_album = ' | ' + nb + ' (album)'
                    else:
                        show_txt_album = ''
                        tmp_input = InputTextMessageContent(message_text=i['link'])
                        title = i['title']

                    result_id = str(i['id'])
                    items.append(InlineQueryResultArticle(
                        id=result_id,
                        title=title,
                        description=i['artist']['name'] + ' | ' + tmp_date + show_txt_album,
                        thumb_url=i['album']['cover_small'],
                        input_message_content=tmp_input,
                    ))
        except KeyError as e:
            print(e)
            pass
        except AttributeError as e:
            print(e)
            pass
    await bot.answer_inline_query(inline_query.id, results=items, cache_time=100)


async def main() -> None:
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
