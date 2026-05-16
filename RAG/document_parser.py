"""
document_parser.py

Wraps the Docling parser to extract layout-aware Markdown and structural hierarchy from PDFs.
Outputs structured chunks anchored to their document context (section path, page, heading depth).

Chunking strategy: simple character-count sliding window splitter.
  - CHUNK_SIZE chars per chunk (default 1500, configurable via env var)
  - CHUNK_OVERLAP chars of overlap between adjacent chunks (default 150)
This avoids requiring a tokenizer download while still covering the full document.
"""

import os
import uuid
import logging
import asyncio
import tempfile
from typing import List, Tuple

from pydantic import BaseModel
from docling.document_converter import DocumentConverter

logger = logging.getLogger("SentinelVault-DocParser")

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "150"))


class ChunkMetadata(BaseModel):
    document_id: str
    page_number: int
    heading_depth: int
    section_path: str
    source_filename: str


class StructuredChunk(BaseModel):
    chunk_id: str
    text: str
    metadata: ChunkMetadata


class DocumentParser:
    def __init__(self):
        """
        Initialises the Docling universal parser.
        """
        logger.info("Initialising Docling DocumentParser...")
        self.converter = DocumentConverter()

    async def parse(self, filename: str, file_bytes: bytes) -> Tuple[str, List[StructuredChunk]]:
        """
        Parses a raw file (PDF/Text) into layout-aware Markdown and structured chunks.

        Args:
            filename:   Original filename (used for metadata and temp file suffix).
            file_bytes: Raw bytes of the document.

        Returns:
            A tuple of (document_id, list of StructuredChunks).
            Multiple chunks are returned — one per sliding window over the full document text.
        """
        document_id = str(uuid.uuid4())
        logger.info(f"Parsing document '{filename}' [ID: {document_id}]")

        # Use tempfile.mkstemp() for cross-platform compatibility (Windows + Linux/Docker)
        fd, temp_path = tempfile.mkstemp(suffix=f"_{filename}")
        os.close(fd)

        try:
            # Write bytes to temp file via thread pool (non-blocking)
            await asyncio.to_thread(self._write_temp_file, temp_path, file_bytes)

            # Run Docling conversion in thread pool (CPU-bound, synchronous)
            result = await asyncio.to_thread(self.converter.convert, temp_path)
            markdown_text = result.document.export_to_markdown()

            logger.info(
                f"Docling extracted {len(markdown_text)} chars from '{filename}'. "
                f"Splitting into chunks (size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP})..."
            )

            chunks = self._split_into_chunks(markdown_text, document_id, filename)
            logger.info(f"Document '{filename}' split into {len(chunks)} chunk(s).")

            return document_id, chunks

        except Exception as e:
            logger.error(f"Failed to parse document '{filename}': {str(e)}")
            raise
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def _split_into_chunks(
        self, text: str, document_id: str, filename: str
    ) -> List[StructuredChunk]:
        """
        Sliding-window character-count chunker.

        Splits the full document text into overlapping chunks of CHUNK_SIZE characters,
        stepping forward by (CHUNK_SIZE - CHUNK_OVERLAP) each iteration.
        This ensures context is not lost at chunk boundaries.
        """
        chunks: List[StructuredChunk] = []
        step = max(1, CHUNK_SIZE - CHUNK_OVERLAP)
        start = 0

        while start < len(text):
            end = min(start + CHUNK_SIZE, len(text))
            chunk_text = text[start:end].strip()

            if chunk_text:  # Skip empty chunks that can appear at the tail
                chunk_index = len(chunks) + 1
                chunks.append(
                    StructuredChunk(
                        chunk_id=str(uuid.uuid4()),
                        text=chunk_text,
                        metadata=ChunkMetadata(
                            document_id=document_id,
                            # Page estimation: rough heuristic — ~3000 chars per page
                            page_number=max(1, (start // 3000) + 1),
                            heading_depth=1,
                            section_path=f"/chunk_{chunk_index}",
                            source_filename=filename,
                        ),
                    )
                )

            start += step

        return chunks

    def _write_temp_file(self, path: str, data: bytes):
        with open(path, "wb") as f:
            f.write(data)
