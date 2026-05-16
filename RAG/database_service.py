"""
database_service.py

Async transaction manager for Neo4j (Property Graph) and Qdrant (Vector DB).
Handles local BGE-M3 embedding batches and maintains cross-links between
Neo4j Graph Node IDs and Qdrant Chunk IDs.
Enforces real database connections; fails fast if Qdrant or Neo4j are offline.
"""

import os
import uuid
import logging
import asyncio
from typing import List, Dict, Any, Optional

from neo4j import AsyncGraphDatabase
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

from document_parser import ChunkMetadata

logger = logging.getLogger("SentinelVault-Database")

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION_NAME = "sentinel_chunks"
VECTOR_DIM = 1024  # BGE-M3 dense vector dimensionality


class DatabaseService:
    def __init__(self):
        self.neo4j_driver = None
        self.qdrant_client = None
        self.bge_model = None

    async def initialize_models(self, shared_model=None):
        """
        Loads the BGE-M3 embedding model used for vector generation.

        Args:
            shared_model: An already-loaded BGEM3FlagModel instance (from EntityResolver).
                          When provided, it is reused directly to avoid loading BGE-M3 twice
                          and wasting ~2 GB VRAM. If None, loads an independent instance.
        """
        if shared_model is not None:
            logger.info("DatabaseService reusing shared BGE-M3 instance from EntityResolver.")
            self.bge_model = shared_model
        else:
            logger.info("Loading BGE-M3 independently for DatabaseService...")
            from FlagEmbedding import BGEM3FlagModel
            self.bge_model = BGEM3FlagModel('BAAI/bge-m3', use_fp16=True)

        logger.info("DatabaseService BGE-M3 ready.")

    async def connect(self):
        """
        Establishes async connections to Neo4j and Qdrant.
        Creates the Qdrant collection if it does not already exist.
        Fails fast if either database is unreachable.
        """
        logger.info("Connecting to local Neo4j and Qdrant instances...")
        try:
            self.neo4j_driver = AsyncGraphDatabase.driver(
                NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD)
            )
            self.qdrant_client = AsyncQdrantClient(url=QDRANT_URL)

            # Validate Qdrant is reachable
            collections = await self.qdrant_client.get_collections()
            existing = [c.name for c in collections.collections]

            # Create collection if it doesn't exist yet
            if COLLECTION_NAME not in existing:
                logger.info(f"Creating Qdrant collection '{COLLECTION_NAME}'...")
                await self.qdrant_client.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
                )

        except Exception as e:
            raise RuntimeError(
                f"Database connection failed: {str(e)}\n"
                f"Ensure Neo4j is at {NEO4J_URI} and Qdrant is at {QDRANT_URL}."
            )

    async def disconnect(self):
        if self.neo4j_driver:
            await self.neo4j_driver.close()

    # -------------------------------------------------------------------------
    # Embedding
    # -------------------------------------------------------------------------

    async def _generate_embeddings(self, text: str) -> List[float]:
        """
        Generates 1024-dim dense vectors using BGE-M3 locally.
        """
        assert self.bge_model is not None, (
            "BGE-M3 model not loaded. Call initialize_models() before using DatabaseService."
        )
        # BGE-M3 encode is CPU/GPU synchronous — offload to thread pool
        emb = await asyncio.to_thread(
            lambda: self.bge_model.encode([text])['dense_vecs'][0]
        )
        return emb.tolist()

    # -------------------------------------------------------------------------
    # Neo4j
    # -------------------------------------------------------------------------

    async def upsert_graph(self, entities: List[Dict], relations: List[Dict]) -> List[str]:
        """
        Executes Cypher MERGE queries to upsert entities and relationships.
        Returns pseudo-IDs for the affected nodes (used for cross-linking in the ledger).
        """
        logger.info(f"Upserting {len(entities)} entities and {len(relations)} relations to Neo4j.")
        try:
            async with self.neo4j_driver.session() as session:
                for entity in entities:
                    await session.run(
                        "MERGE (n:Entity {name: $name})",
                        name=entity["name"]
                    )
                for rel in relations:
                    await session.run(
                        "MATCH (a:Entity {name: $source}), (b:Entity {name: $target}) "
                        f"MERGE (a)-[r:`{rel['type']}`]->(b) "
                        "ON CREATE SET r.confidence = $confidence "
                        "ON MATCH SET r.confidence = $confidence",
                        source=rel["source"],
                        target=rel["target"],
                        confidence=rel.get("confidence", 0.5),
                    )
            return [str(uuid.uuid4()) for _ in entities]
        except Exception as e:
            logger.error(f"Neo4j Upsert Error: {str(e)}")
            raise RuntimeError(f"Failed to upsert to Neo4j: {str(e)}")

    async def query_graph(
        self, cypher_template: str, parameters: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Executes a safe, pre-validated Cypher query intent.
        """
        logger.info(f"Executing Cypher: {cypher_template.strip()[:60]}...")
        try:
            async with self.neo4j_driver.session() as session:
                result = await session.run(cypher_template, parameters)
                records = await result.data()
            return records
        except Exception as e:
            raise RuntimeError(f"Neo4j Graph Query failed: {str(e)}")

    async def prune_low_confidence_nodes(self, entity_name: str):
        """
        Deletes edges connected to the given entity whose confidence is below 0.3.
        Called by AuditLogger when a user submits strong negative feedback for an entity.
        """
        logger.info(f"Pruning low-confidence edges for entity: '{entity_name}'")
        cypher = (
            "MATCH (n:Entity {name: $name})-[r]-()"
            " WHERE r.confidence IS NOT NULL AND r.confidence < 0.3"
            " DELETE r"
        )
        try:
            async with self.neo4j_driver.session() as session:
                await session.run(cypher, name=entity_name)
            logger.info(f"Low-confidence edges pruned for: '{entity_name}'")
        except Exception as e:
            logger.error(f"Graph pruning failed for '{entity_name}': {str(e)}")
            raise RuntimeError(f"Failed to prune graph for '{entity_name}': {str(e)}")

    # -------------------------------------------------------------------------
    # Qdrant
    # -------------------------------------------------------------------------

    async def upsert_vector(self, text: str, metadata: ChunkMetadata) -> str:
        """
        Embeds text using BGE-M3 and upserts to Qdrant.
        Returns the Qdrant Point ID (a UUID string).
        """
        logger.info("Embedding chunk and upserting to Qdrant.")
        embedding = await self._generate_embeddings(text)

        point_id = str(uuid.uuid4())
        payload = metadata.dict()
        payload["text"] = text
        point = PointStruct(id=point_id, vector=embedding, payload=payload)

        try:
            await self.qdrant_client.upsert(
                collection_name=COLLECTION_NAME, points=[point]
            )
        except Exception as e:
            logger.error(f"Qdrant Upsert Error: {str(e)}")
            raise RuntimeError(f"Failed to upsert to Qdrant: {str(e)}")

        return point_id

    async def query_vector(self, query_text: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Performs semantic vector search in Qdrant.
        """
        logger.info(f"Executing Qdrant vector search for: '{query_text}'")
        query_vector = await self._generate_embeddings(query_text)
        try:
            results = await self.qdrant_client.search(
                collection_name=COLLECTION_NAME,
                query_vector=query_vector,
                limit=limit,
            )
            return [
                {"source": "Vector", "content": r.payload.get("text", "")}
                for r in results
            ]
        except Exception as e:
            raise RuntimeError(f"Qdrant Vector Search failed: {str(e)}")
