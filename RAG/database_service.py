"""
database_service.py

Async transaction manager for Neo4j (Property Graph) and Qdrant (Vector DB).
Handles unified embeddings via DeepInfra and maintains cross-links between
Neo4j Graph Node IDs and Qdrant Chunk IDs.
"""

import os
import uuid
import logging
import asyncio
from typing import List, Dict, Any, Optional

from neo4j import AsyncGraphDatabase
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from openai import AsyncOpenAI

from document_parser import ChunkMetadata

logger = logging.getLogger("SentinelVault-Database")



COLLECTION_NAME = "sentinel_chunks"
VECTOR_DIM = 1024  # BGE-M3 dense vector dimensionality


class DatabaseService:
    def __init__(self):
        self.neo4j_driver = None
        self.qdrant_client = None
        self.embedding_client = None

    async def initialize_models(self, shared_client=None):
        """
        Initializes the DeepInfra OpenAI client used for embeddings.
        """
        if shared_client is not None:
            logger.info("DatabaseService reusing shared embedding client.")
            self.embedding_client = shared_client
        else:
            logger.info("Initializing DeepInfra embedding client...")
            self.embedding_client = AsyncOpenAI(
                base_url="https://api.deepinfra.com/v1/openai",
                api_key=os.getenv("DEEPINFRA_API_KEY")
            )
        logger.info("DatabaseService embedding client ready.")

        # C5: Validate that the embedding model produces vectors matching VECTOR_DIM
        logger.info("Validating embedding dimension against VECTOR_DIM...")
        test_vector = await self._generate_embeddings("test")
        if len(test_vector) != VECTOR_DIM:
            raise RuntimeError(
                f"Embedding dimension mismatch. Expected {VECTOR_DIM}, "
                f"got {len(test_vector)}. Update VECTOR_DIM or check "
                f"the embedding model."
            )
        logger.info(f"Embedding dimension validated: {len(test_vector)} == VECTOR_DIM ({VECTOR_DIM}).")

    async def connect(self):
        """
        Establishes async connections to cloud Neo4j and Qdrant.
        Creates the Qdrant collection if it does not already exist.
        """
        logger.info("Connecting to cloud Neo4j and Qdrant instances...")
        
        neo4j_uri = os.getenv("NEO4J_URI")
        neo4j_user = os.getenv("NEO4J_USER")
        neo4j_password = os.getenv("NEO4J_PASSWORD")
        qdrant_url = os.getenv("QDRANT_URL")
        qdrant_api_key = os.getenv("QDRANT_API_KEY")

        try:
            self.neo4j_driver = AsyncGraphDatabase.driver(
                neo4j_uri, auth=(neo4j_user, neo4j_password)
            )
            self.qdrant_client = AsyncQdrantClient(url=qdrant_url, api_key=qdrant_api_key)

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
                f"Ensure NEO4J_URI and QDRANT_URL are configured properly."
            )

    async def disconnect(self):
        if self.neo4j_driver:
            await self.neo4j_driver.close()

    # -------------------------------------------------------------------------
    # Embedding
    # -------------------------------------------------------------------------

    async def _generate_embeddings(self, text: str) -> List[float]:
        """
        Generates 1024-dim dense vectors using DeepInfra's BGE-M3 endpoint.
        """
        assert self.embedding_client is not None, (
            "Embedding client not loaded. Call initialize_models() before using DatabaseService."
        )
        try:
            response = await self.embedding_client.embeddings.create(
                input=[text],
                model="BAAI/bge-m3",
                encoding_format="float"
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            raise RuntimeError(f"Embedding generation failed: {e}") from e

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
            
            filtered_records = []
            for rec in records:
                content_str = str(rec).strip() if rec else ""
                if not content_str:
                    continue
                
                # Assign deterministic source and content for the pipeline
                rec["source"] = "Graph"
                rec["content"] = content_str
                
                filtered_records.append(rec)
                
            return filtered_records
        except Exception as e:
            raise RuntimeError(f"Neo4j Graph Query failed: {str(e)}")

    async def prune_low_confidence_nodes(self, entity_name: str):
        """
        Deletes edges connected to the given entity whose confidence is below 0.3.
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
    # Document Registry
    # -------------------------------------------------------------------------

    async def upsert_document_node(self, document_id: str, source_filename: str, title: str, ingested_at: str, total_chunks: int):
        """
        Creates or updates a Document node in Neo4j representing an ingested file.
        """
        logger.info(f"Upserting Document node for {document_id} ({source_filename})")
        cypher = (
            "MERGE (d:Document {document_id: $document_id}) "
            "SET d.source_filename = $source_filename, "
            "d.title = $title, "
            "d.ingested_at = $ingested_at, "
            "d.total_chunks = $total_chunks"
        )
        parameters = {
            "document_id": document_id,
            "source_filename": source_filename,
            "title": title,
            "ingested_at": ingested_at,
            "total_chunks": total_chunks
        }
        try:
            async with self.neo4j_driver.session() as session:
                await session.run(cypher, parameters)
        except Exception as e:
            logger.error(f"Failed to upsert Document node: {e}")
            raise RuntimeError(f"Failed to upsert Document node: {e}")

    async def get_all_documents(self) -> List[Dict[str, Any]]:
        """
        Retrieves all Document nodes from Neo4j, ordered by ingestion time descending.
        """
        logger.info("Fetching all ingested documents.")
        cypher = (
            "MATCH (d:Document) "
            "RETURN d.document_id AS document_id, "
            "d.source_filename AS source_filename, "
            "d.title AS title, "
            "d.ingested_at AS ingested_at, "
            "d.total_chunks AS total_chunks "
            "ORDER BY d.ingested_at DESC"
        )
        try:
            async with self.neo4j_driver.session() as session:
                result = await session.run(cypher)
                records = await result.data()
                return records
        except Exception as e:
            logger.error(f"Failed to fetch documents: {e}")
            raise RuntimeError(f"Failed to fetch documents: {e}")

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
            filtered_results = []
            for r in results:
                content = r.payload.get("text")
                if not content or not str(content).strip():
                    continue
                
                # Check for required metadata fields
                required_fields = ["document_id", "estimated_page_number", "heading_depth", "section_path", "source_filename"]
                if not all(field in r.payload for field in required_fields):
                    continue
                    
                result_dict = {"source": "Vector", "content": str(content).strip()}
                for k, v in r.payload.items():
                    if k != "text":
                        result_dict[k] = v
                filtered_results.append(result_dict)
                
            return filtered_results
        except Exception as e:
            raise RuntimeError(f"Qdrant Vector Search failed: {str(e)}")
