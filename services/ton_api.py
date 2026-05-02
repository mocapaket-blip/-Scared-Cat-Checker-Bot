"""
Проверка владения NFT через tonapi.io.

Документация: https://tonapi.io/api-v2  (GET /v2/accounts/{account_id}/nfts)
"""
import logging
from typing import Optional

import aiohttp

from config import settings

log = logging.getLogger(__name__)


class TonApiError(RuntimeError):
    pass


def _normalize(addr: Optional[str]) -> str:
    return (addr or "").strip().lower()


async def user_owns_collection_nft(
    wallet_address: str,
    collection_address: str = settings.NFT_COLLECTION_ADDRESS,
) -> bool:
    """
    Возвращает True, если на кошельке есть хотя бы одна NFT
    из указанной коллекции.
    """
    if not wallet_address:
        return False

    url = f"{settings.TONAPI_BASE_URL}/v2/accounts/{wallet_address}/nfts"
    params = {
        "collection": collection_address,
        "limit": 1,
        "indirect_ownership": "false",
    }
    headers = {"Accept": "application/json"}
    if settings.TONAPI_KEY:
        headers["Authorization"] = f"Bearer {settings.TONAPI_KEY}"

    timeout = aiohttp.ClientTimeout(total=15)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params, headers=headers) as resp:
                if resp.status == 404:
                    return False
                if resp.status != 200:
                    text = await resp.text()
                    raise TonApiError(f"tonapi {resp.status}: {text[:200]}")
                data = await resp.json()
    except aiohttp.ClientError as e:
        raise TonApiError(str(e)) from e

    items = data.get("nft_items") or []
    target = _normalize(collection_address)
    for item in items:
        col = (item.get("collection") or {}).get("address")
        if _normalize(col) == target:
            return True
    return False
