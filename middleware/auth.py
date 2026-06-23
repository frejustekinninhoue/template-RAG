from fastapi import HTTPException, Request
from jose import JWTError, jwt

from app.config import settings


_PUBLIC_PATHS = {
    "/health",
    "/api/v1/health",
    "/docs",
    "/openapi.json",
}


def _is_public_path(path: str) -> bool:
    if path in _PUBLIC_PATHS:
        return True
    return path.startswith("/api/v1/health")


async def auth_middleware(request: Request, call_next):
    if _is_public_path(request.url.path):
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed token")

    token = auth_header.removeprefix("Bearer ").strip()
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
        request.state.user_id = payload["sub"]
        request.state.user_payload = payload
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

    return await call_next(request)
