import hashlib
import hmac
from urllib.parse import unquote, parse_qsl
import json
import os
from datetime import datetime

# SECRET_KEY = os.getenv("BOT_API")
# test

def validate_init_data(init_data_raw: str, expires_in: int = 3600) -> dict | None:
    """
    Validate Telegram Mini Apps init data.
    
    Returns dict with user data if valid, None if invalid.
    
    N_update: The endpoint should get the user_id from authentication rather than data passed in body
    """
    try:
        # ❌ Check if empty
        if not init_data_raw or init_data_raw.strip() == "":
            print("❌ Init data is empty")
            return None
        
        # Parse the init data
        parsed_data = dict(parse_qsl(unquote(init_data_raw)))
        
        # ❌ Check if parsed data is empty
        if not parsed_data:
            print("❌ Parsed data is empty")
            return None
        
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
        
        # Create data check string (MUST BE SORTED ALPHABETICALLY)
        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(parsed_data.items())
        )
        
        print("\n=== VERIFICATION ===")
        print(f"Data check string:\n{data_check_string}\n")
        
        # Create secret key from bot token
        secret_key = hmac.new(
            b"WebAppData",
            SECRET_KEY.encode(),
            hashlib.sha256
        ).digest()
        
        # Verify hash using the secret key
        computed_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()
        
        print(f"Computed hash: {computed_hash}")
        print(f"Telegram hash:  {hash_value}")
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
            except Exception as e:
                print(f"❌ Failed to parse user data: {e}")
                return None
        
        # Return validated data
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