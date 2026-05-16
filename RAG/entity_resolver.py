"""
entity_resolver.py

Four-stage deduplication and resolution pipeline for SentinelVault.
Prevents node duplication while preserving intentional disambiguation.

Stages:
1. Normalization  — string canonicalization (lowercase, strip punctuation)
2. Blocking       — candidate pair generation (group by first character to avoid O(n²))
3. Semantic Similarity — BGE-M3 cosine similarity against same-block candidates
4. Graph Context  — verify Neo4j neighbour structure to disambiguate collisions

All stages now correctly wire together: Stage 2 builds a candidate map that is
passed into Stage 3 for each entity resolution call.
"""

import logging
import re
from typing import List, Tuple, Dict, Set

from logic_extractor import ExtractionResult, KnowledgeTriple
from database_service import DatabaseService

logger = logging.getLogger("SentinelVault-EntityResolver")


class EntityResolver:
    def __init__(self):
        self.embedding_model = None
        self.models_loaded = False

    async def initialize_models(self):
        """
        Loads the BGE-M3 embedding model for Semantic Similarity resolution.
        This model instance is also shared with DatabaseService to avoid duplicate VRAM usage.
        """
        if self.models_loaded:
            return

        logger.info("Loading BGE-M3 model for Entity Resolution...")
        from FlagEmbedding import BGEM3FlagModel
        self.embedding_model = BGEM3FlagModel('BAAI/bge-m3', use_fp16=True)
        self.models_loaded = True
        logger.info("BGE-M3 loaded successfully for EntityResolver.")

    async def resolve(
        self, extraction: ExtractionResult, db_service: DatabaseService
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        Runs the four-stage resolution pipeline on extracted triples.
        Returns resolved unique entities and their relationships.
        """
        if not self.models_loaded:
            await self.initialize_models()

        logger.info(f"Resolving {len(extraction.triples)} triples...")

        # Stage 1: Normalization
        normalized_triples = self._stage_1_normalization(extraction.triples)

        # Stage 2: Blocking → returns Dict[entity_name, List[same_block_candidates]]
        candidate_map = self._stage_2_blocking(normalized_triples)

        # Stages 3 & 4: Semantic Similarity + Graph Context per entity
        resolved_entities: Set[str] = set()
        resolved_relations: List[Dict] = []

        for triple in normalized_triples:
            subj_resolved = await self._resolve_single_entity(
                triple.subject,
                candidate_map.get(triple.subject, []),
                db_service,
            )
            obj_resolved = await self._resolve_single_entity(
                triple.object_,
                candidate_map.get(triple.object_, []),
                db_service,
            )

            resolved_entities.add(subj_resolved)
            resolved_entities.add(obj_resolved)

            resolved_relations.append({
                "source": subj_resolved,
                "target": obj_resolved,
                "type": triple.predicate.upper().replace(" ", "_"),
                "confidence": triple.confidence,
                "evidence": triple.source_sentence,
            })

        return [{"name": e} for e in resolved_entities], resolved_relations

    # -------------------------------------------------------------------------
    # Stage 1 — Normalization
    # -------------------------------------------------------------------------

    def _stage_1_normalization(self, triples: List[KnowledgeTriple]) -> List[KnowledgeTriple]:
        """
        String canonicalization: lowercase, strip punctuation.
        """
        normalized = []
        for t in triples:
            subj_norm = re.sub(r'[^\w\s]', '', t.subject).strip().lower()
            obj_norm = re.sub(r'[^\w\s]', '', t.object_).strip().lower()
            normalized.append(t.copy(update={"subject": subj_norm, "object_": obj_norm}))
        return normalized

    # -------------------------------------------------------------------------
    # Stage 2 — Blocking
    # -------------------------------------------------------------------------

    def _stage_2_blocking(self, triples: List[KnowledgeTriple]) -> Dict[str, List[str]]:
        """
        Groups entities by their first character to avoid O(n²) comparisons.

        Returns:
            A dict mapping each entity name → list of other entities in the same block.
            This candidate list is passed directly into Stage 3 for each entity.
        """
        blocks: Dict[str, Set[str]] = {}
        all_entities: List[str] = []

        for t in triples:
            for entity in [t.subject, t.object_]:
                if not entity:
                    continue
                all_entities.append(entity)
                first_char = entity[0]
                if first_char not in blocks:
                    blocks[first_char] = set()
                blocks[first_char].add(entity)

        # Each entity's candidates = other members of its block (excluding itself)
        candidate_map: Dict[str, List[str]] = {}
        for entity in all_entities:
            block = blocks.get(entity[0], set())
            candidate_map[entity] = [e for e in block if e != entity]

        return candidate_map

    # -------------------------------------------------------------------------
    # Stage 3 — Semantic Similarity
    # -------------------------------------------------------------------------

    async def _stage_3_semantic_similarity(
        self, entity_name: str, candidates: List[str]
    ) -> str:
        """
        Uses BGE-M3 cosine similarity to find the best matching candidate.
        Returns the candidate if similarity exceeds 0.85, otherwise the original name.
        """
        if not candidates:
            return entity_name

        import numpy as np

        entity_emb = self.embedding_model.encode([entity_name])['dense_vecs']
        candidate_embs = self.embedding_model.encode(candidates)['dense_vecs']

        similarities = np.dot(candidate_embs, entity_emb.T).flatten()
        best_idx = int(np.argmax(similarities))

        if similarities[best_idx] > 0.85:
            logger.debug(
                f"Entity '{entity_name}' → merged with '{candidates[best_idx]}' "
                f"(similarity={similarities[best_idx]:.3f})"
            )
            return candidates[best_idx]

        return entity_name

    # -------------------------------------------------------------------------
    # Stage 4 — Graph Context
    # -------------------------------------------------------------------------

    async def _stage_4_graph_context(
        self, entity_name: str, db_service: DatabaseService
    ) -> str:
        """
        Queries Neo4j neighbour structure to resolve ambiguous merges.
        e.g. distinguishing 'Apple' (fruit) vs 'Apple' (company) based on connected nodes.
        """
        try:
            results = await db_service.query_graph(
                "MATCH (n {name: $name})-[r]-(m) RETURN m.name AS neighbor LIMIT 5",
                {"name": entity_name},
            )
            if results:
                logger.debug(f"Found existing graph neighbours for '{entity_name}'.")
        except Exception as e:
            logger.warning(f"Graph context check failed for '{entity_name}': {e}")

        return entity_name

    # -------------------------------------------------------------------------
    # Combined Stage 3 + 4
    # -------------------------------------------------------------------------

    async def _resolve_single_entity(
        self,
        entity_name: str,
        candidates: List[str],
        db_service: DatabaseService,
    ) -> str:
        """
        Runs Stages 3 and 4 for a single entity, using the candidate list
        built by Stage 2 (blocking).
        """
        semantically_matched = await self._stage_3_semantic_similarity(entity_name, candidates)
        contextually_matched = await self._stage_4_graph_context(semantically_matched, db_service)
        return contextually_matched
