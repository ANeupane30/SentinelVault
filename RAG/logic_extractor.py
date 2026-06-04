"""
logic_extractor.py

Extraction pipeline for SentinelVault.
Uses a shared LocalLLMClient (backed by OpenRouter) for zero-shot entity tagging
and implicit relationship reasoning.
Outputs strictly validated Knowledge Triples via Pydantic. No fallback mock logic.
"""

import asyncio
from typing import List, Any
from pydantic import BaseModel, Field
from loguru import logger

from llm_client import LocalLLMClient


class KnowledgeTriple(BaseModel):
    subject: str
    predicate: str
    object_: str = Field(alias="object")
    confidence: float
    source_sentence: str


class ExtractionResult(BaseModel):
    triples: List[KnowledgeTriple]
    confidence: float
    llm_refined: bool


class LogicExtractor:
    def __init__(self, llm_client: LocalLLMClient):
        """
        Args:
            llm_client: Shared LocalLLMClient instance injected from api.py.
                        Owns the remote LLM connection — not loaded here.
        """
        self.llm_client = llm_client

    async def extract(self, text: str) -> ExtractionResult:
        """
        Executes the extraction pipeline natively via the Cloud LLM.
        """
        logger.info(f"Extracting triples from text chunk ({len(text)} chars)...")

        # Layer 1 & 2 combined: LLM extracts entities and relations simultaneously
        try:
            refined_triples = await self._run_llm_reasoning(text)
            llm_refined = True
        except Exception as e:
            logger.error(f"Cloud LLM reasoning failed. Error: {str(e)}")
            raise RuntimeError(f"LLM Logic Extraction failed: {str(e)}")

        # Calculate overall confidence
        avg_confidence = 0.0
        if refined_triples:
            avg_confidence = sum(t.confidence for t in refined_triples) / len(refined_triples)

        return ExtractionResult(
            triples=refined_triples,
            confidence=avg_confidence,
            llm_refined=llm_refined
        )

    async def _run_llm_reasoning(self, text: str) -> List[KnowledgeTriple]:
        """
        Uses the LocalLLMClient to extract entities and infer relations.
        Fully async — does not block the event loop.
        """
        messages = [
            {
                "role": "user",
                "content": (
                    "Extract named entities and knowledge triples from this text.\n\n"
                    f"TEXT:\n{text}\n\n"
                    "Output ONLY a JSON object with two keys: 'entities' and 'triples'.\n"
                    "'entities' must be an array of objects with 'text' and 'label' (e.g. Company, Product, Person).\n"
                    "'triples' must be an array of objects with exactly these keys: subject, predicate, object, confidence.\n"
                    "confidence is a float between 0 and 1. Use at most 5 words for subject and object values."
                )
            }
        ]

        extracted = await self.llm_client.complete_json(messages, max_tokens=1000)
        logger.info(f"Raw LLM Extraction Response:\n{extracted}")

        # extracted should be a dict with 'entities' and 'triples' keys
        triples_data = []
        if isinstance(extracted, dict):
            triples_data = extracted.get("triples", [])
        
        refined = []
        malformed_count = 0
        total_count = len(triples_data)

        for t in triples_data:
            try:
                if not isinstance(t, dict):
                    logger.error(
                        f"Non-dict triple item (type={type(t).__name__}): {t}"
                    )
                    malformed_count += 1
                    continue
                if not t.get("object"):
                    logger.error(
                        f"Triple with missing 'object' field: {t}"
                    )
                    malformed_count += 1
                    continue
                t["source_sentence"] = text[:150]
                refined.append(KnowledgeTriple.model_validate(t))
            except Exception as e:
                logger.error(
                    f"Malformed triple from LLM output: {t} — {e}"
                )
                malformed_count += 1

        # If more than 50% of triples are malformed, the LLM prompt adherence has failed
        if total_count > 0 and malformed_count > (total_count / 2):
            raise RuntimeError(
                f"LLM prompt adherence failure: {malformed_count}/{total_count} "
                f"triples were malformed in this chunk."
            )
        elif malformed_count > 0:
            logger.warning(
                f"{malformed_count}/{total_count} triples were malformed but "
                f"below 50% threshold — partial extraction accepted."
            )

        return refined

    async def synthesize_answer(self, query: str, context_results: List[Any]) -> str:
        """
        Uses the LocalLLMClient to synthesize a final natural language answer
        based on retrieved context. Fully async — does not block the event loop.
        """
        logger.info(f"Synthesizing answer for query: {query}")
        context_text = "\n".join([str(c) for c in context_results])
        messages = [
            {
                "role": "user",
                "content": (
                    f"Context:\n{context_text}\n\n"
                    f"Query: {query}\n\n"
                    "Answer based only on the provided context:"
                )
            }
        ]
        return await self.llm_client.complete(messages, max_tokens=512)
