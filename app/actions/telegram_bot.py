from telegram import Bot
from dotenv import load_dotenv
import os
import requests
import asyncio
import aiohttp

load_dotenv()
BOT_TOKEN = os.getenv("BOT_API")
bot = Bot(BOT_TOKEN)

TELE_FILE_BASE_URL = f"https://api.telegram.org/file/bot{BOT_TOKEN}/"


async def run_tele_api(endpoint, params=None, method='get'):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{endpoint}"
    async with aiohttp.ClientSession() as session:
        if method.lower() == 'get':
            async with session.get(url, params=params) as response:
                if response.status != 200:
                    raise Exception(f"Response status: {response.status}")
                return await response.json()
        elif method.lower() == 'post':
            async with session.post(url, json=params) as response:
                if response.status != 200:
                    raise Exception(f"Response status: {response.status}")
                return await response.json()

        
async def get_file_path(file_id):
    """Fetch the file path for a given file ID."""
    response = await run_tele_api(f"getFile?file_id={file_id}")
    # file_path = response.get("data", {}).get("result", "").get("photos")[0][0].get(file_id,"")
    file_path = response.get("result", {}).get("file_path", "")
    if not file_path:
        raise Exception("File path not found")
    return file_path