"""Text generation with bounded Gemini requests and a real Groq fallback.

Only final responses are returned. Provider reasoning is never sent to the UI.
Structured results are validated against the caller's Pydantic schema before
they can become case data.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time

import httpx
from langchain_core.messages import AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import GOOGLE_API_KEY, MODEL_FLASH, MODEL_PRO, MODEL_SEARCH
from app.services.reasoning import ReasoningModel

logger = logging.getLogger(__name__)
_unavailable_until: dict[str, float] = {}


def _messages(messages: list) -> list[dict]:
    result = []
    roles = {"human": "user", "ai": "assistant", "system": "system"}
    for message in messages:
        if isinstance(message, tuple):
            role, content = message
        else:
            role, content = message.type, message.content
        result.append({"role": roles.get(role, role), "content": content})
    return result


class TextModel:
    def __init__(self, tier: str = "flash", schema=None):
        self.tier = tier
        self.schema = schema

    def with_structured_output(self, schema):
        return TextModel(self.tier, schema)

    async def ainvoke(self, messages: list):
        if self.tier == "pro" and os.getenv("LITELLM_API_KEY"):
            try:
                return await ReasoningModel(self.schema).ainvoke(messages)
            except Exception as exc:
                logger.warning("Hackathon reasoning provider unavailable (%s); trying fallback", type(exc).__name__)
        model = {"flash": MODEL_FLASH, "pro": MODEL_PRO, "search": MODEL_SEARCH}[self.tier]
        groq_models = list(dict.fromkeys([os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"), *os.getenv("GROQ_FALLBACK_MODELS", "openai/gpt-oss-20b,qwen/qwen3.8-27b").split(",")]))
        groq_choices = [("groq", name.strip()) for name in groq_models if name.strip()]
        providers = [("gemini", model), *groq_choices] if os.getenv("LLM_PROVIDER", "gemini") != "groq" else [*groq_choices, ("gemini", model)]
        for provider, selected_model in providers:
            identity = f"{provider}:{selected_model}"
            if provider != "gemini" and _unavailable_until.get(identity, 0) > time.monotonic():
                continue
            try:
                if provider == "gemini":
                    if not GOOGLE_API_KEY:
                        continue
                    llm = ChatGoogleGenerativeAI(model=model, google_api_key=GOOGLE_API_KEY, temperature=0.1, max_retries=0, timeout=22)
                    target = llm.with_structured_output(self.schema) if self.schema else llm
                    return await asyncio.wait_for(target.ainvoke(messages), timeout=25)
                key = os.getenv("GROQ_API_KEY", "")
                if not key:
                    continue
                wire = _messages(messages)
                request = {
                    "model": selected_model,
                    "messages": wire,
                    "temperature": 0.1,
                    "max_completion_tokens": 4096 if self.schema else 8192,
                }
                if selected_model.startswith("openai/gpt-oss"):
                    request["reasoning_effort"] = "low"
                if self.schema:
                    wire.insert(0, {"role": "system", "content": "Return ONLY a JSON object conforming to this schema. Preserve exact evidence quotes; never fill unknown facts.\n" + json.dumps(self.schema.model_json_schema())})
                    request["response_format"] = {"type": "json_object"}
                async with httpx.AsyncClient(timeout=httpx.Timeout(45, connect=10)) as client:
                    response = await client.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {key}"}, json=request)
                    response.raise_for_status()
                    result = response.json()["choices"][0]
                if result.get("finish_reason") == "length":
                    raise ValueError("Provider response exceeded output limit")
                content = result["message"].get("content")
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("Empty provider response")
                return self.schema.model_validate_json(content) if self.schema else AIMessage(content=content)
            except Exception as exc:
                # Only the class is logged: SDK error bodies may include request data.
                logger.warning("Text provider %s unavailable (%s); trying fallback", provider, type(exc).__name__)
                cooldown = 20
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
                    try:
                        cooldown = min(60, max(3, float(exc.response.headers.get("retry-after", 15))))
                    except ValueError:
                        cooldown = 15
                _unavailable_until[identity] = time.monotonic() + cooldown
        if self.tier != "pro" and os.getenv("LITELLM_API_KEY"):
            return await ReasoningModel(self.schema).ainvoke(messages)
        raise RuntimeError("The case analysis service is temporarily unavailable. Your saved intake remains available; please retry.")


def text_llm(tier: str = "flash") -> TextModel:
    return TextModel(tier)
