# Telegramusic

A Python bot to download music from :
- Deezer with Deezer API and Deezloader
- YouTube

[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy?template=https://github.com/kernoeb/Telegramusic)

## Disclaimer
:warning: For educational purposes only (or for free music)    
Please don't use this for illegal stuff.  
It's **against Deezer's terms of service**.


## Information

You should probably use Docker way to install the bot, or follow the steps listed in the Dockerfile  
You will have a upgraded version of youtube_dl which is really faster, and avoid the "FLAC issue" from the deezer download library.  
These commands can be executed manually or in a script.


## Translations

Your native language is not in the `langs.json` file ? Just make a pull request or pm me !

## Usage

- Get an `arl` cookie on Deezer for `DEEZER_TOKEN` (see [this repo](https://github.com/nathom/streamrip/wiki/Finding-Your-Deezer-ARL-Cookie))
- Create a bot on Telegram and grab a token with [Bot Father](https://t.me/botfather) (`TELEGRAM_TOKEN`) 
- Activate `Inline Mode` on BotFather for the bot you just created


----

Search for music in `inline mode` :

```
@xxxxxxx_bot (album|track|artist) <search>
```

![image](https://user-images.githubusercontent.com/24623168/141982877-ca7589d4-fe47-4b5a-b751-6d945c21f944.png)


![image](https://user-images.githubusercontent.com/24623168/141983477-b7692d78-134a-4176-98ba-d6388ac4b80b.png)


or send a Deezer / YouTube link

----

## Configuration

### Docker

token.env
```
DEEZER_TOKEN=abcdefghijklmnoxxxxxxxxxxxx
TELEGRAM_TOKEN=123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ
BOT_LANG=fr
```

`docker run -it -d --restart=always --env-file token.env --name telegram_music_bot telegram_music_bot`

-----

**docker-compose.yml**  
(example)

```
services:
  worker:
    build: .
    restart: always
    env_file:
      - token.env     
 ```

### Local usage

- Add `DEEZER_TOKEN` and `TELEGRAM_TOKEN` as variable environment
- python3.X -m pip install -r requirements.txt
- python3.X main.py

(You should use a `venv`)
