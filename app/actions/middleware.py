from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from fastapi import Request, HTTPException
from starlette.responses import JSONResponse
from app.actions.security import validate_init_data
import os 

class UserValidationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        if "Authorization" in request.headers.keys():
            parts = request.headers["Authorization"].split(" ", 1)
            if len(parts) != 2:
                raise HTTPException(status_code=400, detail="Invalid Authorization header format. Expected: 'tma <initDataRaw>'")
            
            auth_type, auth_data = parts

            if not auth_data:
                raise HTTPException(status_code=400, detail="Authorization data missing.")
                
            if auth_type.lower() != "tma":
                raise HTTPException(status_code=400, detail="Invalid Authorization type. Expected 'tma'")

            init_data = validate_init_data(auth_data, expires_in=3600)
            if not init_data:
                raise HTTPException(status_code=401, detail="Invalid or tampered init data")

            # ✅ Option 1: Pass request to next middleware/route
            response = await call_next(request)
            return response
        
        # If no Authorization header → continue
        return await call_next(request)
