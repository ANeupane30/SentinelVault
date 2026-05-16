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
import uuid
import logging
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, Request, UploadFile, File, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from loguru import logger
import torch

from llm_client import LocalLLMClient
from document_parser import DocumentParser
from logic_extractor import LogicExtractor
from entity_resolver import EntityResolver
from database_service import DatabaseService
from query_planner import QueryPlanner
from reranker_service import RerankerService
from audit_logger import AuditLogger

# ---------------------------------------------------------------------------
# Logging — loguru replaces stdlib logging for structured, contextualised output.
# The correlation ID is injected per-request via contextualize() in the middleware.
# ---------------------------------------------------------------------------
import sys
logger.remove()  # Remove loguru's default handler
# Provide a default value for correlation_id so startup/shutdown log lines
# (which run outside any request context) do not raise a KeyError on the format field.
logger.configure(extra={"correlation_id": "-"})
logger.add(
    sys.stderr,
    level="INFO",
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{line}</cyan> | "
        "<yellow>corr_id={extra[correlation_id]}</yellow> | "
        "{message}"
    ),
)

# Minimum VRAM required for BGE-M3 + BGE-Reranker (LLM runs in Docker Desktop, not here)
MIN_VRAM_GB = float(os.getenv("MIN_VRAM_GB", "4"))

# When REQUIRE_GPU=false the service starts in CPU-only mode (degraded throughput).
# Leave REQUIRE_GPU unset or set to any other value to keep the original fail-fast behaviour.
_REQUIRE_GPU = os.getenv("REQUIRE_GPU", "true").strip().lower() != "false"

# ---------------------------------------------------------------------------
# Service-to-service API key
# Read once at module load so misconfiguration is caught before any request.
# Set RAG_API_KEY in the environment (or .env) before starting the server.
# ---------------------------------------------------------------------------
_RAG_API_KEY: str | None = os.getenv("RAG_API_KEY")


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
    # When REQUIRE_GPU=false: warn and continue in CPU-only mode.
    # Otherwise: crash fast so GPU misconfigurations are caught immediately.
    if not torch.cuda.is_available():
        if _REQUIRE_GPU:
            raise RuntimeError(
                "FATAL: CUDA is not available. SentinelVault requires a compatible NVIDIA GPU "
                "for BGE-M3 embeddings and reranking. "
                "Set REQUIRE_GPU=false to start in CPU-only mode (degraded throughput)."
            )
        logger.warning(
            "CUDA is not available — running in CPU-only mode (REQUIRE_GPU=false). "
            "Throughput will be significantly lower than GPU operation."
        )
    else:
        free_mem, total_mem = torch.cuda.mem_get_info()
        total_gb = total_mem / 1024 ** 3
        if total_gb < MIN_VRAM_GB:
            if _REQUIRE_GPU:
                raise RuntimeError(
                    f"FATAL: Insufficient VRAM. Found {total_gb:.1f} GB, "
                    f"minimum {MIN_VRAM_GB} GB required (BGE-M3 + Reranker). "
                    "Set MIN_VRAM_GB env var to override, or set REQUIRE_GPU=false for CPU-only mode."
                )
            logger.warning(
                f"Insufficient VRAM ({total_gb:.1f} GB < {MIN_VRAM_GB} GB) — "
                "continuing in CPU-only mode (REQUIRE_GPU=false)."
            )
        else:
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
# Feature 1 — Correlation ID middleware
#
# For every request:
#   1. Read X-Correlation-ID header; generate a uuid4 if absent.
#   2. Bind it to loguru's context so every log line in this request carries it.
#   3. Store it on request.state so route handlers can read it if needed.
#   4. Echo it back in the response header.
# ---------------------------------------------------------------------------

@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
    request.state.correlation_id = correlation_id

    # Bind to loguru context for the duration of this request.
    with logger.contextualize(correlation_id=correlation_id):
        response = await call_next(request)

    response.headers["X-Correlation-ID"] = correlation_id
    return response


# ---------------------------------------------------------------------------
# Feature 2 — Service-to-service API key dependency
#
# Applied only to /v1/ingest and /v1/query (the .NET-facing routes).
# All other routes (/query, /ingest, /feedback, /health) remain open.
# ---------------------------------------------------------------------------

async def verify_api_key(x_api_key: str = Header(
    default=None,
    alias="X-Api-Key",
    description="Shared secret sent by the .NET backend on every /v1/* call.",
)):
    """
    FastAPI dependency that enforces the RAG_API_KEY shared secret.
    Raises HTTP 401 if the header is missing or does not match.
    """
    if not _RAG_API_KEY:
        # Key not configured — skip enforcement so local dev still works,
        # but emit a clear warning so it is not silently skipped in prod.
        logger.warning(
            "RAG_API_KEY is not set. /v1/* routes are running WITHOUT authentication. "
            "Set RAG_API_KEY in the environment before deploying to production."
        )
        return
    if x_api_key != _RAG_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Api-Key header.",
        )


# ---------------------------------------------------------------------------
# Feature 3 — Global exception handler
#
# Catches any unhandled Exception that escapes a route handler.
# Logs it with full traceback and returns a structured JSON 500 response
# that includes the correlation ID for cross-service tracing.
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    correlation_id = getattr(request.state, "correlation_id", "unknown")
    logger.error(
        f"Unhandled exception on {request.method} {request.url.path} "
        f"[corr_id={correlation_id}]: {exc}",
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": type(exc).__name__,
            "message": str(exc),
            "correlation_id": correlation_id,
        },
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


@app.get("/health", tags=["ops"])
async def health_check():
    """
    Liveness probe — returns immediately without touching any ML model or database.
    Used by Docker Compose healthchecks and the .NET backend's readiness check.
    """
    return {"status": "ok", "version": "2.1.0"}


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


# ---------------------------------------------------------------------------
# /v1/* aliases — used by the .NET PythonAiClient
#
# These thin wrappers delegate to the canonical handlers above so there is
# no duplicated logic.  The .NET backend strips auth, then forwards here.
# ---------------------------------------------------------------------------


class V1QueryRequest(BaseModel):
    """Slim request accepted by the .NET-facing /v1/query alias."""
    query: str = Field(..., description="Natural language query string")


@app.post(
    "/v1/ingest",
    response_model=IngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["v1-aliases"],
    dependencies=[Depends(verify_api_key)],
)
async def v1_ingest_document(file: UploadFile = File(...)):
    """
    .NET-compatible alias for POST /ingest.
    Accepts multipart/form-data with a 'file' field and delegates to the
    canonical ingest_document handler — no logic is duplicated here.
    Protected by X-Api-Key header (verify_api_key dependency).
    """
    return await ingest_document(file)


@app.post(
    "/v1/query",
    tags=["v1-aliases"],
    dependencies=[Depends(verify_api_key)],
)
async def v1_query_pipeline(request: V1QueryRequest):
    """
    .NET-compatible alias for POST /query.
    Accepts { "query": "..." } and returns a plain string (the answer field only)
    so the .NET ChatService can treat it as a raw string without deserialising
    the full QueryResponse envelope.
    Protected by X-Api-Key header (verify_api_key dependency).
    """
    # Build a full QueryRequest with no filters and delegate to the canonical handler.
    full_request = QueryRequest(query=request.query, filters=None)
    result: QueryResponse = await query_pipeline(full_request)
    # Return only the answer string — matches what .NET PythonAiClient.GetAiResponseAsync expects.
    return result.answer
