from datetime import datetime, timedelta
from fastapi import Depends, FastAPI, Query, Response, APIRouter,HTTPException, Body, Header, Request
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import requests, os, base64, logging, asyncio
from app.actions.middleware import UserValidationMiddleware
from app.actions.security import validate_init_data
from app.actions.telegram import TelegramFilePathFetcher
from app.dependency import invoices_collection, users_collection, posts_collection, tags_collection, boards_collection
from app.actions.telegram_bot import upgrade_plan, run_tele_api, verify_image_path, remove_tag_from_post, serialize_doc, send_msg, handle_new_user, get_file_path, extract_photo_details, save_post, generate_tags, save_tags_and_update_post, fetch_mime_type, get_image, fetch_post_from_file_path
from urllib.parse import unquote, parse_qsl
from app.schemas.users import PaymentRecord, PlanType, PreviousPlan, Membership, InvoiceRequest
import json


load_dotenv()

TELE_FILE_URL = os.getenv("TELE_FILE_URL")
# FRONTEND_URL = os.getenv("FRONTEND_URL")
BOT_API = os.getenv("BOT_API")

app = FastAPI()
router = APIRouter()

# app.include_router(router)
# ⭐ CRITICAL: Add CORS middleware BEFORE other middlewares
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://yearly-civil-starling.ngrok-free.app",  # Your ngrok URL
        "https://vsnbrd-backend.onrender.com",  # Your backend
        "http://localhost:3000",  # Local development
        "http://localhost:5173",  # Vite default
    ],
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods
    allow_headers=["*"],  # Allow all headers including Authorization
)

# Add authentication middleware AFTER CORS
app.add_middleware(UserValidationMiddleware)
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

@app.api_route("/getImage", methods=["GET", "HEAD"])
async def getImage(file_path: str = Query(...)):
    """
    Returns image content for the given file_path.
    if not found refethes from telegram and updates DB accordingly and send the updated file path in response header 'X-new-file-path'.
    """
    try:
        # Try to get image from current path
        response = await get_image(file_path=file_path)
        
        if response["ok"]:
            return Response(content=response["content"], media_type=response["media_type"], headers={"X-file-path": file_path})
        
        # If image not found, fetch from DB and update
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

        posts = await (await posts_collection.aggregate(pipeline)).to_list(length=1)
        if not posts:
            raise HTTPException(status_code=404, detail="Post not found in database")
        
        post = posts[0]
        file_id = post.get("file_id")
        
        # Get user's chat_id
        user_doc = await users_collection.find_one(
            {"user_id": post.get("user_id")},
            {"chat_id": 1, "_id": 0}
        )

        if not user_doc:
            raise HTTPException(status_code=404, detail="User not found")

        chat_id = user_doc.get("chat_id")

        # Get new file path
        new_file_path = await get_file_path(
            file_id,
            message_id=post.get("message_id"),
            chat_id=chat_id,
            resolution=post.get("resolution"),
            user_id=post.get("user_id")
        )

        # Try to fetch image with new path
        response = await get_image(file_path=new_file_path)
        
        if response["ok"]:
            # Update the file path in database
            await posts_collection.update_one(
                {"_id": post["_id"]},
                {"$set": {f"file_details.{post.get('resolution')}.file_path": new_file_path}}
            )
            return Response(content=response["content"], media_type=response["media_type"], headers={"X-new-file-path": new_file_path})

        raise HTTPException(status_code=404, detail="Image not found even after path refresh")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    
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
        board = await boards_collection.find_one({"_id": ObjectId(board_id)}, {"posts": 1, "user_id": 1, "_id": 0, "name": 1})
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
        # TODO: Use index to search for tags efficinetly 
        tags = await tags_collection.aggregate([
            {
                "$search": {
                    "index": "tag_search",  # Different index for user_tags collection
                    "compound": {
                        "must": [
                            {
                                "autocomplete": {
                                    "query": query,
                                    "path": "name",
                                    "fuzzy": {"maxEdits": 3}
                                }
                            }
                        ],
                        "filter": [
                            {
                                "equals": {
                                    "path": "user_id",
                                    "value": user_id
                                }
                            }
                        ]
                    }
                }
            },
            {
                "$limit": 10
            },
            {
                "$project": {
                    "name": 1,
                    "score": {"$meta": "searchScore"},
                    "_id": 0
                }
            }
        ]).to_list(length=None)


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
        
        
        # Handle successful payment
        if "pre_checkout_query" in update:
            query_id = update["pre_checkout_query"]["id"]
            # Answer pre-checkout
            res = await run_tele_api(
                endpoint="answerPreCheckoutQuery", 
                params={"pre_checkout_query_id": query_id, "ok": True},
                method="post"
            ) 
            print(f"Pre-checkout answered: {res}", flush=True)
        
        if not message:
            return

        user = message.get("from", {})
        if user.get("is_bot"):
            return
        user_id = str(user.get("id"))
        chat_id = str(message.get("chat", {}).get("id"))
        
        if "successful_payment" in message:
            payment = message["successful_payment"]
            latest_pending_invoice = await invoices_collection.find_one(
                {"user_id": user_id, "status": "pending"},
                sort=[("payment_date", -1)]
            )
            
            await upgrade_plan(user_id=user_id, plan_type=latest_pending_invoice["plan_type"])
            # Update MongoDB
            await invoices_collection.update_one(
                {"user_id": user_id, "status": "pending"},
                {"$set": {"status": "completed", "telegram_payment_charge_id": payment["telegram_payment_charge_id"]}}
            )
            await send_msg(text="Payment successful! Your membership has been activated.", chat_id=chat_id, error=False)
            return
        
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
            post_count = await posts_collection.count_documents({"user_id":user_id})
            user_doc = await users_collection.find_one({"user_id": user_id})
            membership = user_doc.get("membership", {})
            # Check if the user has an active paid plan or is within free period limit
            if post_count <= 50 or (membership.get("expires_at") and membership.get("expires_at") > datetime.now()):
                tags_list = await generate_tags(mime_type=mime_type, data=base64_bytes, user_id=user_id)
                done = await save_tags_and_update_post(tags_list, user_id, post_id)
                if done:
                    await send_msg(text=f"Tags {tags_list} added to post {post_id}", chat_id=chat_id, error=False)
            elif post_count % 10 == 0: # notify every 10 posts after 50
                await send_msg(text="VSNBRD only generates tags for first 50 posts. Upgrade plan for more!", chat_id=chat_id, error=False)
        else:
            await send_msg(text="VSNBRD only supports Compressed Image files at the moment", chat_id=chat_id, error=False)
            
    except Exception as e:
        await send_msg(text=str(e), chat_id=chat_id)
        print(f"Webhook processing failed: {e}", flush=True)

