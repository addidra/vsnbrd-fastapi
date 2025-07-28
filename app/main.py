from fastapi import FastAPI, Query, Response, APIRouter
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
import requests
import os
from app.actions.telegram import TelegramFilePathFetcher
import asyncio
from pydantic import BaseModel
from app.dependency import users_collection
from typing import Any
from app.schemas.users import User

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
    return {"status": True}

@app.post("/webhook")
async def telegram_webhook(update: TelegramUpdate):
    try:
        if update.message and update.message.text == "/start":
            user = update.message["from"]
            user_data = User(
                username=user.get("username", ""),
                first_name=user.get("first_name", ""),
                last_name=user.get("last_name", ""),  
                user_id=str(user.get("id"))
            )
            users_collection.update_one(
                {"user_id": user.id},
                {"$setOnInsert": user_data.model_dump()},
                upsert=True
            )
            print(f"User {user_data.username} added to the database.")
        print(update)
        return {"status": True}
    except Exception as e:
        raise e

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
