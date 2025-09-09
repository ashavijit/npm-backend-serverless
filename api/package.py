from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse , HTMLResponse
import httpx
import requests
import os
import time
from typing import Dict, Any, List

app = FastAPI(title="npm-info-vercel")

from fastapi.middleware.cors import CORSMiddleware

origins = [
    "*"
]

# Simple in-memory TTL cache
CACHE_TTL = int(os.getenv("CACHE_TTL", "60"))  # seconds
_cache: Dict[str, Dict[str, Any]] = {}


app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,          # list of allowed origins
    allow_credentials=True,
    allow_methods=["*"],            # allow all HTTP methods (GET, POST, etc.)
    allow_headers=["*"],            # allow all headers
)

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


@app.get("/api/user/package/downloads/chart")
async def package_downloads_chart(
    package: str = Query(..., description="Package name"),
    range_: str = Query("last-month", alias="range", description="Range: last-day | last-week | last-month or YYYY-MM-DD:YYYY-MM-DD")
):
    """
    Get downloads vs time for a package.
    Returns array of objects: [{date: 'YYYY-MM-DD', downloads: N}, ...]
    """
    key = f"chart:{package}:{range_}"
    cached = get_from_cache(key)
    if cached:
        return JSONResponse(content=cached)

    url = f"https://api.npmjs.org/downloads/range/{range_}/{package}"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url)
        if r.status_code == 404:
            raise HTTPException(status_code=404, detail="Package not found or no downloads")
        r.raise_for_status()
        data = r.json()

    downloads_data: List[Dict[str, Any]] = data.get("downloads", [])
    chart_data = [{"date": d["day"], "downloads": d["downloads"]} for d in downloads_data]

    set_cache(key, chart_data)
    return JSONResponse(content=chart_data)

@app.get("/api/health")
async def health():
    return {"status": "ok"}

@app.get("/api/ping")
async def ping():
    return {"status": "pong"}

@app.get("/", response_class=HTMLResponse)
async def root():
    return """
    <html>
        <head>
            <title>NPM Package API</title>
        </head>
        <body style="font-family: Arial, sans-serif; text-align: center; margin-top: 50px;">
            <h1>Welcome to the NPM Package API 🚀</h1>
            <p>Use the endpoints to explore package details.</p>
            <p>Example: <code>/api/user/&lt;username&gt;</code></p>
        </body>
    </html>
    """

