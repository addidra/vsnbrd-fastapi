import hashlib
import hmac
from urllib.parse import unquote, parse_qsl
import json
import os
import datetime


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

def validate_init_data(init_data_raw: str, token: str, expires_in: int = 3600) -> dict | None:
    """
    Validate and parse Telegram Mini Apps init data.
    
    Args:
        init_data_raw: Raw init data string (URL-encoded)
        token: Bot token for verification
        expires_in: Time window for valid signatures (in seconds)
    
    Returns:
        Parsed init data dict if valid, None otherwise
    """
    try:
        # Parse the init data
        parsed_data = dict(parse_qsl(unquote(init_data_raw)))
        
        # Extract hash and auth_date
        if "hash" not in parsed_data:
            print("❌ Missing hash field")
            return None
        
        if "auth_date" not in parsed_data:
            print("❌ Missing auth_date field")
            return None
        
        hash_value = parsed_data.pop("hash")
        auth_date = int(parsed_data.get("auth_date", 0))
        
        # Check if init data is expired
        current_time = int(datetime.now().timestamp())
        if current_time - auth_date > expires_in:
            print(f"❌ Init data expired. Age: {current_time - auth_date}s, Max: {expires_in}s")
            return None
        
        # Create data check string (must be sorted)
        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(parsed_data.items())
        )
        
        print("\n=== VERIFICATION ===")
        print(f"Data check string:\n{data_check_string}\n")
        
        # Verify hash using the bot token
        secret_key = hashlib.sha256(token.encode()).digest()
        computed_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()
        
        print(f"Computed hash: {computed_hash}")
        print(f"Telegram hash: {hash_value}")
        print(f"Match: {hmac.compare_digest(computed_hash, hash_value)}")
        
        if not hmac.compare_digest(computed_hash, hash_value):
            print("❌ Hash verification failed!")
            return None
        
        print("✅ Hash verified!")
        
        # Parse user data if present
        user_data = {}
        if "user" in parsed_data:
            try:
                user_data = json.loads(parsed_data["user"])
            except:
                pass
        
        return {
            "user": user_data,
            "auth_date": auth_date,
            "chat_instance": parsed_data.get("chat_instance"),
            "chat_type": parsed_data.get("chat_type"),
            "start_param": parsed_data.get("start_param"),
        }
        
    except Exception as e:
        print(f"❌ Exception: {str(e)}")
        import traceback
        traceback.print_exc()
        return None
