# src/tools/graphrag_tool.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.contracts.types import EvidenceChunk, EvidencePack
from src.graphrag.retrieve import RetrieveConfig, graphrag_retrieve


@dataclass(frozen=True)
class GraphRagTool:
    cfg: RetrieveConfig

    def retrieve(self, query: str) -> EvidencePack:
        raw: Dict[str, Any] = graphrag_retrieve(query, self.cfg)

        def to_chunk(prefix: str, d: Dict[str, Any]) -> EvidenceChunk:
            chunk_id = d.get("chunk_id") or ""
            return EvidenceChunk(
                evidence_id=f"{prefix}:{chunk_id}",
                chunk_id=chunk_id,
                doc_id=d.get("doc_id"),
                text=d.get("text"),
                score=d.get("score"),
            )

        seed = [to_chunk("seed", c) for c in raw.get("seed_chunks", []) if c.get("chunk_id")]
        exp = [to_chunk("exp", c) for c in raw.get("expanded_chunks", []) if c.get("chunk_id")]

        # add evidence_id to paths deterministically
        graph_paths = []
        for i, p in enumerate(raw.get("graph_paths", [])):
            p2 = dict(p)
            p2["evidence_id"] = f"path:{i}"
            graph_paths.append(p2)

        return EvidencePack(
            query=raw.get("query", query),
            seed_chunks=seed,
            expanded_chunks=exp,
            graph_paths=graph_paths,
            provenance=raw.get("provenance", {}),
        )