@app.get("/api/about", response_class=HTMLResponse)
async def about():
    html = """
    <!doctype html>
    <html lang="en">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width,initial-scale=1" />
      <title>About — Avijit Sen</title>
      <style>
        :root{
          --bg:#f9fafb;
          --card:#ffffff;
          --border:#e5e7eb;
          --muted:#6b7280;
          --accent:#2563eb;
          --radius:14px;
        }
        html,body{height:100%;margin:0;font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial;}
        body{
          background:var(--bg);
          color:#111827;
          display:flex;
          align-items:center;
          justify-content:center;
          padding:32px;
        }
        .card{
          background:var(--card);
          border: 1px solid var(--border);
          box-shadow: 0 4px 16px rgba(0,0,0,0.05);
          border-radius: var(--radius);
          width:100%;
          max-width:880px;
          padding:28px;
          display:grid;
          grid-template-columns: 1fr 300px;
          gap:20px;
          align-items:start;
        }
        .left h1{margin:0;font-size:20px;letter-spacing:0.2px;}
        .subtitle{color:var(--muted);margin-top:6px;font-size:13px;}
        .bio{margin-top:16px;color:#374151;line-height:1.45;font-size:14px;}
        .links{margin-top:18px;display:flex;flex-wrap:wrap;gap:10px;}
        .link{
          display:inline-flex;align-items:center;gap:10px;padding:10px 12px;background:#f3f4f6;border-radius:10px;border:1px solid var(--border);
          text-decoration:none;color:#111827;font-size:14px;font-weight:500;
        }
        .link svg{width:18px;height:18px;opacity:0.9;}
        .right{
          background:#f9fafb;
          border-radius:12px;padding:14px;border:1px solid var(--border);
        }
        .meta-row{display:flex;align-items:center;justify-content:space-between;gap:10px;}
        .contact{margin-top:12px;font-size:14px;color:var(--muted);}
        .badge{
          display:inline-flex;align-items:center;gap:8px;padding:6px 10px;border-radius:999px;background:#dbeafe;color:var(--accent);font-weight:600;font-size:13px;
        }
        a:hover{opacity:0.9;transform:translateY(-1px);transition:all .12s ease}
        footer{margin-top:18px;color:var(--muted);font-size:12px}
        @media (max-width:820px){
          .card{grid-template-columns:1fr; padding:18px;}
        }
      </style>
    </head>
    <body>
      <article class="card" role="article" aria-label="About Avijit Sen">
        <section class="left">
          <h1>Avijit Sen <span style="font-size:13px;color:var(--muted);font-weight:600;margin-left:8px">Developer • Trading Systems</span></h1>
          <div class="subtitle">FastAPI • React • MongoDB • Redis • Realtime systems</div>

          <p class="bio">
            Hi — I build realtime trading and analytics systems, developer tools, and automation that scale.
            I enjoy clean architecture, modular services and turning trading ideas into production-grade systems.
          </p>

          <div class="links" aria-label="External links">
            <a class="link" href="https://www.linkedin.com/in/avijit-sen-69a00b1b9/" target="_blank" rel="noopener noreferrer">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 8a6 6 0 0 1 6 6v6h-4v-6a2 2 0 0 0-4 0v6h-4V6h4v2"/></svg>
              LinkedIn
            </a>

            <a class="link" href="https://github.com/ashavijit" target="_blank" rel="noopener noreferrer">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2"><path d="M12 2C8 2 4.7 4.3 4.7 8.1c0 2.5 1.6 4.6 3.8 5.3.3.1.4-.1.4-.3v-1.1c-1.6.3-1.9-.7-1.9-.7-.3-.7-.8-.9-.8-.9-.7-.5.1-.5.1-.5.8.1 1.3.8 1.3.8.6 1 1.6.7 2 .5.1-.4.3-.7.6-.9-1.3-.1-2.6-.7-2.6-3 0-.7.3-1.3.8-1.8-.1-.2-.4-1 .1-2 0 0 .7-.2 2.2.8.6-.2 1.2-.3 1.8-.3.6 0 1.2.1 1.8.3 1.4-1 2.2-.8 2.2-.8.5 1 .2 1.8.1 2 .5.5.8 1.1.8 1.8 0 2.3-1.3 2.9-2.6 3 .4.3.7.9.7 1.8v2.7c0 .2.1.4.4.3 2.2-.7 3.8-2.8 3.8-5.3C19.3 4.3 16 2 12 2z"/></svg>
              GitHub
            </a>

            <a class="link" href="https://twitter.com/AvijitSen123" target="_blank" rel="noopener noreferrer">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2"><path d="M23 3a10.9 10.9 0 0 1-3.14 1.53A4.48 4.48 0 0 0 22.43.36a9.06 9.06 0 0 1-2.86 1.1A4.52 4.52 0 0 0 16.11 0c-2.5 0-4.52 2.2-4.52 4.9 0 .38.04.76.12 1.12A12.86 12.86 0 0 1 1.64.9a4.81 4.81 0 0 0-.61 2.48c0 1.71.82 3.22 2.07 4.11A4.48 4.48 0 0 1 .96 7v.06c0 2.39 1.8 4.38 4.18 4.83a4.5 4.5 0 0 1-2.05.08c.58 1.85 2.24 3.2 4.21 3.24A9.06 9.06 0 0 1 0 19.54a12.8 12.8 0 0 0 6.92 2.03c8.3 0 12.84-6.54 12.84-12.2 0-.19 0-.39-.02-.58A8.83 8.83 0 0 0 23 3z"/></svg>
              Twitter
            </a>

            <a class="link" href="https://avijit-sen.vercel.app/" target="_blank" rel="noopener noreferrer">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2"><path d="M3 12l3-2 4 2 7-4 4 2v6l-4 2-7-4-4 2-3-2z"/></svg>
              Portfolio
            </a>
          </div>

        </section>

        <aside class="right" aria-label="Contact & meta">
          <div class="meta-row">
            <div>
              <div style="font-weight:700">Contact</div>
              <div class="contact">avijitsen24.me@gmail.com<br/>+91 98321 56744</div>
            </div>
            <div class="badge" title="Availability">
              <svg width="10" height="10" viewBox="0 0 10 10"><circle cx="5" cy="5" r="5" fill="#2563eb" /></svg>
              Available
            </div>
          </div>

          <div style="margin-top:14px;font-size:13px;color:var(--muted)">
            Quick links
            <ul style="margin:10px 0 0 18px;padding:0;line-height:1.7">
              <li><a style="color:inherit;text-decoration:none" href="mailto:avijitsen24.me@gmail.com">Email me</a></li>
              <li><a style="color:inherit;text-decoration:none" href="tel:+919832156744">Call</a></li>
            </ul>
          </div>

          <div style="margin-top:16px;font-size:12px;color:var(--muted)">
            <strong>Note</strong>
            <div style="margin-top:8px">This page is optimized for readability and quick linking. Use the JSON endpoint for programmatic consumption.</div>
          </div>
        </aside>
      </article>
    </body>
    </html>
    """
    return HTMLResponse(content=html, status_code=200)