@app.delete("/deletePost")
async def delete_post(file_path: str = Query(...)):
    """
    Delete a post and remove its reference from all boards.
    Maintains data consistency automatically.
    """
    try:
        # 1. Fetch the post
        post_res = await fetch_post_from_file_path(file_path)
        if not post_res.get("ok"):
            return {"ok": False, "message": "Post Not Found"}

        post = post_res.get("post")
        post_id = post.get('_id')
        
        print(f"Deleting post: {post_id}", flush=True)
        
        # 2. Remove post_id from all boards that reference it
        # This maintains consistency automatically
        await boards_collection.update_many(
            {"posts": post_id},  # Find all boards with this post
            {"$pull": {"posts": post_id}}  # Remove post_id from posts array
        )
        
        print(f"Removed post {post_id} from all boards", flush=True)
        
        # 3. Delete the post document
        delete_res = await posts_collection.delete_one({"_id": post_id})
        
        if delete_res.deleted_count == 0:
            return {"ok": False, "message": "Failed to delete post"}
        
        # 4. Optional: Delete associated tags if no other posts reference them
        # if post.get('tag_names'):
        #     for tag_name in post.get('tag_names', []):
        #         # Check if any other post uses this tag
        #         other_posts = await posts_collection.count_documents({"tag_names": tag_name})
        #         if other_posts == 0:
        #             await tags_collection.delete_one({"name": tag_name})
        
        return {
            "ok": True, 
            "message": "Post deleted successfully",
            "deleted_post_id": str(post_id)
        }
        
    except Exception as e:
        print(f"Error deleting post: {str(e)}", flush=True)
        import traceback
        traceback.print_exc()
        return {"ok": False, "message": f"Error: {str(e)}"}
    
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
async def get_user_boards(request: Request):
    try:
        user_id = str(request.state.user["user"].get("id"))
        user_boards = await boards_collection.find({"user_id": user_id}).to_list(length=None)
        print(user_boards)
        preview_imgs = []
        for board in user_boards:
            for post_id in board.get("posts", []):
                if len(preview_imgs) >= 1:
                    break
                print(post_id)
                post = await posts_collection.find_one({"_id": post_id})
                preview_imgs.append(post["file_details"].get("medium").get("file_path") or post["file_details"].get("high").get("file_path"))
            board["preview_images"] = preview_imgs
            board["posts"] = [str(post_id) for post_id in board["posts"]]
            preview_imgs = []
        
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
    
