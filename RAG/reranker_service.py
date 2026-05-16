"""
reranker_service.py

Cross-encoder scoring service using BGE-Reranker-v2-m3.
Merges result sets from Neo4j (sparse graph) and Qdrant (dense vector),
and semantic-reranks them to prevent RRF mathematical bias from burying precise graph results.
Executes real BGE cross-encoder scoring natively; no mock scoring fallback.
"""

import logging
import asyncio
from typing import List, Dict, Any
from pydantic import BaseModel

from FlagEmbedding import FlagReranker

logger = logging.getLogger("SentinelVault-Reranker")

class RankedResult(BaseModel):
    source_type: str
    content: str
    cross_encoder_score: float

class RerankerService:
    def __init__(self):
        self.reranker_model = None
        self.models_loaded = False

    async def initialize_models(self):
        """
        Loads the BGE-Reranker-v2-m3 cross-encoder into VRAM.
        """
        if self.models_loaded:
            return
            
        logger.info("Loading BGE-Reranker-v2-m3 Cross-Encoder...")
        self.reranker_model = FlagReranker('BAAI/bge-reranker-v2-m3', use_fp16=True)
        self.models_loaded = True

    async def rerank(self, query: str, candidates: List[Dict[str, Any]]) -> List[RankedResult]:
        """
        Scores the combined candidate list against the user query.
        """
        if not candidates:
            return []
            
        if not self.models_loaded:
            await self.initialize_models()

        logger.info(f"Cross-encoder reranking {len(candidates)} mixed candidates...")
        
        # Prepare pairs for the cross-encoder: [[query, doc1], [query, doc2], ...]
        pairs = [[query, str(cand.get("content", ""))] for cand in candidates]
        
        # Real cross-encoder scoring
        scores = self.reranker_model.compute_score(pairs)
        if isinstance(scores, float): # If only 1 pair, it returns a single float
            scores = [scores]
        
        ranked_results = []
        for cand, score in zip(candidates, scores):
            ranked_results.append(
                RankedResult(
                    source_type=cand.get("source", "Unknown"),
                    content=str(cand.get("content", "")),
                    cross_encoder_score=float(score)
                )
            )
            
        # Sort descending by score
        ranked_results.sort(key=lambda x: x.cross_encoder_score, reverse=True)
        return ranked_results
