from telegram import Bot
from dotenv import load_dotenv
from app.dependency import users_collection, posts_collection,tags_collection, client, mongoClient
from app.schemas.users import User, Membership, PreviousPlan, PlanType
from app.schemas.posts import Post, FILE_TYPE, ResolutionDetails, FileDetails
from bson import ObjectId
from pymongo import UpdateOne
from pymongo.errors import PyMongoError
from google.genai import types
import mimetypes, requests, json, aiohttp, asyncio, magic, os, base64
from datetime import datetime, timedelta

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
    print(f"Handle New user 👤 User ID: {user_id}")
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
    
    tag_names = await tags_collection.distinct("name", {"user_id": user_id})

    text = """
        Analyze the provided image or video and return only a JSON array containing up to 7 unique, high-relevance tags that best describe it for casual user search.
        Tags must be unrelated to each other, with each representing a distinct and clearly recognizable concept such as visible text, dominant colors, distinct shapes, or obvious objects.
        If the image shows a well-known character, brand, landmark, or object (e.g., Batman, Eiffel Tower, Nike logo), include that as the tag instead of describing its attributes.
        Avoid abstract, technical, or overly specific terms unlikely to be used in everyday search.
        Each tag should be a single word or a concise phrase (no more than 3 words).
        Ensure tags are in English, lowercase, and free of special characters or punctuation.
        Do not include duplicates, synonyms, or explanations.
        Output strictly in this format: ['tag1', 'tag2', 'tag3', ...]
    """
    if tag_names:
        text += f""" 
        You are given a list of previously used tags: — {', '.join(tag_names)} — 
        Look at the current image and compare it with the provided list of tags.
        If some of these tags are relevant for the current image, include at max 3 of them.
        Any remaining tags you generate should be new and unique (not from the list).
        Ensure all tags accurately describe the current image’s attributes. """

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

from fastembed import TextEmbedding
from concurrent.futures import ThreadPoolExecutor
from pymongo import UpdateOne
from typing import List
from datetime import datetime
import asyncio

# Initialize once (global)
embedding_model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
executor = ThreadPoolExecutor(max_workers=4)

async def generate_embeddings_async(texts: List[str]) -> List[List[float]]:
    """Generate embeddings asynchronously using FastEmbed"""
    loop = asyncio.get_event_loop()
    
    # Run in thread pool to avoid blocking event loop
    embeddings = await loop.run_in_executor(
        executor,
        lambda: list(embedding_model.embed(texts))
    )
    
    return embeddings

async def save_tags_and_update_post(tags_list: list[str], user_id: str, post_id: ObjectId):
    """Save tags with embeddings using upsert to avoid race conditions."""
    tags_list = list(set(tags_list))  # Remove duplicates
    
    if not tags_list:
        return False
    
    # Generate embeddings for all tags (batch is more efficient)
    embeddings = await generate_embeddings_async(tags_list)
    
    # Create upsert operations
    operations = []
    for tag_name, embedding in zip(tags_list, embeddings):
        operations.append(
            UpdateOne(
                {"name": tag_name, "user_id": user_id},  # Match criteria
                {
                    "$setOnInsert": {  # Only set these fields if inserting
                        "name": tag_name,
                        "user_id": user_id,
                        "embedding": embedding.tolist(),  # Convert to list for MongoDB
                        "created_at": datetime.now()
                    }
                },
                upsert=True  # Insert if doesn't exist
            )
        )
    
    # Run both operations concurrently
    try:
        await asyncio.gather(
            tags_collection.bulk_write(operations, ordered=False),
            posts_collection.update_one(
                {"_id": post_id},
                {"$addToSet": {"tag_names": {"$each": tags_list}}}
            )
        )
        return True
    except Exception as e:
        print(f"Error saving tags: {e}")
        return False

# def run():
#     return save_tags_and_update_post(tags_list=["cake", "dessert", "sweet"], user_id="1892630283", post_id=ObjectId("656f1f4e8f1b2c3d4e5f6789"))


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
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            base64_bytes = base64.b64encode(response.content).decode("utf-8")
            mimetype = fetch_mime_type(base64_bytes, file_path)
            return {
                "ok": True,
                "content": response.content,
                "media_type": mimetype
            }
        else:
            return {"ok": False, "error": f"HTTP {response.status_code}"}
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
    
from pymongo.errors import PyMongoError
from bson import ObjectId

