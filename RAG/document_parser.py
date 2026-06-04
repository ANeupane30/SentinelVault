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

# CHUNK_SIZE and CHUNK_OVERLAP are now validated in DocumentParser.__init__


class ChunkMetadata(BaseModel):
    document_id: str
    estimated_page_number: int
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
        try:
            self.chunk_size = int(os.getenv("CHUNK_SIZE", "1500"))
            self.chunk_overlap = int(os.getenv("CHUNK_OVERLAP", "150"))
        except ValueError as e:
            raise RuntimeError(
                f"CHUNK_SIZE and CHUNK_OVERLAP must be valid integers. "
                f"Error: {e}"
            ) from e

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
                f"Splitting into chunks (size={self.chunk_size}, overlap={self.chunk_overlap})..."
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
        Uses RecursiveCharacterTextSplitter to split the document text into chunks
        respecting paragraph and sentence boundaries.
        """
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap
        )
        
        text_chunks = splitter.split_text(text)
        chunks: List[StructuredChunk] = []
        
        for i, chunk_text in enumerate(text_chunks):
            if chunk_text.strip():
                chunk_index = i + 1
                # Approximation: Docling's export_to_markdown() does not preserve
                # native page boundaries, so we estimate page numbers using a
                # heuristic of ~3000 characters per page. This is inaccurate for
                # documents with dense tables, images, or sparse content.
                estimated_page = max(1, ((i * (self.chunk_size - self.chunk_overlap)) // 3000) + 1)
                chunks.append(
                    StructuredChunk(
                        chunk_id=str(uuid.uuid4()),
                        text=chunk_text.strip(),
                        metadata=ChunkMetadata(
                            document_id=document_id,
                            estimated_page_number=estimated_page,
                            heading_depth=1,
                            section_path=f"/chunk_{chunk_index}",
                            source_filename=filename,
                        ),
                    )
                )

        return chunks

    def _write_temp_file(self, path: str, data: bytes):
        with open(path, "wb") as f:
            f.write(data)
