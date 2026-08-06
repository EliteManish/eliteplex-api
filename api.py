import re
import json
import httpx
from urllib.parse import urlencode
from typing import Optional, Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse


# =========================================================
# APP
# =========================================================

app = FastAPI(
    title="MovieBox API Pro",
    description="Movie metadata and authorized playback API",
    version="3.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================
# CONFIG
# =========================================================

BASE_URL = "https://moviebox.ph"

API_BASE = (
    "https://h5-api.aoneroom.com/"
    "wefeed-h5api-bff"
)

STREAM_BASE = (
    "https://h5.aoneroom.com/"
    "wefeed-h5-bff"
)


# =========================================================
# TOKEN
# =========================================================

_bearer_token: Optional[str] = None


# =========================================================
# HEADERS
# =========================================================

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/148.0.0.0 Safari/537.36"
    ),
    "Referer": "https://moviebox.ph/",
    "Origin": "https://moviebox.ph",

    "X-Client-Info": json.dumps({
        "timezone": "Asia/Kolkata"
    }),

    "X-Request-Lang": "en",

    "Accept": "application/json",
    "Content-Type": "application/json",

    "sec-ch-ua": (
        '"Chromium";v="148", '
        '"Google Chrome";v="148", '
        '"Not/A)Brand";v="99"'
    ),

    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',

    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "cross-site",
}


PLAYER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/148.0.0.0 Safari/537.36"
    ),

    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",

    "Origin": "https://h5.aoneroom.com",

    "sec-ch-ua": (
        '"Chromium";v="148", '
        '"Google Chrome";v="148", '
        '"Not/A)Brand";v="99"'
    ),

    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',

    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}


# =========================================================
# HELPERS
# =========================================================

def safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return None


def extract_token_from_response(response: httpx.Response):
    global _bearer_token

    # -----------------------------------------
    # x-user header
    # -----------------------------------------

    x_user = response.headers.get("x-user")

    if x_user:
        try:
            parsed = json.loads(x_user)

            token = parsed.get("token")

            if token:
                _bearer_token = token
                return token

        except Exception:
            pass

    # -----------------------------------------
    # set-cookie
    # -----------------------------------------

    set_cookie = response.headers.get("set-cookie", "")

    if set_cookie:

        patterns = [
            r"token=([^;]+)",
            r"access_token=([^;]+)",
            r"Authorization=([^;]+)",
        ]

        for pattern in patterns:

            match = re.search(pattern, set_cookie)

            if match:
                token = match.group(1)

                if token:
                    _bearer_token = token
                    return token

    return None


# =========================================================
# GET TOKEN
# =========================================================

async def _get_bearer_token(force_refresh: bool = False) -> str:

    global _bearer_token

    if _bearer_token and not force_refresh:
        return _bearer_token

    url = f"{API_BASE}/home?host=moviebox.ph"

    try:

        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=30
        ) as client:

            response = await client.get(
                url,
                headers=DEFAULT_HEADERS
            )

            extract_token_from_response(response)

    except Exception:
        return ""

    return _bearer_token or ""


# =========================================================
# GENERIC API REQUEST
# =========================================================

