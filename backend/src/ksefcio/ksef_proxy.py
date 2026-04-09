import os

import httpx
from fastapi import APIRouter, Depends, Request, Response

from ksefcio.auth import get_authenticated_user

router = APIRouter(prefix="/api/ksef")

KSEF_BASE_URL = os.environ.get("KSEF_API_URL", "https://api-test.ksef.mf.gov.pl/v2")

_client: httpx.AsyncClient | None = None


async def get_ksef_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=KSEF_BASE_URL, timeout=30.0)
    return _client


async def close_ksef_client():
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


FORWARDED_HEADERS = ("authorization", "content-type", "accept")


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def ksef_proxy(path: str, request: Request, _user=Depends(get_authenticated_user)):
    client = await get_ksef_client()

    headers = {}
    for key in FORWARDED_HEADERS:
        if val := request.headers.get(key):
            headers[key] = val

    body = await request.body()

    response = await client.request(
        method=request.method,
        url=f"/{path}",
        headers=headers,
        content=body if body else None,
        params=dict(request.query_params),
    )

    return Response(
        content=response.content,
        status_code=response.status_code,
        headers={"content-type": response.headers.get("content-type", "application/json")},
    )
