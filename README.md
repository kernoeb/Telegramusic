<h1 align="center">
  <br>
  Telegramusic
  <br>
</h1>

<h4 align="center">A Telegram bot to download music from Deezer, YouTube and SoundCloud</h4>

<p align="center">
<a href="https://heroku.com/deploy?template=https://github.com/kernoeb/Telegramusic">
  <img src="https://www.herokucdn.com/deploy/button.svg" alt="Deploy">
</a>
</p>

## Disclaimer

:warning: For educational purposes only (or for free music)    
Please don't use this for illegal stuff.  
It's **against Deezer's terms of service**.

## Information

You should probably use Docker way to install the bot, or follow the steps listed in the Dockerfile.  
As indicated in the Dockerfile there's a temporary patch to avoid the "FLAC issue" from the deezer download library,
and another one to allow downloading albums with more than 25 tracks.

## Translations

Your native language is not in the `langs.json` file ? Just make a pull request or pm me !

## Usage

- Get an `arl` cookie on Deezer for `DEEZER_TOKEN` (
  see [this repo](https://github.com/nathom/streamrip/wiki/Finding-Your-Deezer-ARL-Cookie))
- Create a bot on Telegram and grab a token with [Bot Father](https://t.me/botfather) (`TELEGRAM_TOKEN`)
- Activate `Inline Mode` on BotFather for the bot you just created

----

Search for music in `inline mode` :

```
@xxxxxxx_bot (album|track) <search>
```

![image](https://user-images.githubusercontent.com/24623168/141982877-ca7589d4-fe47-4b5a-b751-6d945c21f944.png)

![image](https://user-images.githubusercontent.com/24623168/141983477-b7692d78-134a-4176-98ba-d6388ac4b80b.png)

or send a Deezer / YouTube / SoundCloud link
----

## Configuration

### Docker

#### Prerequisites

- Docker ([Linux installation](https://docs.docker.com/engine/install/ubuntu/)
  and [Linux post-installation steps](https://docs.docker.com/engine/install/linux-postinstall/))
- Docker compose (should be included in the Docker installation)

Create a `token.env` file with the following content, replacing the values with your own tokens :

```
DEEZER_TOKEN=abcdefghijklmnoxxxxxxxxxxxx
TELEGRAM_TOKEN=123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ
BOT_LANG=fr
```

#### Run

```bash
./update.sh
```

> Or manually : `git pull && docker-compose up -d --build`

### Local usage

- Add `DEEZER_TOKEN` and `TELEGRAM_TOKEN` as variable environment
- python3.9 -m pip install -r requirements.txt
- python3.9 main.py

> You should use a `venv` to avoid conflicts with your system python packages

### Compressed files (zip)

You can send a zip file with multiple tracks inside, the bot will send you a zip file with all the tracks downloaded and
the cover.

In the `token.env` file, add the following line :

```
FORMAT=zip
```

If the `zip` file is too big (more than 50MB), the bot will split the zip file into multiple parts.

### Download URL

You can also make the bot move a file to a specific directory and send you the download link.

In the `token.env` file, add the following line :

```
FORMAT=zip
COPY_FILES_PATH=/path/to/your/directory
FILE_LINK_TEMPLATE=https://yourdomain.com/download/{0}
```

The `{0}` will be replaced by the file name.

I recommend using a reverse proxy to serve the files, like Nginx or Caddy.

If you use `Docker`, you can mount a volume to the container and set the `COPY_FILES_PATH` to `/files`, like this :

```yaml
volumes:
  - /path/to/your/directory:/files
```

### Allow FLAC format

If you have Deezer premium, you can allow the bot to download FLAC files by adding the following line in the `token.env`
file :

```
ENABLE_FLAC=1
```

### Troubleshooting

> "Sign in to confirm you’re not a bot. This helps protect our community. Learn more."  
> Please note that your account may be banned if you use this feature.

Add a `cookies.txt` in `./local_resources`.  
To generate this file, please see : https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp.

You don't need to restart the bot, it will automatically reload the cookies when downloading a YouTube video.

### Example configuration

```dotenv
# Global configuration
BOT_LANG=en

# Tokens
DEEZER_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TELEGRAM_TOKEN=1234567890:ABCDEFghijklmnopqrstuvwxyz012345678

# Specific configuration
COPY_FILES_PATH=/files
FILE_LINK_TEMPLATE=https://example.com/dl/{0}
FORMAT=zip
```