from fastapi import FastAPI, Query, Response, APIRouter,HTTPException, Body
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
import requests
import os
from app.actions.telegram import TelegramFilePathFetcher
import asyncio
from app.dependency import users_collection, posts_collection, tags_collection
from app.schemas.users import User
from app.schemas.posts import Post,FILE_TYPE, ResolutionDetails, FileDetails
from app.actions.telegram_bot import serialize_doc, send_error_msg, handle_new_user, is_duplicate_post, extract_photo_details, save_post

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
    
import logging

async def process_update(update: dict):
    """Main webhook update processor."""
    try:
        message = update.get("message")
        logging.info(f"Processing message: {update}")
        print(f"Processing message: {update}", flush=True)
        if not message:
            return

        user = message.get("from", {})
        user_id = str(user.get("id"))
        chat_id = str(message.get("chat", {}).get("id"))

        # Handle /start command
        if message.get("text") == "/start":
            await handle_new_user(user, chat_id)

        # Handle photo messages
        elif message.get("photo"):
            message_id = str(message.get("message_id"))

            if await is_duplicate_post(user_id, message_id):
                print("Duplicate post detected. Skipping.")
                return

            file_details = await extract_photo_details(message["photo"])
            await save_post(user_id, message_id, message.get("caption", ""), file_details)

    except Exception as e:
        await send_error_msg(text=str(e), chat_id=chat_id)
        print(f"Webhook processing failed: {e}", flush=True)
