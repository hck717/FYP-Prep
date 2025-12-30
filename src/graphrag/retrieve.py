from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from neo4j import GraphDatabase
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer


@dataclass(frozen=True)
class RetrieveConfig:
    qdrant_path: str
    collection: str
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    embed_model: str
    top_k: int
    hop_k: int
    mapping_path: str
    out_json_path: str


_YEAR_RE = re.compile(r"(19|20)\d{2}")


def extract_source_year(doc_id: Optional[str]) -> Optional[int]:
    """
    Best-effort year extraction from doc_id, e.g.:
      aapl_10k_2024_excerpt -> 2024
      aapl_q3_2025_transcript_excerpt -> 2025
    """
    if not doc_id:
        return None
    m = _YEAR_RE.search(doc_id)
    return int(m.group(0)) if m else None


def graphrag_retrieve(query: str, cfg: RetrieveConfig) -> Dict[str, Any]:
    # ---- Vector pivot (Qdrant) ----
    qdrant = QdrantClient(path=cfg.qdrant_path)
    embedder = SentenceTransformer(cfg.embed_model)
    qvec = embedder.encode([query], normalize_embeddings=True)[0].tolist()

    res = qdrant.query_points(
        collection_name=cfg.collection,
        query=qvec,
        limit=cfg.top_k,
        with_payload=True,
    )
    hits = res.points

    seed_chunks: List[Dict[str, Any]] = []
    seed_chunk_ids: List[str] = []

    # provenance helper: doc_id -> source_year
    doc_years: Dict[str, int] = {}

    for h in hits:
        payload = h.payload or {}
        chunk_id = payload.get("chunk_id")
        if not chunk_id:
            continue

        doc_id = payload.get("doc_id")
        source_year = extract_source_year(doc_id)
        if doc_id and source_year is not None:
            doc_years[doc_id] = source_year

        seed_chunk_ids.append(chunk_id)
        seed_chunks.append(
            {
                "evidence_id": f"seed:{chunk_id}",
                "chunk_id": chunk_id,
                "doc_id": doc_id,
                "source_year": source_year,
                "score": float(h.score) if h.score is not None else None,
                "text": payload.get("text"),
            }
        )

    # ---- Graph expansion (Neo4j) ----
    driver = GraphDatabase.driver(cfg.neo4j_uri, auth=(cfg.neo4j_user, cfg.neo4j_password))

    graph_paths: List[Dict[str, Any]] = []
    expanded_chunk_ids: List[str] = []

    cypher = """
    MATCH (c:Chunk {id:$cid})-[:MENTIONS]->(e:Entity)
    OPTIONAL MATCH (e)-[:CO_OCCURS]->(n:Entity)
    WITH e, collect(DISTINCT n)[0..$hop_k] AS neigh
    UNWIND neigh AS nn
    MATCH (c2:Chunk)-[:MENTIONS]->(nn)
    RETURN e.type AS seed_entity_type, e.name AS seed_entity,
           nn.type AS neighbor_type, nn.name AS neighbor,
           c2.id AS related_chunk_id
    LIMIT 200
    """

    with driver.session() as session:
        for cid in seed_chunk_ids:
            rows = session.run(cypher, cid=cid, hop_k=cfg.hop_k).data()
            for r in rows:
                graph_paths.append(r)
                expanded_chunk_ids.append(r["related_chunk_id"])

    driver.close()

    # Add stable evidence_id for each path
    for i, p in enumerate(graph_paths):
        p["evidence_id"] = f"path:{i}"

    # Unique preserve order
    expanded_chunk_ids = list(dict.fromkeys(expanded_chunk_ids))

    # ---- Fetch expanded chunks back from Qdrant ----
    expanded_chunks: List[Dict[str, Any]] = []
    mapping: Dict[str, str] = {}

    mapping_path = Path(cfg.mapping_path)
    if mapping_path.exists():
        mapping = json.loads(mapping_path.read_text(encoding="utf-8"))

    expanded_point_ids = [mapping[cid] for cid in expanded_chunk_ids if cid in mapping]

    if expanded_point_ids:
        pts = qdrant.retrieve(
            collection_name=cfg.collection,
            ids=expanded_point_ids,
            with_payload=True,
        )
        for p in pts:
            payload = p.payload or {}
            chunk_id2 = payload.get("chunk_id")
            if not chunk_id2:
                continue

            doc_id2 = payload.get("doc_id")
            source_year2 = extract_source_year(doc_id2)
            if doc_id2 and source_year2 is not None:
                doc_years[doc_id2] = source_year2

            expanded_chunks.append(
                {
                    "evidence_id": f"exp:{chunk_id2}",
                    "chunk_id": chunk_id2,
                    "doc_id": doc_id2,
                    "source_year": source_year2,
                    "text": payload.get("text"),
                }
            )

    return {
        "query": query,
        "seed_chunks": seed_chunks,
        "graph_paths": graph_paths,
        "expanded_chunks": expanded_chunks,  # always present (maybe empty)
        "provenance": {
            "vector_db": "qdrant(local_path)",
            "qdrant_path": cfg.qdrant_path,
            "collection": cfg.collection,
            "graph_db": "neo4j",
            "neo4j_uri": cfg.neo4j_uri,
            "mapping_path": cfg.mapping_path,
            "top_k": cfg.top_k,
            "hop_k": cfg.hop_k,
            "seed_chunk_ids": seed_chunk_ids,
            "expanded_chunk_ids": expanded_chunk_ids,
            "doc_years": doc_years,
        },
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--query", required=True)
    p.add_argument("--qdrant_path", default="artifacts/qdrant_local")
    p.add_argument("--collection", default="filings_chunks")
    p.add_argument("--neo4j_uri", default="bolt://localhost:7687")
    p.add_argument("--neo4j_user", default="neo4j")
    p.add_argument("--neo4j_password", default="password")
    p.add_argument("--embed_model", default="sentence-transformers/all-MiniLM-L6-v2")
    p.add_argument("--top_k", type=int, default=5)
    p.add_argument("--hop_k", type=int, default=2)
    p.add_argument("--mapping_path", default="artifacts/chunkid_to_pointid.json")
    p.add_argument("--out_json", default="artifacts/graphrag_result.json")
    args = p.parse_args()

    cfg = RetrieveConfig(
        qdrant_path=args.qdrant_path,
        collection=args.collection,
        neo4j_uri=args.neo4j_uri,
        neo4j_user=args.neo4j_user,
        neo4j_password=args.neo4j_password,
        embed_model=args.embed_model,
        top_k=args.top_k,
        hop_k=args.hop_k,
        mapping_path=args.mapping_path,
        out_json_path=args.out_json,
    )

    out = graphrag_retrieve(args.query, cfg)

    Path("artifacts").mkdir(exist_ok=True)
    Path(cfg.out_json_path).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote {cfg.out_json_path}")

    print("Seed chunks:", len(out["seed_chunks"]))
    print("Graph paths:", len(out["graph_paths"]))
    print("Expanded chunks:", len(out["expanded_chunks"]))
    if out["graph_paths"]:
        print("Example path:", out["graph_paths"][0])
    if out["expanded_chunks"]:
        print("Example expanded chunk_id:", out["expanded_chunks"][0].get("chunk_id"))
        print("Example expanded evidence_id:", out["expanded_chunks"][0].get("evidence_id"))
        print("Example expanded source_year:", out["expanded_chunks"][0].get("source_year"))


if __name__ == "__main__":
    main()