async def _make_request(
    url: str,
    method: str = "GET",
    payload: Optional[dict] = None,
    custom_headers: Optional[dict] = None
):

    global _bearer_token

    token = await _get_bearer_token()

    headers = {
        **DEFAULT_HEADERS
    }

    if token:
        headers["Authorization"] = f"Bearer {token}"

    if custom_headers:
        headers.update(custom_headers)

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=30
    ) as client:

        try:

            if method.upper() == "POST":

                response = await client.post(
                    url,
                    headers=headers,
                    json=payload
                )

            else:

                response = await client.get(
                    url,
                    headers=headers
                )

            # Refresh token if upstream sends one
            new_token = extract_token_from_response(response)

            if response.status_code == 401 and not new_token:

                token = await _get_bearer_token(
                    force_refresh=True
                )

                if token:
                    headers["Authorization"] = (
                        f"Bearer {token}"
                    )

                    if method.upper() == "POST":

                        response = await client.post(
                            url,
                            headers=headers,
                            json=payload
                        )

                    else:

                        response = await client.get(
                            url,
                            headers=headers
                        )

            if response.status_code != 200:

                raise HTTPException(
                    status_code=502,
                    detail={
                        "message": "Upstream API error",
                        "status_code": response.status_code,
                        "response": response.text[:2000]
                    }
                )

            result = safe_json(response)

            if result is None:

                raise HTTPException(
                    status_code=502,
                    detail={
                        "message": "Upstream returned invalid JSON",
                        "status_code": response.status_code
                    }
                )

            return result

        except HTTPException:
            raise

        except httpx.TimeoutException:

            raise HTTPException(
                status_code=504,
                detail="Upstream request timed out"
            )

        except httpx.RequestError as e:

            raise HTTPException(
                status_code=502,
                detail=f"Upstream connection failed: {str(e)}"
            )

        except Exception as e:

            raise HTTPException(
                status_code=502,
                detail=f"Request failed: {str(e)}"
            )


# =========================================================
# DASHBOARD
# =========================================================

@app.get("/", response_class=HTMLResponse)
async def dashboard():

    return HTMLResponse("""
<!DOCTYPE html>
<html lang="en">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width,initial-scale=1.0"
>

<title>MovieBox API Pro</title>

<style>

* {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}

body {
    min-height: 100vh;
    background:
        radial-gradient(
            circle at 10% 10%,
            rgba(255,61,113,.15),
            transparent 35%
        ),
        radial-gradient(
            circle at 90% 90%,
            rgba(51,102,255,.15),
            transparent 35%
        ),
        #07080c;

    color: white;
    font-family: Arial, sans-serif;
}

.container {
    width: min(1100px, 92%);
    margin: auto;
    padding: 60px 0;
}

header {
    text-align: center;
    margin-bottom: 55px;
}

.badge {
    display: inline-block;
    padding: 8px 16px;
    border-radius: 50px;
    background: linear-gradient(
        90deg,
        #ff3d71,
        #3366ff
    );
    font-size: 13px;
    font-weight: bold;
    margin-bottom: 20px;
}

h1 {
    font-size: clamp(40px, 8vw, 70px);
    margin-bottom: 10px;
}

.subtitle {
    color: #888;
    font-size: 18px;
}

.grid {
    display: grid;
    grid-template-columns:
        repeat(auto-fit, minmax(280px, 1fr));
    gap: 20px;
}

.card {
    padding: 28px;
    border-radius: 22px;

    background:
        rgba(255,255,255,.04);

    border:
        1px solid rgba(255,255,255,.08);

    backdrop-filter: blur(15px);
}

.card h2 {
    margin-bottom: 12px;
}

.card p {
    color: #999;
    line-height: 1.6;
    margin-bottom: 20px;
}

.endpoint {
    background: #000;
    padding: 13px;
    border-radius: 10px;
    color: #00e5ff;
    font-family: monospace;
    font-size: 13px;
    word-break: break-all;
    margin-bottom: 18px;
}

.btn {
    display: block;
    text-align: center;
    padding: 13px;
    background: white;
    color: black;
    border-radius: 10px;
    text-decoration: none;
    font-weight: bold;
}

footer {
    text-align: center;
    margin-top: 60px;
    color: #555;
}

</style>

</head>

<body>

<div class="container">

<header>

<div class="badge">
    API v3.0.0
</div>

<h1>MovieBox Pro</h1>

<div class="subtitle">
    Metadata & Playback API
</div>

</header>


<div class="grid">

<div class="card">

<h2>Home</h2>

<p>
Get home page sections and content.
</p>

<div class="endpoint">
/home
</div>

<a
    class="btn"
    href="/home"
    target="_blank"
>
Test
</a>

</div>


<div class="card">

<h2>Search</h2>

<p>
Search movies and series.
</p>

<div class="endpoint">
/search?q=Attack%20on%20Titan
</div>

<a
    class="btn"
    href="/search?q=Attack%20on%20Titan"
    target="_blank"
>
Test
</a>

</div>


<div class="card">

<h2>Detail</h2>

<p>
Get detailed metadata for a title.
</p>

<div class="endpoint">
/detail/{slug}
</div>

<a
    class="btn"
    href="/detail/wizards-beyond-waverly-place-MsYzpWu2wF8"
    target="_blank"
>
Test
</a>

</div>


<div class="card">

<h2>Playback Debug</h2>

<p>
Inspect the authorized playback response
and identify missing resources.
</p>

<div class="endpoint">
/api/stream/{subject_id}
</div>

<a
    class="btn"
    href="/api/stream/7276411159472210592?detail_path=wizards-beyond-waverly-place-MsYzpWu2wF8&se=3&ep=1"
    target="_blank"
>
Test
</a>

</div>

</div>


<footer>
MovieBox API Pro
</footer>

</div>

</body>

</html>
""")


