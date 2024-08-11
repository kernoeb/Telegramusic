import json
import os

LANGS_FILE = json.load(open("langs.json"))
LANG = os.environ.get("BOT_LANG")
DOWNLOADING_USERS = []


if LANG is not None:
    print("Lang : " + LANG)
else:
    print("Lang : en")
    LANG = "en"


def __(s):
    return LANGS_FILE[s][LANG]


def is_downloading(user_id):
    return user_id in DOWNLOADING_USERS


def add_downloading(user_id):
    DOWNLOADING_USERS.append(user_id)


def remove_downloading(user_id):
    DOWNLOADING_USERS.remove(user_id)
