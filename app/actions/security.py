import hashlib
import hmac
from urllib.parse import unquote, parse_qsl
import json
import os


SECRET_KEY = os.getenv("BOT_API")

def verify_telegram_auth(init_data: str) -> str | None:
    """
    Verify Telegram WebApp initData and return user_id.
    Returns None if verification fails.
    """
    try:
        parsed_data = dict(parse_qsl(unquote(init_data)))
        
        if "hash" not in parsed_data or "user" not in parsed_data:
            return None
        
        hash_value = parsed_data.pop("hash")
        
        # Create data check string
        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(parsed_data.items())
        )
        
        # Verify hash
        secret_key = hashlib.sha256(SECRET_KEY.encode()).digest()
        computed_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(computed_hash, hash_value):
            return None
        
        # Extract user_id
        user_data = json.loads(parsed_data.get("user", "{}"))
        user_id = str(user_data.get("id"))
        
        return user_id if user_id else None
        
    except Exception as e:
        print(f"Auth error: {e}")
        return None


