"""
audit_logger.py

Manages the Correction Ledger for SentinelVault.
Persists extraction confidence metadata, user correction signals, and feedback events.

Exposes methods to:
  - log_ingestion()      → records every document chunk ingestion with confidence score
  - log_query()          → records every query, its parsed intent, and results served
  - log_user_feedback()  → records user feedback and triggers graph pruning on negative signals

The Correction Ledger is an append-only JSONL file. Each line is a timestamped JSON record.
"""

import os
import json
import logging
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from query_planner import StructuredQueryIntent
from reranker_service import RankedResult

logger = logging.getLogger("SentinelVault-AuditLogger")

LEDGER_PATH = os.getenv("LEDGER_PATH", "./correction_ledger.jsonl")


class AuditLogger:
    def __init__(self, db_service=None):
        """
        Args:
            db_service: DatabaseService instance injected from api.py.
                        Required for graph pruning triggered by negative user feedback.
                        If None, graph refinement will be skipped with a warning.
        """
        self.db_service = db_service
        self._ensure_ledger_exists()

    def _ensure_ledger_exists(self):
        os.makedirs(os.path.dirname(os.path.abspath(LEDGER_PATH)), exist_ok=True)
        if not os.path.exists(LEDGER_PATH):
            with open(LEDGER_PATH, 'w') as f:
                pass  # Create empty file

    async def log_ingestion(
        self,
        document_id: str,
        chunk_id: str,
        graph_ids: List[str],
        confidence: float,
    ):
        """
        Logs the ingestion of a document chunk, cross-linking vector and graph IDs
        along with the extraction confidence score.
        Flags low-confidence ingestions for review.
        """
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": "INGESTION",
            "document_id": document_id,
            "chunk_id": chunk_id,
            "graph_ids": graph_ids,
            "confidence": confidence,
        }
        await self._write_to_ledger(entry)

        if confidence < 0.5:
            logger.warning(
                f"Low confidence ingestion ({confidence:.2f}) for doc {document_id}. "
                "Flagged for review."
            )

    async def log_query(
        self,
        query: str,
        sqi: StructuredQueryIntent,
        results: List[RankedResult],
    ):
        """
        Logs a user query, its parsed intent, and the ranked results served.
        """
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": "QUERY",
            "query": query,
            "intent_type": sqi.intent_type,
            "target_entities": sqi.target_entities,
            "results_served": len(results),
            "top_score": results[0].cross_encoder_score if results else 0.0,
        }
        await self._write_to_ledger(entry)

    async def log_user_feedback(
        self,
        query_id: str,
        feedback_score: int,
        correction_signal: Optional[Dict] = None,
    ):
        """
        Logs user feedback (e.g. thumbs up/down, specific node correction).
        Triggers asynchronous graph pruning if feedback is strongly negative (score < 0).

        Args:
            query_id:          Identifier for the query this feedback applies to.
            feedback_score:    Positive = good, negative = bad.
            correction_signal: Optional dict with an 'entity_name' key to target pruning.
        """
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": "USER_FEEDBACK",
            "query_id": query_id,
            "feedback_score": feedback_score,
            "correction_signal": correction_signal or {},
        }
        await self._write_to_ledger(entry)

        if feedback_score < 0:
            await self._trigger_graph_refinement(correction_signal)

    async def _write_to_ledger(self, entry: Dict[str, Any]):
        """
        Asynchronously appends a JSONL entry to the ledger file.
        File I/O is offloaded to a thread so the async event loop is not blocked.
        """
        def sync_write():
            with open(LEDGER_PATH, 'a') as f:
                f.write(json.dumps(entry) + '\n')

        await asyncio.to_thread(sync_write)

    async def _trigger_graph_refinement(self, correction_signal: Optional[Dict]):
        """
        Prunes low-confidence edges in Neo4j for the entity named in correction_signal.
        Called automatically when a user submits negative feedback.
        """
        if self.db_service is None:
            logger.warning(
                "Graph refinement triggered but no DatabaseService was injected into AuditLogger. "
                "Skipping pruning."
            )
            return

        if not correction_signal or "entity_name" not in correction_signal:
            logger.warning(
                "Graph refinement triggered but 'entity_name' not found in correction_signal. "
                f"Signal received: {correction_signal}. Skipping pruning."
            )
            return

        entity_name = correction_signal["entity_name"]
        logger.info(f"Graph refinement triggered for entity: '{entity_name}'")

        try:
            await self.db_service.prune_low_confidence_nodes(entity_name)
            logger.info(f"Graph refinement complete for entity: '{entity_name}'")
        except Exception as e:
            logger.error(f"Graph refinement failed for '{entity_name}': {e}")
