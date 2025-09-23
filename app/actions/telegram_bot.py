from telegram import Bot
from dotenv import load_dotenv
from app.dependency import users_collection, posts_collection,tags_collection, client, mongoClient
from app.schemas.users import User
from app.schemas.posts import Post, FILE_TYPE, ResolutionDetails, FileDetails
from bson import ObjectId
from pymongo import UpdateOne
from pymongo.errors import PyMongoError
from google.genai import types
import mimetypes, requests, json, aiohttp, asyncio, magic, os, base64


load_dotenv()
BOT_TOKEN = os.getenv("BOT_API")
TELE_FILE_URL = os.getenv("TELE_FILE_URL")
bot = Bot(BOT_TOKEN)

TELE_FILE_BASE_URL = f"https://api.telegram.org/file/bot{BOT_TOKEN}/"


async def run_tele_api(endpoint, params=None, method='get'):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{endpoint}"
    async with aiohttp.ClientSession() as session:
        if method.lower() == 'get':
            async with session.get(url, params=params) as response:
                data = await response.json()
                return {"ok": response.status == 200, "status": response.status, **data}
        elif method.lower() == 'post':
            async with session.post(url, json=params) as response:
                data = await response.json()
                return {"ok": response.status == 200, "status": response.status, **data}



async def get_file_path(file_id, message_id = None, chat_id = None, resolution = None, user_id = None):
    """Fetch the file path for a given file ID."""
    response = await run_tele_api(f"getFile?file_id={file_id}")
    if response["ok"]:
        file_path = response.get("result", {}).get("file_path", "")
        return file_path
    
    if not (message_id and chat_id and resolution and user_id):
        return None
    # If not ok, re-send message to user to get fresh file_id
    resend = await run_tele_api("forwardMessage", {
        "chat_id": int(chat_id),
        "from_chat_id": int(chat_id),
        "message_id": int(message_id)
    })

    if not resend.get("ok"):
        raise Exception("Failed to resend message to fetch new file_id", resend)
    
    photo_array = resend.get("result", {}).get("photo", [{}])
    new_file_id = ""
    
    if resolution == "high":
        new_file_id = photo_array[-1].get("file_id")
    elif resolution == "medium":
        new_file_id = photo_array[-2].get("file_id") if len(photo_array) > 1 else photo_array[-1].get("file_id")

    response = await run_tele_api(f"getFile?file_id={new_file_id}")
    if response["ok"]:
        new_file_path = response.get("result", {}).get("file_path", "")
    
    await posts_collection.update_one(
        {"user_id": user_id, "message_id": message_id},
        {
            "$set": {
                f"file_details.{resolution}.file_id": new_file_id,
                f"file_details.{resolution}.file_path": new_file_path
            }
        }
    )    
    
    return new_file_path    
    

def serialize_doc(doc):
    doc['_id'] = str(doc['_id'])
    return doc

