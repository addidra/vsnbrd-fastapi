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
from app.actions.telegram_bot import run_tele_api, get_file_path

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

class TelegramUpdate(BaseModel):
    update_id: int
    message: dict | None = None
    edited_message: dict | None = None

@app.get("/")
async def hello():
    print("Render is working")
    return {"status": True}

@app.post("/webhook")
async def telegram_webhook(update: dict = Body(...)):
    try:
        print(update, flush=True)
        if "message" not in update or "from" not in update["message"]:
            raise HTTPException(status_code=400, detail="Invalid update payload")
        user = update["message"]["from"]
        if update["message"] and update["message"].get("text", "") == "/start":
            existing_user = users_collection.find_one({"user_id": str(user.get("id"))})
            if existing_user:
                return {"status": True, "message": "User already exists in the database."}
            response = await run_tele_api("getUserProfilePhotos",method="post", params={"user_id": str(user.get("id"))})
            file_id = response.get("result", {}).get("photos", [])[0][0].get("file_id", "")
            file_path = await get_file_path(file_id)
            user_data = User(
                username=user.get("username", ""),
                first_name=user.get("first_name", ""),
                last_name=user.get("last_name", ""),  
                user_id=str(user.get("id")),
                chat_id = update["message"]["chat"]["id"],
                profile_image_id=file_id,
                profile_image_path=file_path
            )
            users_collection.update_one(
                {"user_id": str(user.get("id"))},
                {"$setOnInsert": user_data.model_dump()},
                upsert=True
            )
            print(f"User {user_data.username} added to the database.", flush=True)
        if update["message"]["photo"]:
            # Handle photo message
            photo = update["message"]["photo"]
            file_id_high = photo[3].get("file_id", "")
            file_id_medium = photo[2].get("file_id", "")
            file_id_low = photo[1].get("file_id", "")
            file_path_high = await get_file_path(file_id_high)
            file_path_medium = await get_file_path(file_id_medium)
            file_path_low = await get_file_path(file_id_low)
            post_data = Post(
                user_id=str(user.get("id")),
                caption=update["message"].get("caption", ""),
                file_details=ResolutionDetails(
                    high=FileDetails(file_id=file_id_high, file_path=file_path_high),
                    medium=FileDetails(file_id=file_id_medium, file_path=file_path_medium),
                    low=FileDetails(file_id=file_id_low, file_path=file_path_low),
                ),
                file_type=FILE_TYPE.IMAGE,
                message_id=str(update["message"].get("message_id")),
            )
            # Save post data to the database
            result = await posts_collection.insert_one(post_data.model_dump())
            post_id = result.inserted_id
                
            # Update user posts
            await users_collection.update_one(
                {"user_id": str(user.get("id"))},
                {"$addToSet": {"posts": post_id}}
            )
            print(f"Post saved with ID: {post_id}", flush=True)
            return {"status": "Post saved successfully", "post_id": str(post_id)}
        return {"status": "End of webhook processing"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get('/test')
async def test():
    try:
        response = await run_tele_api("getUserProfilePhotos", method="post", params={"user_id": "1892630283"})
        response = dict(response)
        # return response
        file_id = response.get("result", {}).get("photos", [])[0][0].get("file_id", "")
        file_path = await get_file_path(file_id)
        return {"status": True, "data": file_path}
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
