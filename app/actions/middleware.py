from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from fastapi import Request
from starlette.responses import JSONResponse
from app.actions.security import validate_init_data
import traceback

PUBLIC_ROUTES = ["/getImage","/","/docs", "/openapi.json", "/redoc", "/health","/webhook"]

class UserValidationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        try:
            # ⭐ Skip OPTIONS requests (CORS preflight)
            if request.method == "OPTIONS":
                print(f"⚪ OPTIONS request to {request.url.path} - skipping auth")
                return await call_next(request)
            
            # Allow public routes
            if request.url.path in PUBLIC_ROUTES:
                print(f"⚪ Public route {request.url.path} - skipping auth")
                return await call_next(request)
            
            print(f"\n{'='*60}")
            print(f"🔍 Checking auth for: {request.method} {request.url.path}")
            print(f"Origin: {request.headers.get('origin', 'None')}")
            
            # Check for Authorization header
            if "Authorization" not in request.headers:
                print("❌ No Authorization header")
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Authorization header is required"},
                    headers={
                        "Access-Control-Allow-Origin": request.headers.get("origin", "*"),
                        "Access-Control-Allow-Credentials": "true",
                    }
                )
            
            # Parse Authorization
            auth_header = request.headers["Authorization"]
            print(f"Authorization header: {auth_header[:50]}...")
            
            parts = auth_header.split(" ", 1)
            if len(parts) != 2:
                print("❌ Invalid Authorization format")
                return JSONResponse(
                    status_code=400,
                    content={"detail": "Invalid Authorization header format"},
                    headers={
                        "Access-Control-Allow-Origin": request.headers.get("origin", "*"),
                        "Access-Control-Allow-Credentials": "true",
                    }
                )
            
            auth_type, auth_data = parts
            
            if not auth_data or auth_data.strip() == "":
                print("❌ Empty auth data")
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Authorization data is empty"},
                    headers={
                        "Access-Control-Allow-Origin": request.headers.get("origin", "*"),
                        "Access-Control-Allow-Credentials": "true",
                    }
                )
            
            if auth_type.lower() != "tma":
                print(f"❌ Invalid auth type: {auth_type}")
                return JSONResponse(
                    status_code=400,
                    content={"detail": f"Invalid auth type: {auth_type}. Expected 'tma'"},
                    headers={
                        "Access-Control-Allow-Origin": request.headers.get("origin", "*"),
                        "Access-Control-Allow-Credentials": "true",
                    }
                )
            
            # Validate init data
            print("🔐 Validating init data...")
            init_data = validate_init_data(auth_data, expires_in=3600)
            
            if not init_data:
                print("❌ Invalid init data")
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid or tampered init data"},
                    headers={
                        "Access-Control-Allow-Origin": request.headers.get("origin", "*"),
                        "Access-Control-Allow-Credentials": "true",
                    }
                )
            
            print(f"✅ Auth successful for user: {init_data.get('user', {}).get('id', 'unknown')}")
            print(f"{'='*60}\n")
            
            # Store user in request state
            request.state.user = init_data
            
            # Continue to route
            response = await call_next(request)
            return response
            
        except Exception as e:
            print(f"💥 Exception in middleware: {str(e)}")
            traceback.print_exc()
            return JSONResponse(
                status_code=500,
                content={"detail": f"Internal server error: {str(e)}"},
                headers={
                    "Access-Control-Allow-Origin": request.headers.get("origin", "*"),
                    "Access-Control-Allow-Credentials": "true",
                }
            )