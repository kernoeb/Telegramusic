# Telegramusic

A Python bot to download music from :
- Deezer with Deezer API and Deezloader
- YouTube

[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy?template=https://github.com/kernoeb/Telegramusic)

## Disclaimer
:warning: For Educational Purposes Only... or for free music :thinking: !!  
Please don't use this for illegal stuff.  
It's **against Deezer's terms of service**.


## Usage

- Get an `arl` cookie on Deezer for `DEEZER_TOKEN`
- Create a bot on Telegram and grab a token with [Bot Father](https://t.me/botfather) (`TELEGRAM_TOKEN`)

## Configuration

### Docker

token.env
```
DEEZER_TOKEN=abcdefghijklmnoxxxxxxxxxxxx
TELEGRAM_TOKEN=123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ
```

`docker run -it -d --restart=always --env-file token.env --name telegram_music_bot telegram_music_bot`

(Feel free to use a docker-compose)


### Local usage

- Add `DEEZER_TOKEN` and `TELEGRAM_TOKEN` as variable environment
- python3.X -m pip install -r requirements.txt
- python3.X main.py

(You should use a `venv`)
