from telegram import Bot
from dotenv import load_dotenv
import os
import requests
import asyncio

load_dotenv()
BOT_TOKEN = os.getenv("BOT_API")
bot = Bot(BOT_TOKEN)

TELE_FILE_BASE_URL = f"https://api.telegram.org/file/bot{BOT_TOKEN}/"

