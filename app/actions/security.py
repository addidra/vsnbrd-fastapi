import hashlib
import hmac
import time
from fastapi import HTTPException, Depends
import os
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_API")
BOT_SECRET = hashlib.sha256(BOT_TOKEN.encode()).digest()

def verify_telegram_auth(data: dict):
    """
    Verifies that data is a valid Telegram Login payload
    """
    check_hash = data.pop("hash", None)
    if not check_hash:
        raise HTTPException(status_code=401, detail="Missing auth hash")

    # Sort and format data
    data_check_string = "\n".join([f"{k}={v}" for k, v in sorted(data.items())])

    # Calculate HMAC-SHA256
    secret_key = BOT_SECRET
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if computed_hash != check_hash:
        raise HTTPException(status_code=401, detail="Invalid Telegram auth")

    # Optional: expire old logins (to prevent replay attacks)
    if "auth_date" in data and int(time.time()) - int(data["auth_date"]) > 86400:
        raise HTTPException(status_code=401, detail="Auth expired")

    return data  # verified Telegram user info