# =========================================================
# HOME
# =========================================================

@app.get("/home")
async def get_home():

    url = f"{API_BASE}/home?host=moviebox.ph"

    data = await _make_request(url)

    sections = []

    operating_list = (
        data
        .get("data", {})
        .get("operatingList", [])
        or []
    )

    for operation in operating_list:

        operation_type = operation.get("type")

        title = operation.get(
            "title",
            "Featured"
        )

        # -----------------------------------------
        # BANNER
        # -----------------------------------------

        if operation_type == "BANNER":

            items = []

            banner_items = (
                operation
                .get("banner", {})
                .get("items", [])
            )

            for item in banner_items:

                subject = item.get(
                    "subject"
                ) or {}

                item_title = (
                    item.get("title")
                    or subject.get("title")
                )

                if not item_title:
                    continue

                if "Communities" in item_title:
                    continue

                items.append({
                    "name": item_title,

                    "poster_url": (
                        item.get("image", {}).get("url")
                        or
                        subject.get("cover", {}).get("url")
                    ),

                    "slug": (
                        item.get("detailPath")
                        or subject.get("detailPath")
                    ),

                    "subject_id": subject.get(
                        "subjectId"
                    ),

                    "badge": subject.get(
                        "corner"
                    )
                })

            sections.append({
                "section": "Banner",
                "count": len(items),
                "items": items
            })

        # -----------------------------------------
        # SUBJECT LIST
        # -----------------------------------------

        elif operation_type in [
            "SUBJECTS_MOVIE",
            "SUBJECTS_TV",
            "SUBJECTS_ANIMATION"
        ]:

            items = []

            for subject in (
                operation.get("subjects", [])
                or []
            ):

                items.append({
                    "name": subject.get("title"),

                    "poster_url": (
                        subject
                        .get("cover", {})
                        .get("url")
                    ),

                    "slug": subject.get(
                        "detailPath"
                    ),

                    "subject_id": subject.get(
                        "subjectId"
                    ),

                    "badge": subject.get(
                        "corner"
                    ),

                    "rating": subject.get(
                        "imdbRatingValue"
                    )
                })

            sections.append({
                "section": title,
                "count": len(items),
                "items": items
            })

    return {
        "status": "success",
        "sections": sections
    }


# =========================================================
# CATEGORY
# =========================================================

async def _get_category_data(
    tab_id: int,
    page: int = 1,
    per_page: int = 24,
    sort: str = "RECOMMEND"
):

    url = f"{API_BASE}/subject/filter"

    payload = {
        "tabId": tab_id,

        "filter": {
            "sort": sort,
            "genre": "ALL",
            "country": "ALL",
            "year": "ALL",
            "language": "ALL"
        },

        "page": page,
        "perPage": per_page
    }

    data = await _make_request(
        url,
        method="POST",
        payload=payload
    )

    inner = data.get("data", {}) or {}

    raw_items = (
        inner.get("items")
        or inner.get("subjects")
        or []
    )

    items = []

    for subject in raw_items:

        release_date = subject.get(
            "releaseDate"
        )

        items.append({
            "name": subject.get("title"),

            "poster_url": (
                subject
                .get("cover", {})
                .get("url")
            ),

            "slug": subject.get(
                "detailPath"
            ),

            "subject_id": subject.get(
                "subjectId"
            ),

            "badge": subject.get(
                "corner"
            ),

            "rating": subject.get(
                "imdbRatingValue"
            ),

            "year": (
                release_date[:4]
                if release_date
                else None
            )
        })

    pager = inner.get(
        "pager",
        {}
    ) or {}

    total = (
        pager.get("totalCount")
        or inner.get("total")
        or len(items)
    )

    return {
        "page": page,
        "per_page": per_page,
        "total": total,
        "items": items
    }


