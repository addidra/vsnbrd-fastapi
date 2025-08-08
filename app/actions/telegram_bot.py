from telegram import Bot
from dotenv import load_dotenv
import os
import requests
import asyncio
import aiohttp
from app.dependency import users_collection, posts_collection
from app.schemas.users import User
from app.schemas.posts import Post, FILE_TYPE, ResolutionDetails, FileDetails

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

def serialize_doc(doc):
    doc['_id'] = str(doc['_id'])
    return doc

async def send_error_msg(text: str, chat_id: str):
    """Send formatted error message to the chat by telebot.

    Args:
        text (str): Error message you want to send.
        chat_id (str): chat_id of the user.
    """
    error_template = (
        "❌ <b><u>Error</u></b>\n"
        f"<pre>{text}</pre>"
    )

    response = await run_tele_api(
        endpoint="sendMessage",
        params={
            "chat_id": chat_id,
            "text": error_template,
            "parse_mode": "HTML"
        },
        method='post'
    )
    return response

async def handle_new_user(user: dict, chat_id: str):
    """Register a new user if they don't exist."""
    user_id = str(user.get("id"))
    existing_user = await users_collection.find_one({"user_id": user_id})
    if existing_user:
        return None  # Already exists

    # Fetch profile photo details
    response = await run_tele_api(
        "getUserProfilePhotos",
        method="post",
        params={"user_id": user_id}
    )

    file_id = response.get("result", {}).get("photos", [])[0][0].get("file_id", "")
    file_path = await get_file_path(file_id)

    user_data = User(
        username=user.get("username", ""),
        first_name=user.get("first_name", ""),
        last_name=user.get("last_name", ""),
        user_id=user_id,
        chat_id=chat_id,
        profile_image_id=file_id,
        profile_image_path=file_path
    )

    await users_collection.update_one(
        {"user_id": user_id},
        {"$setOnInsert": user_data.model_dump()},
        upsert=True
    )

    print(f"New user added: {user_data.username}")
    return user_data


async def is_duplicate_post(user_id: str, message_id: str) -> bool:
    """Check if a post already exists for the same user and message."""
    existing_post = await posts_collection.find_one({
        "user_id": user_id,
        "message_id": message_id
    })
    return existing_post is not None


async def extract_photo_details(photo_list: list) -> ResolutionDetails:
    """Extract high, medium, low resolution file details."""
    file_id_high = photo_list[-1]["file_id"]
    file_id_medium = photo_list[-2]["file_id"]
    file_id_low = photo_list[-3]["file_id"]

    file_path_high = await get_file_path(file_id_high)
    file_path_medium = await get_file_path(file_id_medium)
    file_path_low = await get_file_path(file_id_low)

    return ResolutionDetails(
        high=FileDetails(file_id=file_id_high, file_path=file_path_high),
        medium=FileDetails(file_id=file_id_medium, file_path=file_path_medium),
        low=FileDetails(file_id=file_id_low, file_path=file_path_low),
    )


async def save_post(user_id: str, message_id: str, caption: str, file_details: ResolutionDetails):
    """Insert a new post and link it to the user."""
    post_data = Post(
        user_id=user_id,
        caption=caption,
        file_details=file_details,
        file_type=FILE_TYPE.IMAGE,
        message_id=message_id,
    )

    post_id = (await posts_collection.insert_one(post_data.model_dump())).inserted_id
    await users_collection.update_one(
        {"user_id": user_id},
        {"$addToSet": {"posts": post_id}}
    )
    print(f"Post saved: {post_id}")
    return post_id
