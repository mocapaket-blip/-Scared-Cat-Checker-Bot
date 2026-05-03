"""
Проверка владения NFT через tonapi.io.
Документация: https://tonapi.io/api-v2  (GET /v2/accounts/{account_id}/nfts)

Поддерживает адреса в форматах:
  • EQ.../UQ... — user-friendly base64 (из TON Connect через бот)
  • 0:hexstring — raw-формат (из TON Connect через Mini App)
"""
import logging
from typing import Optional
from urllib.parse import quote

import aiohttp

from config import settings

log = logging.getLogger(__name__)


class TonApiError(RuntimeError):
    pass


def _normalize(addr: Optional[str]) -> str:
    return (addr or "").strip().lower()


def _encode_address(addr: str) -> str:
    """
    URL-кодирует адрес для вставки в путь tonapi.
    EQ.../UQ... — оставляем как есть (безопасные символы).
    0:hex        — кодируем двоеточие → %3A.
    """
    if addr.startswith("0:") or addr.startswith("-1:"):
        return quote(addr, safe="")
    return addr


async def user_owns_collection_nft(
    wallet_address: str,
    collection_address: str = settings.NFT_COLLECTION_ADDRESS,
    encoded_address: Optional[str] = None,
) -> bool:
    """
    Возвращает True, если на кошельке есть хотя бы одна NFT
    из указанной коллекции.

    encoded_address: если уже закодирован снаружи — используем его.
    """
    if not wallet_address:
        return False

    addr_in_url = encoded_address or _encode_address(wallet_address)
    url = f"{settings.TONAPI_BASE_URL}/v2/accounts/{addr_in_url}/nfts"

    params  = {"collection": collection_address, "limit": 1, "indirect_ownership": "false"}
    headers = {"Accept": "application/json"}
    if settings.TONAPI_KEY:
        headers["Authorization"] = f"Bearer {settings.TONAPI_KEY}"

    log.debug("tonapi request: %s | params: %s", url, params)

    timeout = aiohttp.ClientTimeout(total=15)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params, headers=headers) as resp:
                if resp.status == 404:
                    return False
                if resp.status != 200:
                    text = await resp.text()
                    raise TonApiError(f"tonapi {resp.status}: {text[:300]}")
                data = await resp.json()
    except aiohttp.ClientError as e:
        raise TonApiError(str(e)) from e

    items  = data.get("nft_items") or []
    target = _normalize(collection_address)

    log.info("tonapi returned %d NFT items for %s", len(items), wallet_address)

    for item in items:
        col = (item.get("collection") or {}).get("address")
        if _normalize(col) == target:
            return True

    # Если фильтр по коллекции отработал на стороне API — items уже отфильтрованы
    return len(items) > 0