# =========================================================
# MOVIES
# =========================================================

@app.get("/movies")
async def get_movies(
    page: int = 1,
    sort: str = "RECOMMEND"
):

    return await _get_category_data(
        tab_id=2,
        page=page,
        sort=sort
    )


# =========================================================
# TV SERIES
# =========================================================

@app.get("/tv-series")
async def get_tv_series(
    page: int = 1,
    sort: str = "RECOMMEND"
):

    return await _get_category_data(
        tab_id=5,
        page=page,
        sort=sort
    )


# =========================================================
# ANIMATION
# =========================================================

@app.get("/animation")
async def get_animation(
    page: int = 1,
    sort: str = "RECOMMEND"
):

    return await _get_category_data(
        tab_id=8,
        page=page,
        sort=sort
    )


# =========================================================
# SEARCH SUGGESTIONS
# =========================================================

@app.get("/search/suggest")
async def get_search_suggestions(
    q: str = Query(..., min_length=1)
):

    url = f"{API_BASE}/subject/search-suggest"

    payload = {
        "keyword": q,
        "perPage": 10
    }

    data = await _make_request(
        url,
        method="POST",
        payload=payload
    )

    inner = data.get(
        "data",
        {}
    ) or {}

    raw = (
        inner.get("items")
        or inner.get("list")
        or []
    )

    suggestions = []

    for item in raw:

        subject = item.get(
            "subject"
        ) or {}

        suggestions.append({

            "title": (
                subject.get("title")
                or item.get("word")
                or item.get("title")
            ),

            "slug": (
                subject.get("detailPath")
                or item.get("detailPath")
            ),

            "subject_id": (
                subject.get("subjectId")
                or item.get("subjectId")
            )
        })

    return {
        "query": q,
        "suggestions": suggestions
    }


# =========================================================
# SEARCH
# =========================================================

@app.get("/search")
async def search(
    q: str = Query(..., min_length=1),
    page: int = 1
):

    url = f"{API_BASE}/subject/search"

    payload = {
        "keyword": q,
        "page": page,
        "perPage": 20
    }

    data = await _make_request(
        url,
        method="POST",
        payload=payload
    )

    inner = data.get(
        "data",
        {}
    ) or {}

    raw = (
        inner.get("items")
        or inner.get("list")
        or []
    )

    items = []

    for subject in raw:

        items.append({

            "name": subject.get(
                "title"
            ),

            "poster_url": (
                subject
                .get("cover", {})
                .get("url")
            ),

            "slug": subject.get(
                "detailPath"
            ),

            "subject_id": subject.get(
                "subjectId"
            )
        })

    pager = inner.get(
        "pager",
        {}
    ) or {}

    total = (
        pager.get("totalCount")
        or inner.get("total")
        or len(items)
    )

    return {
        "query": q,
        "page": page,
        "total": total,
        "items": items
    }


# =========================================================
# DETAIL
# =========================================================

@app.get("/detail/{slug}")
async def get_movie_detail(
    slug: str
):

    url = (
        f"{API_BASE}/detail"
        f"?detailPath={slug}"
    )

    return await _make_request(url)


# =========================================================
# PLAYBACK DEBUG
# =========================================================

