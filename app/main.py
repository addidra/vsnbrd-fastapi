from fastapi import Depends, FastAPI, Query, Response, APIRouter,HTTPException, Body
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import requests, os, base64, logging, asyncio
from app.actions.security import verify_telegram_auth
from app.actions.telegram import TelegramFilePathFetcher
from app.dependency import users_collection, posts_collection, tags_collection, boards_collection
from app.actions.telegram_bot import remove_tag_from_post, serialize_doc, send_msg, handle_new_user, get_file_path, extract_photo_details, save_post, generate_tags, save_tags_and_update_post, fetch_mime_type, get_image, fetch_post_from_file_path

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
        # if response["ok"]:
        #     return StreamingResponse(response["raw"], media_type=response["media_type"])
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
                    "resolution": {
                        "$cond": [
                            {"$eq": ["$file_details.high.file_path", file_path]},
                            "high",
                            "medium"
                        ]
                    },
                    "file_id": {
                        "$cond": [
                            {"$eq": ["$file_details.high.file_path", file_path]},
                            "$file_details.high.file_id",
                            "$file_details.medium.file_id"
                        ]
                    },
                    "file_path": {
                        "$cond": [
                            {"$eq": ["$file_details.high.file_path", file_path]},
                            "$file_details.high.file_path",
                            "$file_details.medium.file_path"
                        ]
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

from bson import ObjectId

@app.post("/getPostFromBoard")
async def get_post_from_board(board_id: str = Body(..., embed=True)):
    try:
        board = await boards_collection.find_one({"_id": ObjectId(board_id)}, {"posts": 1, "_id": 0, "name": 1})
        post_ids = board.get("posts", [])
        user_posts = await posts_collection.find({"_id": {"$in": post_ids}}).to_list(length=None)

        if not user_posts:
            return {"ok":False, "message": "No posts found for this user."}

        return {"posts":[serialize_doc(post) for post in user_posts], "board": board["name"]}

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
            {"tag_names": {"$in": tag_names}, "user_id": user_id},
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

@app.delete("/deletePost")
async def delete_post(file_path: str = Query(...)):
    try:
        post_res = await fetch_post_from_file_path(file_path)
        if not post_res.get("ok"):
            return {"ok": False, "message": "Post Not Found"}

        post = post_res.get("post")
        print(f"Deleting post: {post['_id']}", flush=True)
        # Delete associated tags if no other posts reference them
        delete_res = await posts_collection.delete_one({"_id": post.get('_id')})
        if delete_res.deleted_count == 0:
            return {"ok": False, "message": "Failed to delete post"}
        return {"ok": True, "message": "Post deleted successfully"}
    except Exception as e:
        return {"ok": False, "message":f"Error: {str(e)}"}
    
@app.delete("/removeTagFromPost")
# async def remove_tag(name: str = Body(...), file_path: str = Body(...), telegram_data: dict = Body(...)):
async def remove_tag(name: str = Body(...), file_path: str = Body(...), user_id: str = Body(...)):
    try:
        # verified = verify_telegram_auth(telegram_data)
        # user_id = verified.get("id")
        result = await remove_tag_from_post(name, file_path, user_id)
        return result
    except Exception as e:
        return {"ok": False, "message": f"Error: {str(e)}"}
    
@app.post("/addTagToPost")
async def add_tag(name: str = Body(..., embed=True), file_path: str = Body(..., embed=True), user_id: str = Body(..., embed=True)):
    try:
        post = await fetch_post_from_file_path(file_path)
        if not post.get("ok"):
            return {"ok": False, "message": "Post Not Found"}
        result = await save_tags_and_update_post([name], user_id, post.get("post", {}).get("_id"))
        return result
    except Exception as e:
        return {"ok": False, "message": f"Error: {str(e)}"}
    
@app.post("/createBoard")
async def create_board(name: str = Body(..., embed=True), user_id: str = Body(..., embed=True), file_paths: list = Body(..., embed=True)):
    try:
        post_ids = []
        for fp in file_paths:
            post = await fetch_post_from_file_path(fp)
            if not post.get("ok"):
                return {"ok": False, "message": f"Post Not Found for file_path: {fp}"}
            post_ids.append(post.get("post", {}).get("_id"))
        
        # Create new board structure
        new_board = {
            "name": name,
            "user_id": user_id,
            "posts": post_ids
        }

        # Add the new board to the user's boards array
        new_board = await boards_collection.insert_one(new_board)

        if new_board.inserted_id:
            return {"ok": True, "message": "Board created successfully.", "board_id": str(new_board.inserted_id)}
        else:
            return {"ok": False, "message": "Failed to create board."}

    except Exception as e:
        return {"ok": False, "message": f"Error: {str(e)}"}
    
@app.get("/getUserBoards")
async def get_user_boards(user_id: str = Query(...)):
    try:
        user_boards = await boards_collection.find({"user_id": user_id}).to_list(length=None)
        preview_imgs = []
        for board in user_boards:
            for post_id in board.get("posts", []):
                if len(preview_imgs) >= 1:
                    break
                post = await posts_collection.find_one({"_id": post_id})
                preview_imgs.append(post["file_details"].get("medium").get("file_path") or post["file_details"].get("high").get("file_path"))
            board["preview_images"] = preview_imgs
            board["posts"] = [str(post_id) for post_id in board["posts"]]
            preview_imgs = []
        if not user_boards:
            return []  # return empty list if no boards found
        
        return [serialize_doc(board) for board in user_boards]
    
    except Exception as e:
        return {"ok": False, "message": str(e)}

@app.delete("/deleteBoard")
async def delete_board(board_id: str = Body(..., embed=True)):
    try:
        delete_res = await boards_collection.delete_one({"_id": ObjectId(board_id)})
        if delete_res.deleted_count == 0:
            return {"ok": False, "message": "Failed to delete board or board not found"}
        return {"ok": True, "message": "Board deleted successfully"}
    except Exception as e:
        return {"ok": False, "message": f"Error: {str(e)}"}

@app.put("/renameBoard")
async def rename_board(board_id: str = Body(..., embed=True), name: str = Body(..., embed=True)):
    try:
        update_res = await boards_collection.update_one({"_id": ObjectId(board_id)}, {"$set": {"name": name}})
        if update_res.modified_count == 0:
            return {"ok": False, "message": "Failed to rename board or no changes made"}
        return {"ok": True, "message": "Board renamed successfully"}
    except Exception as e:
        return {"ok": False, "message": f"Error: {str(e)}"}
    
@app.put("/updateBoardPosts")
async def update_board_posts(board_id: str = Body(..., embed=True), file_paths: list = Body(..., embed=True)):
    try:
        post_ids = []
        for fp in file_paths:
            post = await fetch_post_from_file_path(fp)
            if not post.get("ok"):
                return {"ok": False, "message": f"Post Not Found for file_path: {fp}"}
            post_ids.append(post.get("post", {}).get("_id"))
        
        update_res = await boards_collection.update_one({"_id": ObjectId(board_id)}, {"$set": {"posts": post_ids}})
        if update_res.modified_count == 0:
            return {"ok": False, "message": "Failed to update board posts or no changes made"}
        return {"ok": True, "message": "Board posts updated successfully"}
    except Exception as e:
        return {"ok": False, "message": f"Error: {str(e)}"}