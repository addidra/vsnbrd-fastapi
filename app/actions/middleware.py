from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from fastapi import Request, HTTPException
from starlette.responses import JSONResponse
from app.actions.security import validate_init_data

# Define routes that don't need authentication
PUBLIC_ROUTES = [
    "/docs",
    "/openapi.json",
    "/redoc",
    "/health",
]

class UserValidationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        # Allow public routes without authentication
        if request.url.path in PUBLIC_ROUTES:
            return await call_next(request)
        
        # ❌ REJECT: No Authorization header
        if "Authorization" not in request.headers:
            return JSONResponse(
                status_code=401,
                content={"detail": "Authorization header is required"}
            )
        
        # Parse Authorization header
        parts = request.headers["Authorization"].split(" ", 1)
        if len(parts) != 2:
            return JSONResponse(
                status_code=400,
                content={"detail": "Invalid Authorization header format. Expected: 'tma <initDataRaw>'"}
            )
        
        auth_type, auth_data = parts
        
        print(f"\n{'='*20} Incoming Request {'='*20}")
        print(f"Path: {request.url.path}")
        print(f"Method: {request.method}")
        print(f"Auth Type: {auth_type}")
        print(f"Auth Data Length: {len(auth_data) if auth_data else 0}")
        
        # ❌ REJECT: Empty auth data
        if not auth_data or auth_data.strip() == "":
            return JSONResponse(
                status_code=401,
                content={"detail": "Authorization data is empty"}
            )
        
        # ❌ REJECT: Wrong auth type
        if auth_type.lower() != "tma":
            return JSONResponse(
                status_code=400,
                content={"detail": "Invalid Authorization type. Expected 'tma'"}
            )
        
        # Validate init data
        init_data = validate_init_data(auth_data, expires_in=3600)
        
        # ❌ REJECT: Invalid or tampered data
        if not init_data:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or tampered init data"}
            )
        
        print("✅ Authorization successful")
        print(f"{'='*60}\n")
        
        # ✅ ALLOW: Continue to route handler
        response = await call_next(request)
        return response