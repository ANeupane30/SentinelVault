"""
reranker_service.py

Cross-encoder scoring service using BGE-Reranker-v2-m3.
Merges result sets from Neo4j (sparse graph) and Qdrant (dense vector),
and semantic-reranks them to prevent RRF mathematical bias from burying precise graph results.
"""

import os
import logging
from typing import List, Dict, Any
from pydantic import BaseModel
import httpx

logger = logging.getLogger("SentinelVault-Reranker")

class RankedResult(BaseModel):
    source_type: str
    content: str
    cross_encoder_score: float

class RerankerService:
    def __init__(self):
        self.api_key = os.getenv("DEEPINFRA_API_KEY")
        # DeepInfra doesn't natively host BGE rerankers anymore, so we substitute with Qwen3-Reranker-4B
        self.endpoint = "https://api.deepinfra.com/v1/inference/Qwen/Qwen3-Reranker-4B"

    async def rerank(self, query: str, candidates: List[Dict[str, Any]]) -> List[RankedResult]:
        """
        Scores the combined candidate list against the user query using DeepInfra.
        """
        # IMPORTANT: scores must be initialized here to prevent UnboundLocalError
        # if the API response path does not assign scores. Do not remove.
        scores = []
        if not candidates:
            return []

        logger.info(f"Cross-encoder reranking {len(candidates)} mixed candidates...")

        # DeepInfra expects {"query": query, "documents": [doc1, doc2, ...]}
        documents = [str(cand.get("content", "")) for cand in candidates]

        try:
            if self.api_key:
                # DeepInfra doesn't have a standard OpenAI rerank endpoint, so we hit their inference API.
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.post(
                        self.endpoint,
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json={"queries": [query], "documents": documents}
                    )
                    logger.debug(f"Raw reranker response: {response.text}")
                    logger.info(f"Raw reranker response: {response.text[:500]}")
                    if response.status_code == 200:
                        data = response.json()
                        # Assuming the API returns a list of scores or similar structure
                        if "scores" in data:
                            scores = [float(x) for x in data["scores"]]
                        elif isinstance(data, list):
                            scores = [float(x) for x in data]
                        elif "results" in data:
                            results_list = sorted(data["results"], 
                                                  key=lambda x: x.get("index", 0))
                            scores = [float(x.get("relevance_score", x.get("score", 0))) 
                                      for x in results_list]
                    else:
                        logger.error(f"DeepInfra Reranker returned {response.status_code}: {response.text}")
                        raise RuntimeError(f"DeepInfra Reranker returned {response.status_code}: {response.text}")
            else:
                logger.error("No DEEPINFRA_API_KEY found.")
                raise RuntimeError("No DEEPINFRA_API_KEY found. Cannot perform reranking.")
        except Exception as e:
            logger.error(f"Reranker failed: {e}")
            raise RuntimeError(f"Reranker failed: {e}") from e

        if not scores:
            raise RuntimeError(
                "Reranker returned a response but scores list is empty. "
                "Check the response parsing logic."
            )

        ranked_results = []
        for cand, score in zip(candidates, scores):
            ranked_results.append(
                RankedResult(
                    source_type=cand.get("source", "Unknown"),
                    content=str(cand.get("content", "")),
                    cross_encoder_score=score
                )
            )
            
        # Sort descending by score
        ranked_results.sort(key=lambda x: x.cross_encoder_score, reverse=True)
        return ranked_results
