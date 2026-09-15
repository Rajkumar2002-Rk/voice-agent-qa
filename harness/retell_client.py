"""Thin Retell REST client — only the endpoints this harness actually uses."""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

BASE = os.getenv("RETELL_BASE_URL", "https://api.retellai.com")


class RetellError(RuntimeError):
    pass


class RetellClient:
    def __init__(self, api_key: str | None = None, timeout: float = 30.0):
        self.api_key = api_key or os.getenv("RETELL_API_KEY", "")
        if not self.api_key:
            raise RetellError(
                "RETELL_API_KEY is not set. Copy .env.example to .env and fill it in "
                "(see docs/retell-setup.md)."
            )
        self._c = httpx.Client(
            base_url=BASE,
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
            timeout=timeout,
        )

    # ---- plumbing ---------------------------------------------------------

    def _req(self, method: str, path: str, **kw) -> dict[str, Any]:
        r = self._c.request(method, path, **kw)
        if r.status_code >= 400:
            raise RetellError(f"{method} {path} -> {r.status_code}: {r.text[:500]}")
        return r.json() if r.content else {}

    def close(self) -> None:
        self._c.close()

    # ---- agents -----------------------------------------------------------

    def create_llm(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._req("POST", "/create-retell-llm", json=body)

    def update_llm(self, llm_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._req("PATCH", f"/update-retell-llm/{llm_id}", json=body)

    def create_agent(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._req("POST", "/create-agent", json=body)

    def update_agent(self, agent_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._req("PATCH", f"/update-agent/{agent_id}", json=body)

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        return self._req("GET", f"/get-agent/{agent_id}")

    def list_agents(self) -> list[dict[str, Any]]:
        out = self._req("GET", "/list-agents")
        return out if isinstance(out, list) else out.get("agents", [])

    # ---- chat (text channel) ---------------------------------------------

    def create_chat(self, agent_id: str, **kw) -> dict[str, Any]:
        return self._req("POST", "/create-chat", json={"agent_id": agent_id, **kw})

    def chat_completion(self, chat_id: str, content: str) -> dict[str, Any]:
        return self._req("POST", "/create-chat-completion",
                         json={"chat_id": chat_id, "content": content})

    def end_chat(self, chat_id: str) -> dict[str, Any]:
        return self._req("POST", "/end-chat", json={"chat_id": chat_id})

    def get_chat(self, chat_id: str) -> dict[str, Any]:
        return self._req("GET", f"/get-chat/{chat_id}")

    # ---- calls (voice channel) -------------------------------------------

    def create_web_call(self, agent_id: str, **kw) -> dict[str, Any]:
        return self._req("POST", "/v2/create-web-call", json={"agent_id": agent_id, **kw})

    def get_call(self, call_id: str) -> dict[str, Any]:
        return self._req("GET", f"/v2/get-call/{call_id}")

    def wait_for_call_end(self, call_id: str, timeout_s: float = 180,
                          poll_s: float = 2.0) -> dict[str, Any]:
        """Poll until the call is finished and its transcript has settled.

        Retell populates the transcript asynchronously after a call ends, so
        `call_status == "ended"` alone is not enough — we wait for the
        transcript to stop growing.
        """
        deadline = time.time() + timeout_s
        last_len, stable = -1, 0
        call: dict[str, Any] = {}
        while time.time() < deadline:
            call = self.get_call(call_id)
            status = call.get("call_status")
            if status in ("ended", "error"):
                n = len(call.get("transcript_with_tool_calls") or [])
                stable = stable + 1 if n == last_len else 0
                last_len = n
                if stable >= 2:
                    return call
            time.sleep(poll_s)
        return call
