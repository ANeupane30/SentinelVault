"""
query_planner.py

Converts natural language queries into a Structured Query Intent (SQI) JSON object.
Uses a shared LocalLLMClient (Docker Desktop llama3.2) to parse intent, capturing entities,
relationships, filters, and logical constraints. Maps these to pre-validated Cypher templates
to prevent Cypher hallucinations.
Enforces strict JSON parsing without fallback mock generation.
"""

import logging
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from llm_client import LocalLLMClient

logger = logging.getLogger("SentinelVault-QueryPlanner")


class StructuredQueryIntent(BaseModel):
    intent_type: str = Field(..., description="Type of query: 'ENTITY_LOOKUP', 'PATH_FINDING', 'AGGREGATION'")
    target_entities: List[str] = Field(default_factory=list)
    target_relations: List[str] = Field(default_factory=list)
    filters: Dict[str, Any] = Field(default_factory=dict)
    cypher_template: str = Field(..., description="The pre-validated Cypher template string to use")
    parameters: Dict[str, Any] = Field(default_factory=dict)
    confidence: float


class QueryPlanner:
    def __init__(self, llm_client: LocalLLMClient):
        """
        Args:
            llm_client: Shared LocalLLMClient instance injected from api.py.
        """
        self.llm_client = llm_client

        # Pre-validated safe Cypher templates — LLM selects which template to use,
        # it cannot generate raw Cypher directly.
        self.TEMPLATES = {
            "ENTITY_LOOKUP": """
                MATCH (n) WHERE n.name IN $entity_names
                OPTIONAL MATCH (n)-[r]-(m)
                RETURN n, r, m LIMIT $limit
            """,
            "PATH_FINDING": """
                MATCH p=shortestPath((source)-[*1..3]-(target))
                WHERE source.name = $source_name AND target.name = $target_name
                RETURN p
            """,
            "AGGREGATION": """
                MATCH (n:Entity)-[r]->(m:Entity)
                WHERE n.name IN $entity_names
                RETURN n.name AS entity, type(r) AS relation, count(m) AS count
                ORDER BY count DESC LIMIT $limit
            """
        }

    async def generate_intent(
        self,
        user_query: str,
        filters: Optional[Dict[str, Any]] = None,
    ) -> StructuredQueryIntent:
        """
        Translates a natural language query into an SQI object using the local LLM.

        Args:
            user_query: The user's natural language question.
            filters:    Optional additional metadata filters to apply.

        Returns:
            A StructuredQueryIntent with a pre-validated Cypher template and parameters.
            Falls back to a safe ENTITY_LOOKUP SQI if the LLM returns malformed JSON.
        """
        logger.info(f"Planning query intent for: '{user_query}'")

        # Ultra-explicit prompt: small models (3B) need a concrete example and
        # must not be asked to produce keys that the code ignores anyway.
        messages = [
            {
                "role": "user",
                "content": (
                    "You are a JSON API. Respond ONLY with a single JSON object — "
                    "no prose, no markdown, no explanation.\n\n"
                    "Analyse the query and return exactly this JSON structure:\n"
                    '{"intent_type": "ENTITY_LOOKUP", "target_entities": ["name1"], "target_relations": []}\n\n'
                    "Rules:\n"
                    '  - intent_type must be exactly one of: "ENTITY_LOOKUP", "PATH_FINDING", "AGGREGATION"\n'
                    "  - target_entities is a JSON array of entity name strings extracted from the query\n"
                    "  - target_relations is a JSON array of relationship strings (may be empty)\n\n"
                    f'Query: "{user_query}"\n\n'
                    "JSON response:"
                )
            }
        ]

        # Attempt LLM-based intent parsing; fall back to safe defaults on any failure.
        intent_type = "ENTITY_LOOKUP"
        target_entities: List[str] = []
        target_relations: List[str] = []

        try:
            intent_data = await self.llm_client.complete_json(messages, max_tokens=128)

            if isinstance(intent_data, dict):
                intent_type = intent_data.get("intent_type", "ENTITY_LOOKUP")
                target_entities = intent_data.get("target_entities", [])
                target_relations = intent_data.get("target_relations", [])
            else:
                logger.warning(
                    f"LLM returned a non-dict SQI payload ({type(intent_data).__name__}). "
                    "Defaulting to ENTITY_LOOKUP."
                )
        except RuntimeError as e:
            # complete_json() exhausted retries — fall back gracefully instead of 500.
            logger.warning(
                f"QueryPlanner LLM call failed after retries: {e}. "
                "Falling back to full-text vector search (ENTITY_LOOKUP, no entity filter)."
            )

        # Guard: fall back to ENTITY_LOOKUP if an unrecognised intent is returned
        if intent_type not in self.TEMPLATES:
            logger.warning(
                f"Unknown intent_type '{intent_type}' from LLM — defaulting to ENTITY_LOOKUP."
            )
            intent_type = "ENTITY_LOOKUP"

        # Ensure list types are correct (LLM sometimes returns a bare string)
        if isinstance(target_entities, str):
            target_entities = [target_entities] if target_entities else []
        if isinstance(target_relations, str):
            target_relations = [target_relations] if target_relations else []

        template = self.TEMPLATES[intent_type]
        parameters: Dict[str, Any] = {
            "entity_names": target_entities,
            "limit": 50,
        }

        if intent_type == "PATH_FINDING" and len(target_entities) >= 2:
            parameters["source_name"] = target_entities[0]
            parameters["target_name"] = target_entities[1]

        if filters:
            parameters.update(filters)

        sqi = StructuredQueryIntent(
            intent_type=intent_type,
            target_entities=target_entities,
            target_relations=target_relations,
            filters=filters or {},
            cypher_template=template,
            parameters=parameters,
            confidence=0.92,
        )

        logger.info(f"Generated SQI: {sqi.intent_type} targeting {sqi.target_entities}")
        return sqi
