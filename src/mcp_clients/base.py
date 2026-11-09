import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

import httpx
from pydantic import BaseModel


class Rule(BaseModel):
    id: str
    kind: str
    spec: Dict[str, Any]


class BaseMCPClient:
    def __init__(self, base_url: str, name: str, http: Optional[httpx.AsyncClient] = None):
        self.base_url = base_url.rstrip("/")
        self.name = name
        self.http = http or httpx.AsyncClient(timeout=10.0)
        self._cache: List[Rule] = []
        self._callbacks: List[Callable[[List[Dict[str, Any]]], None]] = []
        self._poll_task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    async def fetch_rules(self) -> List[Rule]:
        url = f"{self.base_url}/rules"
        resp = await self.http.get(url)
        resp.raise_for_status()
        items = resp.json()
        self._cache = [Rule(**it) for it in items]
        return self._cache

    def get_cached(self) -> List[Dict[str, Any]]:
        return [r.dict() for r in self._cache]

    def on_update(self, cb: Callable[[List[Dict[str, Any]]], None]) -> None:
        self._callbacks.append(cb)

    async def apply_rules(self, rules_payload: List[Dict[str, Any]]) -> None:
        self._cache = [Rule(**it) for it in rules_payload]
        await self._notify()

    async def _notify(self) -> None:
        for cb in list(self._callbacks):
            try:
                cb(self.get_cached())
            except Exception:
                logging.exception("MCP client callback failed")

    async def _poll_loop(self, interval: float) -> None:
        while not self._stop.is_set():
            try:
                await self.fetch_rules()
                await self._notify()
            except Exception:
                logging.exception("%s poll failed", self.name)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                continue

    def start_polling(self, interval: float = 30.0) -> None:
        if not self._poll_task:
            self._stop.clear()
            self._poll_task = asyncio.create_task(self._poll_loop(interval))

    async def stop_polling(self) -> None:
        if self._poll_task:
            self._stop.set()
            await self._poll_task
            self._poll_task = None

    async def close(self) -> None:
        await self.stop_polling()
        await self.http.aclose()
