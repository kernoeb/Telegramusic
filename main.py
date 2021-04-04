import asyncio
import locale
import logging
import os
import re
import shutil

import deezloader
import requests
from aiogram import Bot, Dispatcher, executor, types, exceptions
from aiogram.types import InlineQuery, \
    InputTextMessageContent, InlineQueryResultArticle, InputMediaAudio
from aioify import aioify
from deezloader.deezer_settings import api_track, api_album, api_search_trk, api_playlist
from mutagen.mp3 import MP3

locale.setlocale(locale.LC_TIME, '')

logging.basicConfig(level=logging.INFO)

deezloader_async = aioify(obj=deezloader, name='deezloader_async')

download = deezloader_async.Login(os.environ.get('DEEZER_TOKEN'))
downloading_users = []

bot = Bot(token=os.environ.get('TELEGRAM_TOKEN'))
dp = Dispatcher(bot)


@dp.message_handler(regexp=r"^https?:\/\/(?:www\.)?deezer\.com\/([a-z]*\/)?track\/(\d+)\/?$")
async def get_track(event: types.Message):
    print(event.from_user)
    if event.from_user.id not in downloading_users:
        tmp = event.text
        if tmp[-1] == '/':
            tmp = tmp[:-1]
        tmp_msg = await event.answer("Téléchargement en cours...")
        downloading_users.append(event.from_user.id)
        dl = await download.download_trackdee(tmp, output="tmp", quality="MP3_320", recursive_download=True,
                                              recursive_quality=True, not_interface=False)
        tmp_track = requests.get(api_track % event.text.split('/')[-1]).json()
        tmp_cover = requests.get(tmp_track['album']['cover_xl'], stream=True).raw
        tmp_artist_track = []
        for c in tmp_track['contributors']:
            tmp_artist_track.append(c['name'])
        tmp_date = tmp_track['release_date'].split('-')
        tmp_date = tmp_date[2] + '/' + tmp_date[1] + '/' + tmp_date[0]
        await event.answer_photo(tmp_cover,
                                 caption='<b>Track: {}</b>'
                                         '\n{} - {}\n<a href="{}">Lien de l\'album</a>'
                                         '\n<a href="{}">Lien du track</a>'
                                 .format(
                                     tmp_track['title'], tmp_track['artist']['name'],
                                     tmp_date, tmp_track['album']['link'], tmp_track['link']), parse_mode='HTML'
                                 )
        await event.delete()

        tmp_song = open(dl, 'rb')
        duration = int(MP3(tmp_song).info.length)
        await event.answer_audio(tmp_song,
                                 title=tmp_track['title'],
                                 performer=', '.join(tmp_artist_track),
                                 duration=duration,
                                 disable_notification=True)
        await tmp_msg.delete()
        try:
            shutil.rmtree(os.path.dirname(dl))
        except FileNotFoundError:
            pass
        downloading_users.remove(event.from_user.id)

    else:
        tmp_err_msg = await event.answer("Un téléchargement est déjà en cours!!")
        await event.delete()
        await asyncio.sleep(2)
        await tmp_err_msg.delete()


@dp.message_handler(regexp=r"^https?:\/\/(?:www\.)?deezer\.com\/([a-z]*\/)?album\/(\d+)\/?$")
async def get_album(event: types.Message):
    print(event.from_user)
    if event.from_user.id not in downloading_users:
        tmp = event.text
        if tmp[-1] == '/':
            tmp = tmp[:-1]
        tmp_msg = await event.answer("Téléchargement en cours...")
        downloading_users.append(event.from_user.id)
        dl = await download.download_albumdee(tmp,
                                              output="tmp",
                                              quality="MP3_320",
                                              recursive_download=True,
                                              recursive_quality=True,
                                              not_interface=False)
        album = requests.get(api_album % event.text.split('/')[-1]).json()
        tracks = requests.get(api_album % event.text.split('/')[-1] + '/tracks?limit=100').json()
        tmp_cover = requests.get(album['cover_xl'], stream=True).raw
        tmp_titles = []
        tmp_artists = []
        for track in tracks['data']:
            tmp_titles.append(track['title'])
            tmp_track = requests.get(api_track % track['id']).json()
            tmp_artist_track = []
            for c in tmp_track['contributors']:
                tmp_artist_track.append(c['name'])
            tmp_artists.append(tmp_artist_track)
        tmp_date = album['release_date'].split('-')
        tmp_date = tmp_date[2] + '/' + tmp_date[1] + '/' + tmp_date[0]
        await event.answer_photo(tmp_cover,
                                 caption='<b>Album: {}</b>\n{} - {}\n<a href="{}">Lien de l\'album</a>'.format(
                                     album['title'], album['artist']['name'],
                                     tmp_date, album['link']),
                                 parse_mode='HTML')
        await event.delete()

        try:
            tmp_count = 0
            group_media = []

            for i in dl:
                tmp_song = open(i, 'rb')
                duration = int(MP3(tmp_song).info.length)
                group_media.append(InputMediaAudio(media=tmp_song,
                                                   title=tmp_titles[tmp_count],
                                                   performer=', '.join(tmp_artists[tmp_count]),
                                                   duration=duration))
                tmp_count += 1
            await event.answer_media_group(group_media, disable_notification=True)
        except exceptions.NetworkError:
            tmp_count = 0
            for i in dl:
                tmp_song = open(i, 'rb')
                duration = int(MP3(tmp_song).info.length)
                await event.answer_audio(tmp_song,
                                         title=tmp_titles[tmp_count],
                                         performer=', '.join(tmp_artists[tmp_count]),
                                         duration=duration,
                                         disable_notification=True)
                tmp_count += 1
        await tmp_msg.delete()
        try:
            shutil.rmtree(os.path.dirname(dl[0]))
        except FileNotFoundError:
            pass
        downloading_users.remove(event.from_user.id)

    else:
        tmp_err_msg = await event.answer("Un téléchargement est déjà en cours!!")
        await event.delete()
        await asyncio.sleep(2)
        await tmp_err_msg.delete()


