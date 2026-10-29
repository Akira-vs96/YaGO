"""OpenStreetMap address integration with modest caching and provider pacing."""
import asyncio
import os
import time

import httpx
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api", tags=["maps"])
cache = {}
gate = asyncio.Lock()
last_request = 0.0


async def nominatim(path, params):
    global last_request
    key = (path, tuple(sorted(params.items())))
    entry = cache.get(key)
    if entry and time.monotonic() - entry[0] < 600:
        return entry[1]
    async with gate:
        await asyncio.sleep(max(0, 1.1 - (time.monotonic() - last_request)))
        last_request = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.get(os.getenv("NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org").rstrip("/") + path,
                    params={**params, "format": "jsonv2", "accept-language": "ru"},
                    headers={"User-Agent": os.getenv("NOMINATIM_USER_AGENT", "YaGo educational app (contact: example@example.com)")})
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(503, "Поиск адресов временно недоступен") from exc
        cache[key] = (time.monotonic(), data)
        return data


@router.get("/geocode")
async def geocode(q: str = Query(min_length=3, max_length=200)):
    query = q if "астан" in q.lower() else f"{q}, Астана, Казахстан"
    results = await nominatim("/search", {"q": query, "limit": 5, "countrycodes": "kz"})
    return [{"address": r["display_name"], "lat": float(r["lat"]), "lng": float(r["lon"])} for r in results]


@router.get("/reverse-geocode")
async def reverse_geocode(lat: float = Query(ge=-90, le=90), lng: float = Query(ge=-180, le=180)):
    result = await nominatim("/reverse", {"lat": lat, "lon": lng, "zoom": 18})
    if not result.get("display_name"):
        raise HTTPException(404, "Адрес для точки не найден")
    return {"address": result["display_name"], "lat": lat, "lng": lng}


@router.get("/routes")
async def route(startLat: float, startLng: float, endLat: float, endLng: float):
    from .services import Point, driving_route
    result = await driving_route(Point(address="Начало", lat=startLat, lng=startLng),
                                 Point(address="Конец", lat=endLat, lng=endLng))
    return {"provider": "OSRM", "profile": "driving", "geometry": result["geometry"],
            "distanceMeters": round(result["distance"]), "durationSeconds": round(result["duration"])}
