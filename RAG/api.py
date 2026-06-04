"""
api.py

FastAPI entry point for SentinelVault.
Manages HTTP endpoints for ingestion and query execution, routing requests
to the local-first components (Docling, GLiNER, Neo4j, Qdrant)
and cloud endpoints (OpenRouter, DeepInfra).
"""

import os
from dotenv import load_dotenv
env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(env_path, override=True)

import uuid
import logging
import time
import asyncio
import datetime
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, Request, UploadFile, File, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from loguru import logger

from llm_client import LocalLLMClient
from document_parser import DocumentParser
from logic_extractor import LogicExtractor
from entity_resolver import EntityResolver
from database_service import DatabaseService
from query_planner import QueryPlanner
from reranker_service import RerankerService
from audit_logger import AuditLogger

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
import sys
logger.remove()
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

# Custom Exceptions
class DatabaseConnectionError(Exception): pass
class LLMGenerationError(Exception): pass
class ComponentError(Exception): pass

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=== SentinelVault startup ===")



    llm_client = LocalLLMClient()
    app.state.llm_client = llm_client

    entity_resolver = EntityResolver()
    await entity_resolver.initialize_models()
    app.state.entity_resolver = entity_resolver

    logic_extractor = LogicExtractor(llm_client=llm_client)
    app.state.logic_extractor = logic_extractor

    database_service = DatabaseService()
    await database_service.initialize_models(shared_client=entity_resolver.embedding_client)
    
    try:
        await database_service.connect()
    except Exception as e:
        raise DatabaseConnectionError(f"Failed to connect to databases: {e}") from e
    
    app.state.database_service = database_service

    query_planner = QueryPlanner(llm_client=llm_client)
    app.state.query_planner = query_planner

    reranker_service = RerankerService()
    app.state.reranker_service = reranker_service

    audit_logger = AuditLogger(db_service=database_service)
    app.state.audit_logger = audit_logger

    document_parser = DocumentParser()
    app.state.document_parser = document_parser

    logger.info("=== SentinelVault ready ===")
    yield

    logger.info("Shutting down SentinelVault services...")
    await database_service.disconnect()


app = FastAPI(
    title="SentinelVault",
    description="Cloud-Ready Knowledge Orchestration Pipeline",
    version="2.2.0",
    lifespan=lifespan,
)

@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
    request.state.correlation_id = correlation_id
    with logger.contextualize(correlation_id=correlation_id):
        response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    return response

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)

    correlation_id = getattr(request.state, "correlation_id", "unknown")
    logger.error(
        "Unhandled exception on {method} {path} [corr_id={corr_id}]: {exc}",
        method=request.method,
        path=request.url.path,
        corr_id=correlation_id,
        exc=str(exc)
    )
    
    # Determine failing component name for 500 response
    component = "Unknown Component"
    if isinstance(exc, DatabaseConnectionError):
        component = "Database Connection"
    elif isinstance(exc, LLMGenerationError):
        component = "LLM Generation"
    elif isinstance(exc, ComponentError):
        component = "System Component"

    return JSONResponse(
        status_code=500,
        content={
            "error": type(exc).__name__,
            "failing_component": component,
            "message": str(exc),
            "correlation_id": correlation_id,
        },
    )

class QueryRequest(BaseModel):
    query: str = Field(..., description="Natural language query string")
    filters: Optional[Dict[str, Any]] = Field(default=None, description="Optional metadata filters")

class QueryResponse(BaseModel):
    answer: str
    confidence: Optional[float] = None
    sources: List[Dict[str, Any]]

class IngestResponse(BaseModel):
    status: str
    document_id: str
    extracted_entities: int
    extracted_relations: int

class FeedbackRequest(BaseModel):
    query_id: str = Field(..., description="ID of the query this feedback relates to")
    feedback_score: int = Field(..., description="Positive = good result, negative = bad result")
    correction_signal: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional signal for targeted graph pruning, e.g. {'entity_name': 'Apple'}"
    )

class FeedbackResponse(BaseModel):
    status: str

@app.get("/health", tags=["ops"])
async def health_check():
    return {"status": "ok", "version": "2.2.0"}