async def remove_tag_from_post(name: str, file_path: str, user_id: str):
    """Remove a tag from a post and update the tag's user_id list.

    Args:
        name (str): The name of the tag to remove.
        file_path (str): The file path of the post.
        user_id (str): The user ID of the user removing the tag.

    Returns:
        dict: A dictionary indicating the success or failure of the operation.
    """
    session = await mongoClient.start_session()
    try:
        await session.start_transaction()
        tag_doc = await tags_collection.find_one({"name": name}, session=session)
        if not tag_doc:
            await session.abort_transaction()
            return {"ok": False, "message": "Tag not found"}

        post_res = await fetch_post_from_file_path(file_path=file_path)
        if not post_res.get("ok"):
            await session.abort_transaction()
            return {"ok": False, "message": "Post not found"}

        post = post_res["post"]
        await posts_collection.update_one(
            {"_id": post["_id"]},
            {"$pull": {"tag_names": name}},
            session=session
        )
        # Check is any other posts have this tag for the same user
        other_post_with_tag = await posts_collection.find_one({"tag_names":name, "user_id":user_id}, session=session)
        if not other_post_with_tag:
            # If no other posts have this tag, remove it from tags_collection
            await tags_collection.delete_one({"_id": tag_doc["_id"]}, session=session)
            
        await session.commit_transaction()
        return {"ok": True, "message": "Tag removed from post"}

    except PyMongoError as e:
        await session.abort_transaction()
        return {"ok": False, "message": f"Transaction failed: {str(e)}"}

    finally:
        await session.end_session()

async def verify_image_path(file_path: str) -> bool:
    """Check if image URL is still valid without downloading full content"""
    try:
        url = f"{TELE_FILE_URL}{file_path}"
        response = requests.head(url, timeout=5)  # HEAD request is faster
        return response.status_code == 200
    except:
        return False

async def upgrade_plan(user_id: str, plan_type: PlanType):
    """
    Upgrade user membership plan.
    Expects JSON body with 'user_id', 'plan_type', 'duration_days'.
    """
    try:
        user_doc = await users_collection.find_one({"user_id": str(user_id)})
        if not user_doc:
            return {"ok": False, "message": "User not found"}

        current_membership = user_doc.get("membership", {})
        
        # Get current start date and ensure it's a datetime object
        current_start_date = current_membership.get("current_start_date")
        if isinstance(current_start_date, str):
            current_start_date = datetime.fromisoformat(current_start_date.replace('Z', '+00:00'))
        elif current_start_date is None:
            current_start_date = datetime.now()
        
        # Get current end date (expires_at) and ensure it's a datetime object
        current_end_date = current_membership.get("expires_at")
        if isinstance(current_end_date, str):
            current_end_date = datetime.fromisoformat(current_end_date.replace('Z', '+00:00'))
        
        # Calculate new end date
        end_date = None
        if plan_type == PlanType.quarterly:
            end_date = datetime.now() + timedelta(days=90)
        elif plan_type == PlanType.yearly:
            end_date = datetime.now() + timedelta(days=365)
        
        # Only create previous_plan if there was an existing plan
        history = current_membership.get("history", [])
        if current_membership.get("plan"):  # Only add to history if there was a previous plan
            previous_plan = PreviousPlan(
                plan=current_membership.get("plan"),
                start_date=current_start_date,
                end_date=current_end_date  # Use the actual expiry date, not calculated
            )
            history = history + [previous_plan.model_dump()]
        
        updated_membership = Membership(
            plan=plan_type,
            expires_at=end_date,
            current_start_date=datetime.now(),
            history=history
        )

        updated_user = await users_collection.update_one(
            {"user_id": str(user_id)},
            {"$set": {"membership": updated_membership.model_dump()}}
        )
        
        print(updated_user.matched_count, updated_user.modified_count)
        return {"ok": True, "message": "Membership upgraded successfully"}

    except Exception as e:
        return {"ok": False, "message": f"Error: {str(e)}"}
    
async def is_premium_user(user_id:str) -> bool:
    """Check if the user has an active premium membership."""
    user_doc :User= await users_collection.find_one({"user_id": str(user_id)})
    if not user_doc:
        return False
    membership = user_doc.membership
    plan = membership.plan
    expires_at = membership.expires_at

    if not expires_at:
        return False

    # Ensure expires_at is a datetime object
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))

    return datetime.now() < expires_at