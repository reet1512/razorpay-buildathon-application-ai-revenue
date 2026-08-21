"""
ai/client.py — talk to Ollama (OpenAI-compatible /v1/chat/completions).

Default:
  LLM_BASE_URL=http://localhost:11434/v1
  LLM_MODEL=qwen3:8b
  LLM_API_KEY=ollama
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

load_dotenv()


class LLMError(RuntimeError):
    """Raised when the model call or JSON parse fails hard."""


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


class LLMClient:
    """
    Thin HTTP client.

    We use httpx (already in requirements) instead of the OpenAI SDK
    so local Ollama stays a zero-drama dependency.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 120.0,
    ) -> None:
        self.provider = _env("LLM_PROVIDER", "ollama")
        self.base_url = (base_url or _env("LLM_BASE_URL", "http://localhost:11434/v1")).rstrip(
            "/"
        )
        self.api_key = api_key or _env("LLM_API_KEY", "ollama")
        self.model = model or _env("LLM_MODEL", "qwen3:8b")
        self.timeout = timeout

    def available(self) -> bool:
        """
        Cheap health check.

        Ollama: GET http://localhost:11434/api/tags
        If this fails, agent must use rules_fallback (exit check).
        """
        try:
            root = self.base_url.replace("/v1", "")
            with httpx.Client(timeout=3.0) as client:
                r = client.get(f"{root}/api/tags")
                return r.status_code == 200
        except Exception:
            return False

    def chat_json(self, system: str, user: str, *, temperature: float = 0.1) -> dict[str, Any]:
        """
        Ask for JSON. Parse strictly. Raise LLMError on failure.
        """
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        # qwen3 may "think"; we still ask for final JSON only.
        payload = {
            "model": self.model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            raise LLMError(f"LLM HTTP failed: {exc}") from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except Exception as exc:
            raise LLMError(f"Unexpected LLM response shape: {data!r}") from exc

        return parse_json_content(content)


def parse_json_content(content: str) -> dict[str, Any]:
    """
    Extract JSON from model output.

    Handles:
    - markdown fences ```json ... ```
    - qwen3 <think>...</think> blocks
    - leading/trailing prose (best-effort first {...} object)
    """
    text = content.strip()
    # Strip think blocks (qwen3)
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"<thinking>[\s\S]*?</thinking>", "", text, flags=re.IGNORECASE).strip()

    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Best effort: first JSON object in the string
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise LLMError(f"Could not parse JSON from model output: {content[:400]!r}")