@app.get("/api/stream/{subject_id}")
async def get_stream_sources(

    subject_id: str,

    detail_path: str = Query(
        "",
        description="detailPath from metadata"
    ),

    se: int = Query(
        0,
        ge=0
    ),

    ep: int = Query(
        0,
        ge=0
    )
):

    # -----------------------------------------------------
    # IMPORTANT:
    # Build query parameters with urlencode instead of
    # manually concatenating them.
    # -----------------------------------------------------

    params = {
        "subjectId": subject_id,
        "se": se,
        "ep": ep,
        "detailPath": detail_path
    }

    query_string = urlencode(params)

    play_url = (
        f"{STREAM_BASE}/web/subject/play"
        f"?{query_string}"
    )

    # -----------------------------------------------------
    # Player page URL
    # -----------------------------------------------------

    player_params = {
        "id": subject_id,
        "type": "/movie/detail",
        "detailSe": se,
        "detailEp": ep,
        "lang": "en"
    }

    player_url = (
        "https://h5.aoneroom.com/"
        "spa/videoPlayPage/movies/"
        f"{detail_path}"
        f"?{urlencode(player_params)}"
    )

    headers = {
        **PLAYER_HEADERS,
        "Referer": player_url
    }

    # -----------------------------------------------------
    # Request upstream
    # -----------------------------------------------------

    try:

        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=30
        ) as client:

            response = await client.get(
                play_url,
                headers=headers
            )

    except httpx.TimeoutException:

        raise HTTPException(
            status_code=504,
            detail="Playback service timed out"
        )

    except httpx.RequestError as e:

        raise HTTPException(
            status_code=502,
            detail=f"Playback connection failed: {str(e)}"
        )

    # -----------------------------------------------------
    # Non-200 response
    # -----------------------------------------------------

    if response.status_code != 200:

        return {
            "status": "upstream_error",

            "request": {
                "subject_id": subject_id,
                "detail_path": detail_path,
                "se": se,
                "ep": ep
            },

            "upstream": {
                "status_code": response.status_code,
                "content_type": response.headers.get(
                    "content-type"
                ),
                "response": response.text[:5000]
            }
        }

    # -----------------------------------------------------
    # JSON
    # -----------------------------------------------------

    result = safe_json(response)

    if result is None:

        return {
            "status": "invalid_json",

            "request": {
                "subject_id": subject_id,
                "detail_path": detail_path,
                "se": se,
                "ep": ep
            },

            "upstream": {
                "status_code": response.status_code,
                "content_type": response.headers.get(
                    "content-type"
                ),
                "response": response.text[:5000]
            }
        }

    # -----------------------------------------------------
    # Extract data
    # -----------------------------------------------------

    data = result.get(
        "data",
        {}
    ) or {}

    streams = (
        data.get("streams")
        or []
    )

    hls = (
        data.get("hls")
        or []
    )

    dash = (
        data.get("dash")
        or []
    )

    # -----------------------------------------------------
    # Normalize stream metadata
    # -----------------------------------------------------

    normalized_streams = []

    for stream in streams:

        if not isinstance(stream, dict):
            continue

        resolution = (
            stream.get("resolutions")
            or stream.get("resolution")
        )

        normalized_streams.append({

            "id": stream.get("id"),

            "resolution": (
                f"{resolution}p"
                if resolution
                else "HD"
            ),

            "format": stream.get(
                "format",
                "mp4"
            ),

            "url": stream.get(
                "url"
            ),

            "size": stream.get(
                "size"
            ),

            "duration": stream.get(
                "duration"
            ),

            "codec": stream.get(
                "codecName"
            )
        })

    # -----------------------------------------------------
    # Final response
    # -----------------------------------------------------

    has_resource = (
        data.get("hasResource", False)
        or bool(normalized_streams)
        or bool(hls)
        or bool(dash)
    )

    return {

        "status": "success",

        "request": {
            "subject_id": subject_id,
            "detail_path": detail_path,
            "se": se,
            "ep": ep
        },

        "playback_page": player_url,

        "has_resource": has_resource,

        "sources": normalized_streams,

        "hls": hls,

        "dash": dash,

        "free_episodes": data.get(
            "freeNum"
        ),

        "limited": data.get(
            "limited",
            False
        ),

        "available": {
            "mp4": len(normalized_streams) > 0,
            "hls": len(hls) > 0,
            "dash": len(dash) > 0
        },

        "diagnostic": (
            None
            if has_resource
            else
            "Upstream returned no playback resource "
            "for this subject/season/episode."
        )
    }