@app.post("/getImageDetails")
async def get_image_details(file_path: str = Body(..., embed=True)):
    try:
        # Fetch post from file_path
        post_res = await fetch_post_from_file_path(file_path)
        if not post_res.get("ok"):
            return {"ok": False, "message": "Post Not Found"}

        post = post_res.get("post")
        
        # Verify if the image URL is still valid
        is_valid = await verify_image_path(file_path)
        
        return {
            "ok": True,
            "file_path": file_path,
            "tag_names": post.get("tag_names", []),
            "is_valid": is_valid
        }
    except Exception as e:
        return {"ok": False, "message": f"Error: {str(e)}"}
    
# ========== USAGE IN YOUR ENDPOINTS ==========
@app.get("/test-verification")
async def test_verification(authorization: str = Header(None)):
    """
    Validate Telegram Mini Apps init data from Authorization header.
    
    Expected header format:
    Authorization: tma <initDataRaw>
    """
    
    if not authorization:
        raise HTTPException(
            status_code=400,
            detail="Missing Authorization header"
        )
    
    # Parse authorization header
    parts = authorization.split(" ", 1)
    if len(parts) != 2:
        raise HTTPException(
            status_code=400,
            detail="Invalid Authorization header format. Expected: 'tma <initDataRaw>'"
        )
    
    auth_type, auth_data = parts
    
    if auth_type.lower() != "tma":
        raise HTTPException(
            status_code=401,
            detail=f"Invalid auth type: {auth_type}. Expected: tma"
        )
    
    print(f"\n{'='*80}")
    print(f"Authorization header received (first 100 chars): {authorization[:100]}...")
    print(f"{'='*80}\n")
    
    # Validate init data
    init_data = validate_init_data(auth_data, expires_in=3600)
    
    if not init_data:
        raise HTTPException(
            status_code=401,
            detail="Invalid or tampered init data"
        )
    
    user_id = init_data["user"].get("id")
    
    return {
        "success": True,
        "user_id": user_id,
        "user_info": init_data["user"],
        "auth_date": init_data["auth_date"],
        "message": "✅ Verification successful!"
    }

@app.post("/create-invoice")
async def create_invoice(request: Request, invoice: InvoiceRequest):
    # Create invoice link
    user_id = str(request.state.user["user"].get("id"))
    payload = {
        "title": invoice.title,
        "description": invoice.description,
        "payload": f"user_{user_id}_{invoice.amount}",
        "currency": "XTR",  # Telegram Stars
        "prices": [{"label": invoice.title, "amount": invoice.amount}]
    }
    
    response = await run_tele_api(endpoint="createInvoiceLink", params=payload, method="post")
    
    if not response.get("ok"):
        raise HTTPException(400, "Failed to create invoice")
    
    invoice_link = response["result"]

    invoice_model = PaymentRecord(user_id=user_id,invoice_link=invoice_link,amount=invoice.amount,status="pending",plan_type=invoice.plan_type,title=invoice.title)
    await invoices_collection.insert_one(invoice_model.model_dump())

    return {"invoice_link": invoice_link}

@app.post("/test-invoice")
async def create_invoice(request: Request, invoice: InvoiceRequest):
    # Create invoice link
    user_id = str(request.state.user["user"].get("id"))
    payload = {
        "title": invoice.title,
        "description": invoice.description,
        "payload": f"user_{user_id}_10",
        "currency": "XTR",  # Telegram Stars
        "prices": [{"label": invoice.title, "amount": 10}]
    }
    
    response = await run_tele_api(endpoint="createInvoiceLink", params=payload, method="post")
    
    if not response.get("ok"):
        raise HTTPException(400, "Failed to create invoice")
    
    invoice_link = response["result"]

    invoice_model = PaymentRecord(user_id=user_id,invoice_link=invoice_link,amount=invoice.amount,status="pending",plan_type=invoice.plan_type,title=invoice.title)
    await invoices_collection.insert_one(invoice_model.model_dump())

    return {"invoice_link": invoice_link}

@app.get("/check-membership")
async def check_membership(request: Request):
    user_id = request.state.user["user"].get("id")
    user_doc = await users_collection.find_one({"user_id": str(user_id)})
    if not user_doc:
        return {"ok": False, "message": "User not found"}

    current_membership = user_doc.get("membership", {})
    if not current_membership:
        return {"ok": True, "isFree": True, "message": "No membership found"}
    isPaid = current_membership.get("expires_at") and current_membership.get("expires_at") > datetime.now()
    if not isPaid:
        return {"ok": True, "isFree": True, "message": "No active membership found"}

    return {"ok": True, "membership": current_membership}