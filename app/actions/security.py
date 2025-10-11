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


def verify_telegram_auth_debug(init_data: str) -> dict:
    """
    Verify Telegram initData with detailed debugging.
    Returns dict with success status and debug info.
    """
    try:
        parsed_data = dict(parse_qsl(unquote(init_data)))
        
        print("\n=== VERIFICATION DEBUG ===")
        print(f"Parsed fields: {list(parsed_data.keys())}")
        
        if "hash" not in parsed_data:
            return {"success": False, "error": "Missing 'hash' field", "debug": "parsed_data keys: " + str(list(parsed_data.keys()))}
        
        if "user" not in parsed_data:
            return {"success": False, "error": "Missing 'user' field", "debug": "parsed_data keys: " + str(list(parsed_data.keys()))}
        
        hash_value = parsed_data.pop("hash")
        print(f"Telegram hash: {hash_value}")
        
        # Create data check string - MUST match exactly what Telegram used
        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(parsed_data.items())
        )
        print(f"\nData check string:\n{data_check_string}\n")
        
        # Verify hash - Step by step
        print(f"Bot token: {SECRET_KEY[:20]}...")
        
        # IMPORTANT: Use the RAW bot token, not its SHA256 hash
        secret_key = hashlib.sha256(SECRET_KEY.encode()).digest()
        print(f"Secret key (hashed token): {secret_key.hex()[:20]}...")
        
        # Try with hashed token first (standard method)
        computed_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()
        print(f"\nComputed hash (with hashed token): {computed_hash}")
        print(f"Telegram hash:  {hash_value}")
        
        # If that doesn't match, try with raw token
        if computed_hash != hash_value:
            print("\n⚠️  Hash mismatch! Trying with raw bot token...")
            computed_hash_raw = hmac.new(
                SECRET_KEY.encode(),
                data_check_string.encode(),
                hashlib.sha256
            ).hexdigest()
            print(f"Computed hash (with raw token): {computed_hash_raw}")
            
            if computed_hash_raw == hash_value:
                print("✅ MATCH FOUND! Using raw token works!")
                computed_hash = computed_hash_raw
        
        # Step 3: Compare
        hashes_match = hmac.compare_digest(computed_hash, hash_value)
        print(f"Hashes match: {hashes_match}")
        
        if not hashes_match:
            return {
                "success": False,
                "error": "Hash mismatch",
                "debug": {
                    "bot_token_set": bool(SECRET_KEY and SECRET_KEY != "YOUR_BOT_TOKEN"),
                    "computed_hash": computed_hash,
                    "telegram_hash": hash_value,
                    "bot_token_start": SECRET_KEY[:20] if SECRET_KEY else "NOT SET"
                }
            }
        
        # Extract user_id
        user_data = json.loads(parsed_data.get("user", "{}"))
        user_id = str(user_data.get("id"))
        
        print(f"✅ Verification successful! User ID: {user_id}")
        
        return {
            "success": True,
            "user_id": user_id,
            "user_info": user_data,
            "debug": "Verification successful"
        }
        
    except Exception as e:
        print(f"❌ Exception: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": str(e),
            "debug": traceback.format_exc()
        }
