from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import httpx
import os
import time
from typing import Dict, Any

app = FastAPI(title="npm-info-vercel")

# Simple in-memory TTL cache
CACHE_TTL = int(os.getenv("CACHE_TTL", "60"))  # seconds
_cache: Dict[str, Dict[str, Any]] = {}


def get_from_cache(key: str):
    ent = _cache.get(key)
    if not ent:
        return None
    if time.time() - ent["ts"] > CACHE_TTL:
        _cache.pop(key, None)
        return None
    return ent["value"]


def set_cache(key: str, val: Any):
    _cache[key] = {"ts": time.time(), "value": val}


async def fetch_registry(pkg: str) -> Dict[str, Any]:
    url = f"https://registry.npmjs.org/{pkg}"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url)
        if r.status_code == 404:
            raise HTTPException(status_code=404, detail="Package not found")
        r.raise_for_status()
        return r.json()


async def fetch_downloads(pkg: str) -> Dict[str, Any]:
    url = f"https://api.npmjs.org/downloads/point/last-week/{pkg}"
    async with httpx.AsyncClient(timeout=8) as client:
        r = await client.get(url)
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        return r.json()


@app.get("/api/package/{package_name}")
async def get_package(
    package_name: str,
    include_versions: bool = False,
    include_readme: bool = False
):
    """Return basic npm package info."""
    key = f"pkg:{package_name}:{int(include_versions)}:{int(include_readme)}"
    cached = get_from_cache(key)
    if cached:
        return JSONResponse(content=cached)

    reg = await fetch_registry(package_name)
    latest = reg.get("dist-tags", {}).get("latest")
    latest_meta = reg.get("versions", {}).get(latest, {}) if latest else {}
    downloads = await fetch_downloads(package_name)

    result = {
        "name": reg.get("name"),
        "description": reg.get("description"),
        "homepage": reg.get("homepage"),
        "repository": reg.get("repository"),
        "latest": latest,
        "latest_meta": {
            "version": latest_meta.get("version"),
            "license": latest_meta.get("license"),
            "dependencies": latest_meta.get("dependencies", {}),
            "dist": latest_meta.get("dist", {}),
        },
        "downloads_last_week": downloads.get("downloads") if downloads else None,
    }

    if include_versions:
        versions = list(reg.get("versions", {}).keys())
        result["versions"] = versions[-20:]

    if include_readme:
        result["readme"] = reg.get("readme", "")

    set_cache(key, result)
    return JSONResponse(content=result)


@app.get("/api/user/{username}")
async def get_user_packages(username: str, size: int = 10, from_: int = 0):
    """Fetch npm packages published by a given user (maintainer)."""
    key = f"user:{username}:{size}:{from_}"
    cached = get_from_cache(key)
    if cached:
        return JSONResponse(content=cached)

    url = "https://registry.npmjs.org/-/v1/search"
    params = {"text": f"maintainer:{username}", "size": size, "from": from_}

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url, params=params)
        if r.status_code != 200:
            raise HTTPException(status_code=502, detail="Failed to fetch user packages")
        data = r.json()

    results = []
    for pkg in data.get("objects", []):
        pkg_info = pkg.get("package", {})
        results.append({
            "name": pkg_info.get("name"),
            "version": pkg_info.get("version"),
            "description": pkg_info.get("description"),
            "date": pkg_info.get("date"),
            "links": pkg_info.get("links"),
        })

    output = {"username": username, "count": data.get("total", 0), "packages": results}
    set_cache(key, output)
    return JSONResponse(content=output)


@app.get("/api/health")
async def health():
    return {"status": "ok"}

@app.get("/api/ping")
async def ping():
    return {"status": "pong"}

@app.get("/")
async def root():
    return {"message": "Welcome to the NPM Package API"}