async def send_msg(text: str, chat_id: str, error: bool = True):
    """Send formatted error message to the chat by telebot.

    Args:
        text (str): Error message you want to send.
        chat_id (str): chat_id of the user.
    """
    if error:
        template = (
            "❌ <b><u>Error</u></b>\n"
            f"<pre>{text}</pre>"
        )
    else:
        template = (
            "✅ <b><u>Success</u></b>\n"
            f"<pre>{text}</pre>"
        )

    response = await run_tele_api(
        endpoint="sendMessage",
        params={
            "chat_id": chat_id,
            "text": template,
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
        await send_msg(text="User already exists", chat_id=chat_id, error=False)

    response = await run_tele_api(
        "getUserProfilePhotos",
        method="post",
        params={"user_id": user_id, "limit": 1}  # just get the first photo
    )

    photos = response.get("result", {}).get("photos", [])

    if photos and photos[0]:  
        # last element is the highest resolution
        file_id = photos[0][-1]["file_id"]
        file_path = await get_file_path(file_id)
    else:
        file_id = None
        file_path = None

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
    await send_msg(text=f"New User {user_data.username} added", chat_id=chat_id, error=False)
    return user_data


async def is_duplicate_post(user_id: str, message_id: str) -> bool:
    """Check if a post already exists for the same user and message."""
    existing_post = await posts_collection.find_one({
        "user_id": user_id,
        "message_id": message_id
    })
    return existing_post is not None


async def extract_photo_details(photo_list: list) -> ResolutionDetails:
    """Extract resolution file details dynamically (1=high, 2=high+medium)."""
    file_details = []

    # Traverse and fetch file paths
    for p in photo_list:
        file_id = p["file_id"]
        file_path = await get_file_path(file_id)
        file_details.append(FileDetails(file_id=file_id, file_path=file_path))

    # Assign based on available count
    if len(file_details) == 1:
        return ResolutionDetails(high=file_details[-1], medium=None)
    else:
        return ResolutionDetails(high=file_details[-1], medium=file_details[-2])

async def save_post(user_id: str, message_id: str, caption: str, file_details: ResolutionDetails, chat_id: str):
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
    await send_msg(text=f"New Post {post_id} added", chat_id=chat_id, error=False)
    return post_id

async def generate_tags(mime_type: str, data: bytes, user_id: str):
    """
    Generate tags for the provided media content.
    
    Args:
        mime_type (str): The MIME type of the media content.
        data (bytes): The media content data.
        user_id (str): The ID of the user submitting the content.

    """
    
    tags = await tags_collection.find(
        {"user_id": user_id},
        {"name": 1, "_id": 0}
    ).to_list(length=None)
    

    tag_names = [tag["name"] for tag in tags]
    text = """
        Analyze the provided image or video and return only a JSON array containing up to 7 unique, high-relevance tags that best describe it for casual user search. 
        Tags must be unrelated to each other, with each representing a distinct and clearly recognizable concept such as visible text, dominant colors, distinct shapes, or obvious objects. 
        Avoid abstract, technical, or overly specific terms unlikely to be used in everyday search. 
        Do not include duplicates, synonyms, or explanations. 
        Output strictly in this format: ['tag1', 'tag2', 'tag3', ...].

    """
    if tag_names:
        text += f""" If the following list contains tags already used to categorize previous images — {', '.join(tag_names)} — identify which of these also apply to the current image and include them in the array. 
        If there are additional key attributes not in the list, add them as new tags. """

    config = types.GenerateContentConfig(
        response_mime_type="application/json"
    )
    
    response  = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=[
            types.Part.from_bytes(
                data=data,
                mime_type=mime_type
            ),
            text
        ],
        config=config
    )
    res_dict = json.loads(response.text)

    # Extract the text from the first candidate's parts
    # text_value = (
    #     res_dict.get("candidates", [{}])[0]
    #     .get("content", {})
    #     .get("parts", [{}])[0]
    #     .get("text", "")
    # )

    # Convert that text (which should be a JSON array string) into a Python list
    # tags_list = json.loads(text_value)
    return res_dict


async def save_tags_and_update_post(tags_list: list[str], user_id: ObjectId, post_id: ObjectId):
    """Save tags to tags_collection with user_id and update the post's tag_names."""

    # Prepare bulk upsert operations for tags
    operations = [
        UpdateOne(
            {"name": tag},  # match tag by name
            {
                "$setOnInsert": {"name": tag},  # only set name if inserting
                "$addToSet": {"user_id": user_id},  # ensures no duplicate user_id
            },
            upsert=True
        )
        for tag in tags_list
    ]


    if not operations:
        return

    # Run both updates concurrently
    await asyncio.gather(
        tags_collection.bulk_write(operations),
        posts_collection.update_one(
            {"_id": post_id},
            {"$addToSet": {"tag_names": {"$each": tags_list}}}
        )
    )
    return True


def fetch_mime_type(b64_data, file_path) -> str:
    """Fetch the MIME type from base64-encoded bytes using python-magic."""
    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type:
        return mime_type
    raw_bytes = base64.b64decode(b64_data)
    mime = magic.Magic(mime=True)
    return mime.from_buffer(raw_bytes)

async def get_image(file_path: str):
    """Return an image from a file path."""
    try:
        url = f"{TELE_FILE_URL}{file_path}"
        response = requests.get(url)
        base64_bytes = base64.b64encode(response.content).decode("utf-8")
        mimetype = fetch_mime_type(base64_bytes, file_path)
        if response.status_code == 200:
            return {"ok":True,"content": response.content, "media_type": mimetype}
        else:
            return {"ok": False, "error": f"{response}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    
async def fetch_post_from_file_path(file_path: str):
    """Fetch post details from the database using the file path."""
    try:
        post = await posts_collection.find_one({
            "$or": [
                {"file_details.high.file_path": file_path},
                {"file_details.medium.file_path": file_path}
            ]
        })
        if post:
            return {"ok": True, "post": post}
        else:
            return {"ok": False, "message": "Post not found"}
    except Exception as e:
        return {"ok": False, "message": str(e)}
    
async def remove_tag_from_post(name: str, file_path: str, user_id: str):
    """Remove a tag from a post and update the tag's user_id list.

    Args:
        name (str): The name of the tag to remove.
        file_path (str): The file path of the post.
        user_id (str): The user ID of the user removing the tag.

    Returns:
        dict: A dictionary indicating the success or failure of the operation.
    """
    async with await mongoClient.start_session() as session:
        try:
            async with session.start_transaction():
                tag_doc = await tags_collection.find_one({"name": name}, session=session)
                if not tag_doc:
                    return {"ok": False, "message": "Tag not found"}

                post = await fetch_post_from_file_path(file_path=file_path)
                if not post.get("ok"):
                    return {"ok": False, "message": "Post not found"}

                # Remove the tag from the post
                await posts_collection.update_one(
                    {"_id": post["post"]["_id"]},
                    {"$pull": {"tag_names": name}},
                    session=session
                )

                # Remove user_id from the tag's user_id list
                await tags_collection.update_one(
                    {"_id": tag_doc["_id"]},
                    {"$pull": {"user_id": user_id}},
                    session=session
                )

            # If all succeeds, transaction commits automatically
            return {"ok": True, "message": "Tag removed from post"}

        except PyMongoError as e:
            # Any error -> transaction rolls back automatically
            return {"ok": False, "message": f"Transaction failed: {str(e)}"}