import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


app_name = os.getenv("APP_NAME", "YaGo API")
cors_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]

app = FastAPI(title=app_name, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", tags=["health"])
def health() -> dict[str, str | bool]:
    return {"ok": True, "service": app_name}