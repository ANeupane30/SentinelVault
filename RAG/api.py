"""
api.py

FastAPI entry point for SentinelVault.
Manages HTTP endpoints for ingestion and query execution, routing requests
to the local-first components (Docling, GLiNER, BGE-M3, Neo4j, Qdrant)
and communicating with the .NET 10 core service via gRPC (notification stub deferred).

LLM inference is handled by the Docker Desktop model (llama3.2:3B-Q4_K_M) via
LocalLLMClient — no Qwen/AWQ model weights are loaded in this process.
"""

import os
import logging
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException, status
from pydantic import BaseModel, Field
import torch

from llm_client import LocalLLMClient
from document_parser import DocumentParser
from logic_extractor import LogicExtractor
from entity_resolver import EntityResolver
from database_service import DatabaseService
from query_planner import QueryPlanner
from reranker_service import RerankerService
from audit_logger import AuditLogger

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("SentinelVault-API")

# Minimum VRAM required for BGE-M3 + BGE-Reranker (LLM runs in Docker Desktop, not here)
MIN_VRAM_GB = float(os.getenv("MIN_VRAM_GB", "4"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup and shutdown lifecycle.

    Startup sequence (order matters):
      1. Hardware validation
      2. LLM client (connects to Docker Desktop — no GPU memory used here)
      3. EntityResolver → loads BGE-M3 (shared)
      4. LogicExtractor → loads GLiNER on CPU
      5. DatabaseService → reuses BGE-M3 from EntityResolver
      6. QueryPlanner, RerankerService → model-free or GPU-light
      7. Database connections (Neo4j + Qdrant)
      8. AuditLogger → injected with DatabaseService
    """
    logger.info("=== SentinelVault startup ===")

    # 1. Hardware validation
    if not torch.cuda.is_available():
        raise RuntimeError(
            "FATAL: CUDA is not available. SentinelVault requires a compatible NVIDIA GPU "
            "for BGE-M3 embeddings and reranking."
        )

    free_mem, total_mem = torch.cuda.mem_get_info()
    total_gb = total_mem / 1024 ** 3
    if total_gb < MIN_VRAM_GB:
        raise RuntimeError(
            f"FATAL: Insufficient VRAM. Found {total_gb:.1f} GB, "
            f"minimum {MIN_VRAM_GB} GB required (BGE-M3 + Reranker). "
            "Set MIN_VRAM_GB env var to override."
        )
    logger.info(f"Hardware validation passed ({total_gb:.1f} GB VRAM available).")

    # 2. LLM Client — connects to Docker Desktop; no GPU memory consumed in this process
    llm_client = LocalLLMClient()
    app.state.llm_client = llm_client

    # 3. Entity Resolver → loads BGE-M3 (will be shared)
    entity_resolver = EntityResolver()
    await entity_resolver.initialize_models()
    app.state.entity_resolver = entity_resolver

    # 4. Logic Extractor → loads GLiNER on CPU; receives shared LLM client
    logic_extractor = LogicExtractor(llm_client=llm_client)
    await logic_extractor.initialize_models()
    app.state.logic_extractor = logic_extractor

    # 5. Database Service → reuses EntityResolver's BGE-M3 instance (saves ~2 GB VRAM)
    database_service = DatabaseService()
    await database_service.initialize_models(shared_model=entity_resolver.embedding_model)
    await database_service.connect()
    app.state.database_service = database_service

    # 6. Query Planner → receives shared LLM client (no additional model load)
    query_planner = QueryPlanner(llm_client=llm_client)
    app.state.query_planner = query_planner

    # 7. Reranker Service → loads BGE-Reranker-v2-m3
    reranker_service = RerankerService()
    await reranker_service.initialize_models()
    app.state.reranker_service = reranker_service

    # 8. Audit Logger → injected with DatabaseService for graph pruning
    audit_logger = AuditLogger(db_service=database_service)
    app.state.audit_logger = audit_logger

    # Document Parser — no model weights, initialised last
    document_parser = DocumentParser()
    app.state.document_parser = document_parser

    logger.info("=== SentinelVault ready ===")
    yield

    # Shutdown
    logger.info("Shutting down SentinelVault services...")
    await database_service.disconnect()


app = FastAPI(
    title="SentinelVault",
    description="Local-First, High-Integrity Knowledge Orchestration Pipeline",
    version="2.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Pydantic Data Contracts
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    query: str = Field(..., description="Natural language query string")
    filters: Optional[Dict[str, Any]] = Field(
        default=None, description="Optional metadata filters"
    )


class QueryResponse(BaseModel):
    answer: str
    confidence: float
    sources: List[Dict[str, Any]]


class IngestResponse(BaseModel):
    status: str
    document_id: str
    extracted_entities: int
    extracted_relations: int


class FeedbackRequest(BaseModel):
    query_id: str = Field(..., description="ID of the query this feedback relates to")
    feedback_score: int = Field(
        ..., description="Positive = good result, negative = bad result"
    )
    correction_signal: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional signal for targeted graph pruning, e.g. {'entity_name': 'Apple'}"
    )


class FeedbackResponse(BaseModel):
    status: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/ingest", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_document(file: UploadFile = File(...)):
    """
    Ingestion Pipeline:
    File Upload → Docling → Character-Count Chunker →
    [GLiNER + LLM Reasoning → Entity Resolver → Neo4j] +
    [BGE-M3 → Qdrant] → Cross-link ChunkID → Correction Ledger
    """
    logger.info(f"Received file for ingestion: {file.filename}")

    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename missing.")

    # Retrieve service instances from app state
    document_parser: DocumentParser = app.state.document_parser
    logic_extractor: LogicExtractor = app.state.logic_extractor
    entity_resolver: EntityResolver = app.state.entity_resolver
    database_service: DatabaseService = app.state.database_service
    audit_logger: AuditLogger = app.state.audit_logger

    try:
        file_bytes = await file.read()

        # 1. Document Parsing (Docling → multi-chunk sliding window)
        document_id, parsed_chunks = await document_parser.parse(file.filename, file_bytes)
        logger.info(f"Parsed document {document_id} into {len(parsed_chunks)} chunk(s).")

        total_entities = 0
        total_relations = 0

        for chunk in parsed_chunks:
            # 2. Logic Extraction (GLiNER + Docker Desktop LLM)
            extraction_result = await logic_extractor.extract(chunk.text)

            # 3. Entity Resolution (Normalization → Blocking → BGE-M3 Semantic → Graph Context)
            resolved_entities, resolved_relations = await entity_resolver.resolve(
                extraction_result, database_service
            )

            # 4. Upsert to Graph DB (Neo4j)
            graph_ids = await database_service.upsert_graph(resolved_entities, resolved_relations)

            # 5. Upsert to Vector DB (Qdrant) with BGE-M3
            vector_id = await database_service.upsert_vector(chunk.text, chunk.metadata)

            # 6. Cross-link ChunkID in Correction Ledger
            await audit_logger.log_ingestion(
                document_id=document_id,
                chunk_id=vector_id,
                graph_ids=graph_ids,
                confidence=extraction_result.confidence,
            )

            total_entities += len(resolved_entities)
            total_relations += len(resolved_relations)

        # NOTE: gRPC notification to .NET core service is deferred (Fix 6).
        # stub = sentinel_pb2_grpc.CoreServiceStub(grpc_channel)
        # await stub.NotifyIngestionComplete(...)

        return IngestResponse(
            status="success",
            document_id=document_id,
            extracted_entities=total_entities,
            extracted_relations=total_relations,
        )

    except Exception as e:
        logger.error(f"Ingestion failed for '{file.filename}': {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ingestion pipeline error: {str(e)}",
        )


@app.post("/query", response_model=QueryResponse)
async def query_pipeline(request: QueryRequest):
    """
    Hybrid Retrieval Pipeline:
    User Query → Query Intent Planner → SQI →
    [Cypher Template → Neo4j] + [BGE-M3 → Qdrant] →
    BGE-Reranker → LLM Synthesis → Correction Ledger
    """
    logger.info(f"Received query: {request.query}")

    logic_extractor: LogicExtractor = app.state.logic_extractor
    database_service: DatabaseService = app.state.database_service
    query_planner: QueryPlanner = app.state.query_planner
    reranker_service: RerankerService = app.state.reranker_service
    audit_logger: AuditLogger = app.state.audit_logger

    try:
        # 1. Query Intent Planning (Docker Desktop LLM → SQI JSON → Cypher template)
        sqi = await query_planner.generate_intent(request.query, request.filters)

        # 2. Hybrid Retrieval
        graph_results = await database_service.query_graph(sqi.cypher_template, sqi.parameters)
        vector_results = await database_service.query_vector(request.query, limit=10)

        # 3. Cross-Encoder Reranking (BGE-Reranker-v2-m3)
        combined_candidates = graph_results + vector_results
        ranked_results = await reranker_service.rerank(request.query, combined_candidates)

        # 4. Final Answer Synthesis (Docker Desktop LLM)
        final_answer = await logic_extractor.synthesize_answer(request.query, ranked_results)

        # 5. Log to Correction Ledger
        await audit_logger.log_query(request.query, sqi, ranked_results)

        return QueryResponse(
            answer=final_answer,
            confidence=sqi.confidence,
            sources=[res.dict() for res in ranked_results[:5]],
        )

    except Exception as e:
        logger.error(f"Query pipeline failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Query execution error: {str(e)}",
        )


@app.post("/feedback", response_model=FeedbackResponse, status_code=status.HTTP_200_OK)
async def submit_feedback(request: FeedbackRequest):
    """
    User Feedback Endpoint:
    Logs feedback to the Correction Ledger.
    Negative scores (< 0) trigger asynchronous graph pruning for the specified entity.

    Example correction_signal: {"entity_name": "apple"}
    """
    audit_logger: AuditLogger = app.state.audit_logger

    try:
        await audit_logger.log_user_feedback(
            query_id=request.query_id,
            feedback_score=request.feedback_score,
            correction_signal=request.correction_signal,
        )
        return FeedbackResponse(status="feedback recorded")

    except Exception as e:
        logger.error(f"Feedback submission failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Feedback error: {str(e)}",
        )
