"""
llm_client.py

Central async LLM client for SentinelVault.
Wraps the OpenRouter OpenAI-compatible API.
All LLM inference in the pipeline routes through this module.

Exposes:
  - complete()       → returns raw text response
  - complete_json()  → returns parsed dict/list; relies on OpenAI SDK JSON mode
"""

import os
import json
import logging
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger("SentinelVault-LLMClient")

class LocalLLMClient:
    """
    Thin async wrapper around the OpenRouter OpenAI-compatible endpoint.
    A single shared instance is created at startup in api.py and injected into
    LogicExtractor and QueryPlanner.
    """

    def __init__(self):
        # Read from environment with no fallbacks for secrets
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        self.base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

        model = os.getenv("OPENROUTER_MODEL")
        if not model:
            raise RuntimeError(
                "OPENROUTER_MODEL environment variable is required "
                "and not set. Set it to a valid OpenRouter model string."
            )
        self.model_id = model

        self._client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )
        logger.info(
            f"LocalLLMClient initialised → base_url={self.base_url}, model={self.model_id}"
        )

    async def complete(self, messages: list[dict], max_tokens: int = 512) -> str:
        """
        Sends a chat-completion request and returns the raw text content.
        """
        logger.debug(f"LLM complete() called with {len(messages)} message(s), max_tokens={max_tokens}")
        try:
            response = await self._client.chat.completions.create(
                model=self.model_id,
                messages=messages,
                max_tokens=max_tokens,
            )
            content = response.choices[0].message.content
            if not content:
                raise RuntimeError("LLM returned an empty response.")
            return content.strip()
        except Exception as e:
            logger.error(f"LLM complete() failed: {e}")
            raise RuntimeError(f"LLM inference failed: {e}") from e

    async def complete_json(self, messages: list[dict], max_tokens: int = 1024) -> Any:
        """
        Sends a chat-completion request and parses the response as JSON.
        Relies on OpenAI SDK JSON mode (response_format={"type": "json_object"}).
        """
        # Prepend a strict JSON-only system message before all caller-supplied messages.
        STRICT_JSON_SYSTEM = (
            "You are a precise assistant. Respond only with valid JSON. "
            "No explanation, no markdown code fences, no trailing text of any kind."
        )
        json_messages = []
        caller_had_system = any(m.get("role") == "system" for m in messages)
        for msg in messages:
            if msg.get("role") == "system":
                # Prepend the strict instruction to any existing system message.
                json_messages.append({
                    "role": "system",
                    "content": STRICT_JSON_SYSTEM + " " + msg["content"],
                })
            else:
                json_messages.append(msg)
        if not caller_had_system:
            # No system message from caller — insert one at the front.
            json_messages.insert(0, {"role": "system", "content": STRICT_JSON_SYSTEM})

        try:
            response = await self._client.chat.completions.create(
                model=self.model_id,
                messages=json_messages,
                max_tokens=max_tokens,
                response_format={"type": "json_object"}
            )
            
            if response.choices is None or len(response.choices) == 0:
                raise RuntimeError("LLM returned an empty response.")
                
            if getattr(response.choices[0], "message", None) is None or response.choices[0].message.content is None:
                raise RuntimeError("LLM returned an empty response.")
                
            content = response.choices[0].message.content
            if not content:
                logger.error(f"Empty LLM response! Full response dump: {response.model_dump_json()}")
                raise RuntimeError("LLM returned an empty response.")
            logger.info(f"Raw string from LLM before JSON parse:\n{content}")
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode failed for LLM response: {e}")
            raise RuntimeError(f"JSON parse error: {e}") from e
        except Exception as e:
            logger.error(f"LLM complete_json() failed: {e}")
            raise RuntimeError(f"LLM inference failed: {e}") from e
