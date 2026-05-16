"""
llm_client.py

Central async LLM client for SentinelVault.
Wraps the Docker Desktop local model (llama3.2:3B-Q4_K_M) via its OpenAI-compatible API.
All LLM inference in the pipeline routes through this module — no other file loads model weights.

Exposes:
  - complete()       → returns raw text response
  - complete_json()  → returns parsed dict/list; raises RuntimeError on parse failure
"""

import os
import json
import logging
import asyncio
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger("SentinelVault-LLMClient")

# Resolved from environment — allows swapping models or endpoints without code changes.
# Inside Docker Compose use host.docker.internal; for local native runs use localhost.
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:12434/engines/llama.cpp/v1")
LLM_MODEL_ID = os.getenv("LLM_MODEL_ID", "ai/llama3.2:3B-Q4_K_M")
LLM_API_KEY = os.getenv("LLM_API_KEY", "unused")
# Number of retry attempts when the LLM returns malformed JSON.
# Each retry re-sends the full request; the model may produce valid JSON on a subsequent attempt.
LLM_JSON_RETRIES = int(os.getenv("LLM_JSON_RETRIES", "3"))


class LocalLLMClient:
    """
    Thin async wrapper around the Docker Desktop OpenAI-compatible LLM endpoint.
    A single shared instance is created at startup in api.py and injected into
    LogicExtractor and QueryPlanner.
    """

    def __init__(self):
        self._client = AsyncOpenAI(
            base_url=LLM_BASE_URL,
            api_key=LLM_API_KEY,
        )
        logger.info(
            f"LocalLLMClient initialised → base_url={LLM_BASE_URL}, model={LLM_MODEL_ID}"
        )

    async def complete(self, messages: list[dict], max_tokens: int = 512) -> str:
        """
        Sends a chat-completion request and returns the raw text content.

        Args:
            messages:   OpenAI-style message list, e.g. [{"role": "user", "content": "..."}]
            max_tokens: Maximum tokens to generate.

        Returns:
            The assistant's response as a plain string.

        Raises:
            RuntimeError: If the API call fails or returns an empty response.
        """
        logger.debug(f"LLM complete() called with {len(messages)} message(s), max_tokens={max_tokens}")
        try:
            response = await self._client.chat.completions.create(
                model=LLM_MODEL_ID,
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

    async def complete_json(self, messages: list[dict], max_tokens: int = 512) -> Any:
        """
        Sends a chat-completion request and parses the response as JSON.
        Retries up to LLM_JSON_RETRIES times (default 3) with exponential backoff
        when the model returns malformed or non-JSON output.

        Strategy:
          - Appends a system message instructing JSON-only output.
          - Extracts the first JSON array or object from the raw response.
          - On parse failure, waits 2^attempt seconds and retries the full request.
          - Raises RuntimeError only after all retries are exhausted.

        Args:
            messages:   OpenAI-style message list.
            max_tokens: Maximum tokens to generate.

        Returns:
            A parsed Python dict or list.

        Raises:
            RuntimeError: If all retry attempts fail to produce valid JSON.
        """
        # Append JSON-only instruction once — reused across all retry attempts
        json_messages = list(messages)
        json_messages.append({
            "role": "system",
            "content": (
                "Respond only with valid JSON. "
                "Do not include any prose, explanation, or markdown fences. "
                "Your entire response must be parseable by json.loads()."
            )
        })

        last_error: Exception | None = None

        for attempt in range(1, LLM_JSON_RETRIES + 1):
            try:
                raw = await self.complete(json_messages, max_tokens=max_tokens)
            except RuntimeError as e:
                # API-level failure (network error, empty response, etc.)
                last_error = e
                wait = 2 ** (attempt - 1)
                logger.warning(
                    f"complete_json() attempt {attempt}/{LLM_JSON_RETRIES}: "
                    f"API call failed ({e}). Retrying in {wait}s..."
                )
                await asyncio.sleep(wait)
                continue

            json_str = self._extract_json_substring(raw)

            if not json_str:
                last_error = RuntimeError(
                    f"No JSON array or object found in LLM output."
                )
                wait = 2 ** (attempt - 1)
                logger.warning(
                    f"complete_json() attempt {attempt}/{LLM_JSON_RETRIES}: "
                    f"No JSON found in output. Retrying in {wait}s...\n"
                    f"Raw output: {raw[:300]!r}"
                )
                await asyncio.sleep(wait)
                continue

            try:
                return json.loads(json_str)
            except json.JSONDecodeError as e:
                last_error = e
                wait = 2 ** (attempt - 1)
                logger.warning(
                    f"complete_json() attempt {attempt}/{LLM_JSON_RETRIES}: "
                    f"JSON parse error: {e}. Retrying in {wait}s...\n"
                    f"Extracted string: {json_str[:300]!r}"
                )
                await asyncio.sleep(wait)

        raise RuntimeError(
            f"complete_json() failed after {LLM_JSON_RETRIES} attempt(s). "
            f"Last error: {last_error}"
        ) from last_error

    @staticmethod
    def _extract_json_substring(text: str) -> str:
        """
        Extracts the first well-formed JSON array or object from a text string.
        Tries array ([...]) before object ({...}) since extraction responses are usually lists.
        """
        # Try array first
        arr_start = text.find("[")
        arr_end = text.rfind("]")
        if arr_start != -1 and arr_end != -1 and arr_end > arr_start:
            return text[arr_start:arr_end + 1]

        # Fall back to object
        obj_start = text.find("{")
        obj_end = text.rfind("}")
        if obj_start != -1 and obj_end != -1 and obj_end > obj_start:
            return text[obj_start:obj_end + 1]

        return ""