@dp.message_handler(regexp=r"^https?:\/\/(?:www\.)?deezer\.com\/([a-z]*\/)?playlist\/(\d+)\/?$")
async def get_playlist(event: types.Message):
    print(event.from_user)
    if event.from_user.id not in downloading_users:
        tmp = event.text
        if tmp[-1] == '/':
            tmp = tmp[:-1]
        tmp_msg = await event.answer("Téléchargement en cours...")
        downloading_users.append(event.from_user.id)
        dl = await download.download_playlistdee(tmp,
                                                 output="tmp",
                                                 quality="MP3_320",
                                                 recursive_download=True,
                                                 recursive_quality=True,
                                                 not_interface=False)
        album = requests.get(api_playlist % event.text.split('/')[-1]).json()
        tracks = requests.get(api_playlist % event.text.split('/')[-1] + '/tracks?limit=100').json()
        tmp_cover = requests.get(album['picture_xl'], stream=True).raw
        tmp_titles = []
        tmp_artists = []
        for track in tracks['data']:
            tmp_titles.append(track['title'])
            tmp_track = requests.get(api_track % track['id']).json()
            tmp_artist_track = []
            for c in tmp_track['contributors']:
                tmp_artist_track.append(c['name'])
            tmp_artists.append(tmp_artist_track)
        tmp_count = 0
        tmp_date = album['creation_date'].split(' ')[0].split('-')
        tmp_date = tmp_date[2] + '/' + tmp_date[1] + '/' + tmp_date[0]
        await event.answer_photo(tmp_cover,
                                 caption='<b>Playlist: {}</b>\n{} - {}\n<a href="{}">Lien de la playlist</a>'.format(
                                     album['title'], album['creator']['name'], tmp_date, album['link']), parse_mode='HTML')
        await event.delete()
        for i in dl:
            tmp_song = open(i, 'rb')
            duration = int(MP3(tmp_song).info.length)
            await event.answer_audio(tmp_song,
                                     title=tmp_titles[tmp_count],
                                     performer=', '.join(tmp_artists[tmp_count]),
                                     duration=duration,
                                     disable_notification=True)
            tmp_count += 1
        await tmp_msg.delete()
        try:
            shutil.rmtree(os.path.dirname(dl[0]))
        except FileNotFoundError:
            pass
        downloading_users.remove(event.from_user.id)

    else:
        tmp_err_msg = await event.answer("Un téléchargement est déjà en cours!!")
        await event.delete()
        await asyncio.sleep(2)
        await tmp_err_msg.delete()


@dp.message_handler(commands=['help'])
async def test(event: types.Message):
    bot_info = await bot.get_me()
    bot_name = bot_info.first_name.replace("_", "\\_").replace("*", "\\*").replace("[", "\\[").replace("`", "\\`")
    bot_username = bot_info.username.replace("_", "\\_").replace("*", "\\*").replace("[", "\\[").replace("`", "\\`")
    msg = "Salut, je suis *{}*\n".format(bot_name)
    msg += "_Tu peux m'utiliser en inline :_\n"
    msg += "@{} \\(album\\|track\\|artist\\) \\<recherche\\>\n".format(bot_username)
    msg += "Ou envoie un *lien* d'album ou de track Deezer\\!"
    await event.answer(msg, parse_mode="MarkdownV2")


@dp.inline_handler()
async def inline_echo(inline_query: InlineQuery):
    if inline_query.query:
        album = False
        if inline_query.query.startswith('artist '):
            album = True
            tmp_text = 'artist:"{}"'.format(inline_query.query.split('artist ')[1])
            text = api_search_trk % tmp_text
        elif inline_query.query.startswith('track '):
            tmp_text = 'track:"{}"'.format(inline_query.query.split('track ')[1])
            text = api_search_trk % tmp_text
        elif inline_query.query.startswith('album '):
            album = True
            tmp_text = 'album:"{}"'.format(inline_query.query.split('album ')[1])
            text = api_search_trk % tmp_text
        else:
            text = api_search_trk % inline_query.query

        items = []
        try:
            r = requests.get(text).json()
            all_ids = []
            for i in r['data']:
                tmp_url = i['album']['tracklist']
                tmp_id = re.search('/album/(.*)/tracks', tmp_url).group(1)
                if not (album and tmp_id in all_ids):
                    tmp_album = requests.get(api_album % tmp_id).json()
                    all_ids.append(tmp_id)
                    tmp_date = tmp_album['release_date'].split('-')
                    tmp_date = tmp_date[2] + '/' + tmp_date[1] + '/' + tmp_date[0]
                    if album:
                        title = i['album']['title']
                        tmp_input = InputTextMessageContent("https://deezer.com/album/%s" % tmp_id)
                        try:
                            nb = str(len(tmp_album['tracks']['data'])) + ' audio(s)'
                        except KeyError:
                            nb = ''
                        show_txt_album = ' | ' + nb + ' (album)'
                    else:
                        show_txt_album = ''
                        tmp_input = InputTextMessageContent(i['link'])
                        title = i['title']

                    result_id: str = i['id']
                    items.append(InlineQueryResultArticle(
                        id=result_id,
                        title=title,
                        description=i['artist']['name'] + ' | ' + tmp_date + show_txt_album,
                        thumb_url=i['album']['cover_small'],
                        input_message_content=tmp_input,
                    ))
        except KeyError:
            pass
        except AttributeError:
            pass
        await bot.answer_inline_query(inline_query.id, results=items, cache_time=2)


if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
