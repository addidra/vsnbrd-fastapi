from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from fastapi import Request, HTTPException
from app.actions.security import validate_init_data
import os 

BOT_API = os.getenv("BOT_API")

class UserValidationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        if "Authorization" in request.headers.keys():
            # Parse authorization header
            parts = request.headers["Authorization"].split(" ", 1)
            if len(parts) != 2:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid Authorization header format. Expected: 'tma <initDataRaw>'"
                )
            
            auth_type, auth_data = parts
            
            if not auth_data:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid Authorization header format. Expected: 'tma <initDataRaw>'"
                )
                
            if auth_type.lower() != "tma":
                raise HTTPException(
                    status_code=400,
                    detail="Invalid Authorization type. Expected 'tma'"
                )
            
            init_data = validate_init_data(auth_data, BOT_API, expires_in=3600)
            
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
