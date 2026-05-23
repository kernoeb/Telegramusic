# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Telegramusic is a Telegram bot that downloads music from Deezer, YouTube, and SoundCloud. Users interact via inline search queries or by sending direct links. Built with Python 3.13, aiogram 3, and yt-dlp.

## Running the Bot

### Docker (production)
```bash
./update.sh  # pulls, builds, and starts the container
# or manually: docker compose up -d --build
```

### Local development
```bash
# Set environment variables (or source token.env)
export DEEZER_TOKEN=... TELEGRAM_TOKEN=...
python3.13 -m pip install -r requirements.txt
python3.13 main.py
```

### Linting
```bash
ruff check .
```

No test suite exists.

## Architecture

**Entry point:** `main.py` — registers routers, handles `/start` deep-links (for inline download buttons), starts aiogram polling.

**Bot singleton:** `bot.py` — creates the shared `Bot` and `Dispatcher` instances from `TELEGRAM_TOKEN`.

**Handlers (aiogram Routers):**
- `handlers/deezer.py` — Deezer track/album/shortlink message handlers + inline query search. Manages download lifecycle (retry logic, session refresh, zip creation, Telegram upload). This is by far the largest module.
- `handlers/yt_dlp.py` — YouTube and SoundCloud handlers via yt-dlp. Two separate routers (`youtube_router`, `soundcloud_router`).

**Download core:**
- `dl_utils/deezer_download.py` — Deezer session management (ARL cookie auth), Blowfish decryption of streams, metadata tagging (mutagen), search API. **Forked from [kmille/deezer-downloader](https://github.com/kmille/deezer-downloader)** with local modifications: `get_file_format()` with per-track quality fallback (FLAC → MP3_320 → MP3_128), `deezer_format` passed as parameter instead of relying on the global, `DeezerApiException` vs `RuntimeError` distinction for session auto-refresh, and `ALB_ART_NAME` fetch in `get_song_infos_from_deezer_website`. When syncing with upstream, preserve these differences. Uses global `session` and `license_token` state.
- `dl_utils/deezer_utils.py` — Filename sanitization and audio duration helpers.

**Shared state:** `utils.py` — i18n via `langs.json` (the `__()` function), per-user download lock (`DOWNLOADING_USERS` list), `TMP_DIR` constant.

## Key Design Patterns

- Deezer downloads use Blowfish CBC decryption with a per-song key derived from `SNG_ID`. Every third 2048-byte block is encrypted.
- The Deezer session auto-refreshes after `DEEZER_SESSION_REINIT_THRESHOLD` consecutive failures (default 3).
- Album tracks download concurrently via `asyncio.gather`, each with independent retry loops.
- Synchronous Deezer/yt-dlp calls are wrapped in `asyncio.to_thread` / `run_in_executor` to avoid blocking the event loop.
- Output format is controlled by `FORMAT=zip` env var; when set, tracks are bundled in zip archives (auto-split at 48MB for Telegram's limit).

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_TOKEN` | Yes | Telegram Bot API token |
| `DEEZER_TOKEN` | Yes | Deezer ARL cookie |
| `BOT_LANG` | No | Language code for bot messages (default: `en`, available in `langs.json`) |
| `ENABLE_FLAC` | No | Set to `1` for FLAC downloads (requires Deezer Premium) |
| `FORMAT` | No | Set to `zip` to bundle downloads as zip archives |
| `COPY_FILES_PATH` / `FILE_LINK_TEMPLATE` | No | Serve zips via HTTP instead of Telegram upload |
| `MAX_RETRIES` | No | Download retry count (default: 5) |
| `COOKIES_PATH` | No | Path to `cookies.txt` for yt-dlp (YouTube auth) |
| `YT_PLAYER_CLIENT` | No | Comma-separated yt-dlp player clients |
| `DEEZER_PROXY` | No | HTTPS proxy for Deezer requests |
| `SEND_ALBUM_COVER` | No | Set to `false` to skip sending album art |

## Auxiliary Tools

`arl_fetcher/` — standalone Bun/TypeScript script using Puppeteer to extract a Deezer ARL cookie from email/password login. Run with `bun start` (separate from the bot).

## Debugging

Filter bot logs for user activity:
```bash
docker logs telegramusic 2>/dev/null | grep "USER_DEBUG"
```
