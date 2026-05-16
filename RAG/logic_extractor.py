"""
logic_extractor.py

Dual-layer extraction pipeline for SentinelVault.
1. Uses GLiNER for fast zero-shot entity tagging on CPU.
2. Uses a shared LocalLLMClient (Docker Desktop llama3.2) for implicit relationship reasoning.
Outputs strictly validated Knowledge Triples via Pydantic. No fallback mock logic.
"""

import logging
import asyncio
from typing import List, Any
from pydantic import BaseModel, Field

from gliner import GLiNER

from llm_client import LocalLLMClient

logger = logging.getLogger("SentinelVault-LogicExtractor")


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
                        Owns the Docker Desktop LLM connection — not loaded here.
        """
        self.llm_client = llm_client
        self.gliner_model = None
        self.models_loaded = False

    async def initialize_models(self):
        """
        Loads GLiNER entity model on CPU.
        The LLM is managed externally via LocalLLMClient — no model weights loaded here.
        """
        if self.models_loaded:
            return

        logger.info("Loading GLiNER entity model on CPU...")
        self.gliner_model = GLiNER.from_pretrained("urchade/gliner_mediumv2.1").to("cpu")

        self.models_loaded = True
        logger.info("Logic Extractor (GLiNER) loaded successfully.")

    async def extract(self, text: str) -> ExtractionResult:
        """
        Executes the dual-layer extraction pipeline.
        """
        if not self.models_loaded:
            logger.warning("Models not initialized, calling initialize_models() now.")
            await self.initialize_models()

        logger.info(f"Extracting triples from text chunk ({len(text)} chars)...")

        # Layer 1: GLiNER Entity Extraction & Heuristic Tagging
        extracted_entities, base_triples = await self._run_gliner(text)

        # Layer 2: LLM Logic Refinement (async, non-blocking via AsyncOpenAI)
        try:
            refined_triples = await self._run_llm_reasoning(text, extracted_entities, base_triples)
            llm_refined = True
        except Exception as e:
            logger.error(f"Local LLM reasoning failed. Error: {str(e)}")
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

    async def _run_gliner(self, text: str) -> tuple[List[dict], List[KnowledgeTriple]]:
        """
        Runs GLiNER on CPU for entity extraction, applies strict mapping,
        and formulates initial base triples heuristically.
        """
        labels = ["Company", "Product", "Person", "Location", "Support"]
        entities = self.gliner_model.predict_entities(text, labels)

        # Strict Mapping: Force known company names to be Company
        for ent in entities:
            if ent["text"].lower() in ["toshiba", "hp"]:
                ent["label"] = "Company"

        triples = []
        # Heuristic: If there is exactly one Company and some Products, form HAS_PRODUCT triples
        companies = [e for e in entities if e["label"] == "Company"]
        products = [e for e in entities if e["label"] == "Product"]

        if len(companies) == 1 and products:
            for p in products:
                triples.append(
                    KnowledgeTriple(
                        subject=companies[0]["text"],
                        predicate="HAS_PRODUCT",
                        object_=p["text"],
                        confidence=0.5,  # Low confidence — awaits LLM refinement
                        source_sentence=text
                    )
                )

        return entities, triples

    async def _run_llm_reasoning(
        self, text: str, entities: List[dict], base_triples: List[KnowledgeTriple]
    ) -> List[KnowledgeTriple]:
        """
        Uses the LocalLLMClient to infer implicit relations and long-range dependencies.
        Fully async — does not block the event loop.
        """
        messages = [
            {
                "role": "user",
                "content": (
                    f"Given the text: '{text}'\n"
                    f"Extracted Entities: {entities}\n"
                    f"Base Heuristic Triples: {[t.dict(by_alias=True) for t in base_triples]}\n"
                    "Extract any implicit relationships or correct any mistakes. "
                    "Output a JSON array of triples, each with keys: "
                    "subject, predicate, object, confidence (float 0-1), source_sentence."
                )
            }
        ]

        extracted = await self.llm_client.complete_json(messages, max_tokens=512)

        # extracted may be a list of dicts or a dict with a triples key
        if isinstance(extracted, dict):
            extracted = extracted.get("triples", [])

        refined = base_triples.copy()
        for t in extracted:
            try:
                refined.append(KnowledgeTriple(**t))
            except Exception as e:
                logger.warning(f"Skipping malformed triple from LLM output: {t} — {e}")

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