@app.post("/ingest", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_document(file: UploadFile = File(...)):
    logger.info(f"Received file for ingestion: {file.filename}")
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename missing.")

    document_parser: DocumentParser = app.state.document_parser
    logic_extractor: LogicExtractor = app.state.logic_extractor
    entity_resolver: EntityResolver = app.state.entity_resolver
    database_service: DatabaseService = app.state.database_service
    audit_logger: AuditLogger = app.state.audit_logger

    correlation_id = str(uuid.uuid4())

    try:
        file_bytes = await file.read()
        document_id, parsed_chunks = await document_parser.parse(file.filename, file_bytes)
        logger.info(f"Parsed document {document_id} into {len(parsed_chunks)} chunk(s).")

        total_entities = 0
        total_relations = 0
        failed_chunks = []

        async def _process_single_chunk(chunk):
            try:
                t0 = time.time()
                extraction_result = await logic_extractor.extract(chunk.text)
                t1 = time.time()
                logger.info(f"Chunk extraction took {t1 - t0:.2f} seconds")
            except Exception as e:
                logger.error(f"Logic extraction failed for chunk {chunk.chunk_id}: {e}")
                failed_chunks.append({"chunk_id": str(chunk.chunk_id), "error": str(e)})
                return 0, 0

            t2 = time.time()
            resolved_entities, resolved_relations = await entity_resolver.resolve(
                extraction_result, database_service
            )
            t3 = time.time()
            logger.info(f"Entity resolution took {t3 - t2:.2f} seconds")

            try:
                t4 = time.time()
                graph_ids = await database_service.upsert_graph(resolved_entities, resolved_relations)
                vector_id = await database_service.upsert_vector(chunk.text, chunk.metadata)
                t5 = time.time()
                logger.info(f"Database writes (graph & vector) took {t5 - t4:.2f} seconds")
            except Exception as e:
                raise DatabaseConnectionError(f"Database upsert failed: {e}") from e

            await audit_logger.log_ingestion(
                document_id=document_id,
                chunk_id=vector_id,
                graph_ids=graph_ids,
                confidence=extraction_result.confidence,
            )

            return len(resolved_entities), len(resolved_relations)

        results = await asyncio.gather(
            *[_process_single_chunk(chunk) for chunk in parsed_chunks],
            return_exceptions=True
        )

        for res in results:
            if isinstance(res, Exception):
                raise res
            e_count, r_count = res
            total_entities += e_count
            total_relations += r_count

        # Evaluate outcomes after the loop
        total_chunks = len(parsed_chunks)
        succeeded = total_chunks - len(failed_chunks)

        if succeeded > 0:
            title = os.path.splitext(file.filename)[0] if file.filename else "Unknown"
            await database_service.upsert_document_node(
                document_id=document_id,
                source_filename=file.filename or "Unknown",
                title=title,
                ingested_at=datetime.datetime.utcnow().isoformat(),
                total_chunks=total_chunks
            )

        if succeeded == 0 and total_chunks > 0:
            # ALL chunks failed
            return JSONResponse(
                status_code=500,
                content={
                    "status": "failed",
                    "document_id": document_id,
                    "correlation_id": correlation_id,
                    "message": "Ingestion failed. No chunks were processed.",
                    "total_chunks": total_chunks,
                    "succeeded": 0,
                    "failed": len(failed_chunks),
                    "failed_chunks": failed_chunks,
                },
            )

        if failed_chunks:
            # SOME chunks failed — partial success
            return JSONResponse(
                status_code=207,
                content={
                    "status": "partial_success",
                    "document_id": document_id,
                    "correlation_id": correlation_id,
                    "degraded": True,
                    "total_chunks": total_chunks,
                    "succeeded": succeeded,
                    "failed": len(failed_chunks),
                    "failed_chunks": failed_chunks,
                },
            )

        # ALL chunks succeeded — unchanged 202
        return IngestResponse(
            status="success",
            document_id=document_id,
            extracted_entities=total_entities,
            extracted_relations=total_relations,
        )

    except Exception as e:
        logger.error(f"Ingestion failed for '{file.filename}': {str(e)}")
        # If it's already our custom exception, let it bubble up to the global handler
        if isinstance(e, (DatabaseConnectionError, LLMGenerationError, ComponentError)):
            raise e
        raise ComponentError(f"Ingestion pipeline error: {str(e)}") from e


@app.get("/documents")
async def get_documents():
    database_service: DatabaseService = app.state.database_service
    docs = await database_service.get_all_documents()
    return {
        "total": len(docs),
        "documents": docs
    }

@app.post("/query", response_model=QueryResponse)
async def query_pipeline(request: QueryRequest):
    logger.info(f"Received query: {request.query}")

    logic_extractor: LogicExtractor = app.state.logic_extractor
    database_service: DatabaseService = app.state.database_service
    query_planner: QueryPlanner = app.state.query_planner
    reranker_service: RerankerService = app.state.reranker_service
    audit_logger: AuditLogger = app.state.audit_logger

    try:
        try:
            sqi = await query_planner.generate_intent(request.query, request.filters)
        except Exception as e:
            raise LLMGenerationError(f"Query planning failed: {e}") from e

        try:
            graph_results = await database_service.query_graph(sqi.cypher_template, sqi.parameters)
            vector_results = await database_service.query_vector(request.query, limit=10)
        except Exception as e:
            raise DatabaseConnectionError(f"Hybrid retrieval failed: {e}") from e

        combined_candidates = graph_results + vector_results
        ranked_results = await reranker_service.rerank(request.query, combined_candidates)

        try:
            final_answer = await logic_extractor.synthesize_answer(request.query, ranked_results)
        except Exception as e:
            raise LLMGenerationError(f"Answer synthesis failed: {e}") from e

        await audit_logger.log_query(request.query, sqi, ranked_results)

        try:
            max_sources = int(os.getenv("MAX_SOURCES", "5"))
        except ValueError:
            max_sources = 5

        return QueryResponse(
            answer=final_answer,
            confidence=sqi.confidence,
            sources=[res.dict() for res in ranked_results[:max_sources]],
        )

    except Exception as e:
        logger.error(f"Query pipeline failed: {str(e)}")
        if isinstance(e, (DatabaseConnectionError, LLMGenerationError, ComponentError)):
            raise e
        raise ComponentError(f"Query execution error: {str(e)}") from e


@app.post("/feedback", response_model=FeedbackResponse, status_code=status.HTTP_200_OK)
async def submit_feedback(request: FeedbackRequest):
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
        raise DatabaseConnectionError(f"Feedback error: {str(e)}") from e
