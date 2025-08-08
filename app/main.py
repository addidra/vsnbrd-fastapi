from fastapi import FastAPI, Query, Response, APIRouter,HTTPException, Body
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
import requests
import os
from app.actions.telegram import TelegramFilePathFetcher
import asyncio
from pydantic import BaseModel
from app.dependency import users_collection, posts_collection, tags_collection
from app.schemas.users import User
from app.schemas.posts import Post,FILE_TYPE, ResolutionDetails, FileDetails
from app.actions.telegram_bot import run_tele_api, get_file_path, serialize_doc, send_error_msg

load_dotenv()

TELE_FILE_URL = os.getenv("TELE_FILE_URL")
# FRONTEND_URL = os.getenv("FRONTEND_URL")
BOT_API = os.getenv("BOT_API")

app = FastAPI()
router = APIRouter()
# app.include_router(router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://vsnbrd-addidras-projects.vercel.app","https://vsnbrd.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def hello():
    print("Render is working")
    return {"status": True}

@app.post("/webhook")
async def telegram_webhook(update: dict = Body(...)):
    asyncio.create_task(process_update(update))
    return {"ok": True}

@app.get('/test')
async def test():
    try:
        res = await send_error_msg(
            text="This is a test error message, You cannot share your private information as this is publically accessed",
            chat_id="1892630283"  # Replace with a valid chat ID for testing
        )
        return res
    except Exception as e:
        return HTTPException(status_code=500, detail=str(e))

@app.get('/getImage')
def getImage(file_path: str = Query(...)):
    try:
        url = f'{TELE_FILE_URL}{file_path}'
        response = requests.get(url)
        return Response(content=response.content, media_type='image/png')
    except Exception as e:
        return e
    
@app.get("/getUserPosts")
async def get_user_posts(user_id: str = Query(...)):
    try:
        # method 1: Fetch posts directly
        user_posts = await posts_collection.find({"user_id": user_id}).to_list(length=None)
        
        # method 2: Fetch user and then posts
        # user = await users_collection.find_one({"user_id": user_id})
        # user_posts2 = await posts_collection.find({"_id": {"$in": user.get("posts", [])}}).to_list(length=None)
        if not user_posts:
            return {"ok":False, "message": "No posts found for this user."}
        
        return [serialize_doc(post) for post in user_posts]
    
    except Exception as e:
        return {"ok": False, "message": str(e)}
    
@app.get('/getFilePaths')
def getFilePaths(user_id: str = Query(...)):
    fetcher = TelegramFilePathFetcher(BOT_API,user_id)
    return asyncio.run(fetcher.process())

@app.get('/get_user_from_db')
def get_user_from_db():
    try:
        def serialize_doc(doc):
            doc['_id'] = str(doc['_id'])
            return doc

        data = users_collection.find().limit(5)
        return [serialize_doc(doc) for doc in data]
    except Exception as e:
        return {"error": str(e)}


async def process_update(update: dict):
    try:
        message = update.get("message")
        if not message:
            return

        user = message.get("from", {})
        user_id = str(user.get("id"))
        chat_id = message.get("chat", {}).get("id")
        raise Exception("This is a test error message, You cannot share your private information as this is publically accessed")
        if message.get("text") == "/start":
            existing_user = await users_collection.find_one({"user_id": user_id})
            if not existing_user:
                response = await run_tele_api("getUserProfilePhotos", method="post", params={"user_id": user_id})
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

        if message.get("photo"):
            message_id = str(message.get("message_id"))

            # Deduplication check
            existing_post = await posts_collection.find_one({
                "user_id": user_id,
                "message_id": message_id
            })
            if existing_post:
                print("Duplicate post detected. Skipping.")
                return

            photo = message["photo"]
            file_id_high = photo[-1]["file_id"]
            file_id_medium = photo[-2]["file_id"]
            file_id_low = photo[-3]["file_id"]

            file_path_high = await get_file_path(file_id_high)
            file_path_medium = await get_file_path(file_id_medium)
            file_path_low = await get_file_path(file_id_low)

            post_data = Post(
                user_id=user_id,
                caption=message.get("caption", ""),
                file_details=ResolutionDetails(
                    high=FileDetails(file_id=file_id_high, file_path=file_path_high),
                    medium=FileDetails(file_id=file_id_medium, file_path=file_path_medium),
                    low=FileDetails(file_id=file_id_low, file_path=file_path_low),
                ),
                file_type=FILE_TYPE.IMAGE,
                message_id=message_id,
            )

            post_id = (await posts_collection.insert_one(post_data.model_dump())).inserted_id
            await users_collection.update_one(
                {"user_id": user_id},
                {"$addToSet": {"posts": post_id}}
            )
            print(f"Post saved: {post_id}")

    except Exception as e:
        await send_error_msg(text=str(e), chat_id=chat_id)
        print(f"Webhook processing failed: {e}", flush=True)