# =========================================================
# CAPTIONS
# =========================================================

@app.get("/api/stream/{subject_id}/captions")
async def get_captions(

    subject_id: str,

    detail_path: str = Query(""),

    se: int = Query(
        0,
        ge=0
    ),

    ep: int = Query(
        0,
        ge=0
    )
):

    params = {
        "subjectId": subject_id,
        "se": se,
        "ep": ep,
        "detailPath": detail_path
    }

    play_url = (
        f"{STREAM_BASE}/web/subject/play"
        f"?{urlencode(params)}"
    )

    player_params = {
        "id": subject_id,
        "type": "/movie/detail",
        "detailSe": se,
        "detailEp": ep,
        "lang": "en"
    }

    player_url = (
        "https://h5.aoneroom.com/"
        "spa/videoPlayPage/movies/"
        f"{detail_path}"
        f"?{urlencode(player_params)}"
    )

    headers = {
        **PLAYER_HEADERS,
        "Referer": player_url
    }

    try:

        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=30
        ) as client:

            response = await client.get(
                play_url,
                headers=headers
            )

    except Exception as e:

        raise HTTPException(
            status_code=502,
            detail=f"Playback request failed: {str(e)}"
        )

    if response.status_code != 200:

        return {
            "subject_id": subject_id,
            "se": se,
            "ep": ep,
            "count": 0,
            "captions": [],
            "upstream_status": response.status_code
        }

    play_json = safe_json(response)

    if not play_json:

        return {
            "subject_id": subject_id,
            "se": se,
            "ep": ep,
            "count": 0,
            "captions": []
        }

    play_data = play_json.get(
        "data",
        {}
    ) or {}

    streams = (
        play_data.get("streams")
        or []
    )

    dash = (
        play_data.get("dash")
        or []
    )

    stream_id = None
    stream_format = None

    # -----------------------------------------------------
    # Prefer MP4 stream
    # -----------------------------------------------------

    for stream in streams:

        if not isinstance(stream, dict):
            continue

        if stream.get("id"):

            stream_id = stream.get("id")

            stream_format = stream.get(
                "format",
                "MP4"
            )

            break

    # -----------------------------------------------------
    # Fallback DASH
    # -----------------------------------------------------

    if not stream_id:

        for item in dash:

            if not isinstance(item, dict):
                continue

            if item.get("id"):

                stream_id = item.get("id")

                stream_format = item.get(
                    "format",
                    "DASH"
                )

                break

    if not stream_id:

        return {
            "subject_id": subject_id,
            "se": se,
            "ep": ep,
            "count": 0,
            "captions": []
        }

    # -----------------------------------------------------
    # Caption request
    # -----------------------------------------------------

    caption_params = {
        "format": stream_format,
        "id": stream_id,
        "subjectId": subject_id,
        "detailPath": detail_path
    }

    caption_url = (
        f"{API_BASE}/subject/caption"
        f"?{urlencode(caption_params)}"
    )

    caption_data = await _make_request(
        caption_url
    )

    inner = caption_data.get(
        "data",
        {}
    )

    if isinstance(inner, dict):

        captions = (
            inner.get("captions")
            or []
        )

    elif isinstance(inner, list):

        captions = inner

    else:

        captions = []

    return {
        "subject_id": subject_id,
        "se": se,
        "ep": ep,
        "stream_id": stream_id,
        "format": stream_format,
        "count": len(captions),
        "captions": captions
    }


# =========================================================
# HEALTH CHECK
# =========================================================

@app.get("/health")
async def health():

    return {
        "status": "ok",
        "version": "3.0.0"
    }


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        "api:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
