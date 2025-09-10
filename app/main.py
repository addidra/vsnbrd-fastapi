from fastapi import FastAPI, Query, Response, APIRouter,HTTPException, Body
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
import requests, os, base64, logging, asyncio
from app.actions.telegram import TelegramFilePathFetcher
from app.dependency import users_collection, posts_collection, tags_collection
from app.actions.telegram_bot import serialize_doc, send_msg, handle_new_user, get_file_path, extract_photo_details, save_post, generate_tags, save_tags_and_update_post, fetch_mime_type, get_image

load_dotenv()

TELE_FILE_URL = os.getenv("TELE_FILE_URL")
# FRONTEND_URL = os.getenv("FRONTEND_URL")
BOT_API = os.getenv("BOT_API")

app = FastAPI()
router = APIRouter()

# app.include_router(router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://vsnbrd-addidras-projects.vercel.app","https://vsnbrd.vercel.app","https://yearly-civil-starling.ngrok-free.app"],
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
        file_path = await get_file_path(file_id="AgACAgUAAxkBAAOKaJjhrc4UQrIuNwPWpYQ_PV751vwAAm3IMRvWLchUa956uPM7MDIBAAMCAAN4AAM2BA",message_id="139", chat_id="1892630283", resolution="medium", user_id="1892630283")
        return file_path
    except Exception as e:
        return HTTPException(status_code=500, detail=str(e))

@app.get('/getImage')
async def getImage(file_path: str = Query(...)):
    try:
        response = await get_image(file_path=file_path)  # await + dict response
        if response["ok"]:
            return Response(content=response["content"], media_type=response["media_type"])
        
        # fallback to DB if image not found at URL
        pipeline = [
            {
                "$match": {
                    "$or": [
                        {"file_details.high.file_path": file_path},
                        {"file_details.medium.file_path": file_path}
                    ]
                }
            },
            {
                "$project": {
                    "user_id": 1,
                    "message_id": 1,
                    "file_details": {
                        "high": {
                            "file_id": "$file_details.high.file_id",
                            "file_path": "$file_details.high.file_path"
                        },
                        "medium": {
                            "file_id": "$file_details.medium.file_id",
                            "file_path": "$file_details.medium.file_path"
                        }
                    }
                }
            }
        ]


        post = await (await posts_collection.aggregate(pipeline)).to_list()
        if post:
            post = post[0]

        file_id = post.get("file_id")
        user_doc = await users_collection.find_one(
            {"user_id": post.get("user_id")},
            {"chat_id": 1, "_id": 0}  # project only chat_id
        )

        if not user_doc:
            raise Exception("User not found")

        chat_id = user_doc.get("chat_id")

        file_path = await get_file_path(
            file_id,
            message_id=post.get("message_id"),
            chat_id=chat_id,
            resolution=post.get("resolution"),
            user_id=post.get("user_id")
        )

        response = await get_image(file_path=file_path)
        if response["ok"]:
            await posts_collection.update_one(
                {"_id": post["_id"]},
                {"$set": {f"file_details.{post.get('resolution')}.file_path": file_path}}
            )
            return Response(content=response["content"], media_type=response["media_type"])

        raise Exception("Image not found")

    except Exception as e:
        return {"error": str(e)}

    
@app.get("/getUserPosts")
async def get_user_posts(user_id: str = Query(...)):
    try:
        # method 1: Fetch posts directly
        user_posts = await posts_collection.find({"user_id": user_id}).to_list(length=None)
        
        if not user_posts:
            return {"ok":False, "message": "No posts found for this user."}
        
        return [serialize_doc(post) for post in user_posts]
    
    except Exception as e:
        return {"ok": False, "message": str(e)}
    
@app.get("/search")
async def search_posts(query: str = Query(...), user_id: str = Query(...)):
    try:
        # First try Atlas Search autocomplete
        tag_cursor = await tags_collection.aggregate([
            {
                "$search": {
                    "index": "search",  # the index you created in Atlas
                    "autocomplete": {
                        "query": query,
                        "path": "name",
                        "fuzzy": { "maxEdits": 1 }  # typo-tolerance
                    }
                }
            },
            {"$match": {"user_id": user_id}},
            {"$limit": 10}
        ])

        tags = await tag_cursor.to_list(length=None)

        # Fallback to regex if Atlas Search returned nothing
        if not tags:
            tags = await tags_collection.find(
                {
                    "name": {"$regex": query, "$options": "i"},
                    "user_id": user_id
                }
            ).to_list(length=None)
            print(f"Regex fallback")

        tag_names = [t["name"] for t in tags]
        print(f"Found tags: {tag_names}")

        search_results = await posts_collection.find(
            {"tag_names": {"$in": tag_names}},
            {
                "file_details": 1,
                "caption": 1,
                "tag_names": 1,
                "created_at": 1,
                "_id": 0
            }
        ).to_list(length=None)

        if not search_results:
            return {"ok": False, "message": "No posts found matching the query."}

        return search_results

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
    """Main webhook update processor."""
    try:
        message = update.get("message")
        logging.info(f"Processing message: {update}")
        print(f"Processing message: {update}", flush=True)
        if not message:
            return

        user = message.get("from", {})
        if user.get("is_bot"):
            return
        user_id = str(user.get("id"))
        chat_id = str(message.get("chat", {}).get("id"))

        # Handle /start command
        if message.get("text") == "/start":
            await handle_new_user(user, chat_id)

        # Handle photo messages
        elif message.get("photo"):
            message_id = str(message.get("message_id"))
            
            if await users_collection.find_one({"user_id": user_id}) is None:
                await handle_new_user(user, chat_id)
                
            file_details = await extract_photo_details(message["photo"])
            await send_msg(text=f"Extracted Photo Detail {file_details}", chat_id=chat_id, error=False) if file_details else None
            post_id = await save_post(user_id, message_id, message.get("caption", ""), file_details, chat_id=chat_id)

            # fetch the photo byte from post file
            response = requests.get(os.getenv("TELE_FILE_URL") + (file_details.medium or file_details.high).file_path)
            base64_bytes = base64.b64encode(response.content).decode("utf-8")
            mime_type = fetch_mime_type(str(base64_bytes),file_details.high.file_path)
            await send_msg(text=f"Read: {mime_type}", chat_id=chat_id, error=False)
            tags_list = await generate_tags(mime_type=mime_type, data=base64_bytes, user_id=user_id)
            done = await save_tags_and_update_post(tags_list, user_id, post_id)
            if done:
                await send_msg(text=f"Tags {tags_list} added to post {post_id}", chat_id=chat_id, error=False)

        else:
            await send_msg(text="VSNBRD only supports Compressed Image files at the moment", chat_id=chat_id, error=False)
            
    except Exception as e:
        await send_msg(text=str(e), chat_id=chat_id)
        print(f"Webhook processing failed: {e}", flush=True)
