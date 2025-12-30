from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

from neo4j import GraphDatabase
from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer


@dataclass(frozen=True)
class Config:
    docs_dir: str
    qdrant_path: str
    qdrant_collection: str
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    embed_model: str
    chunk_size: int
    out_mapping_path: str


def chunk_text(text: str, chunk_size: int) -> List[str]:
    text = " ".join(text.split())
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size) if text[i : i + chunk_size].strip()]


def make_chunk_id(doc_id: str, idx: int, chunk: str) -> str:
    h = hashlib.sha1(chunk.encode("utf-8")).hexdigest()[:10]
    return f"{doc_id}:{idx}:{h}"


def stable_uuid(text: str) -> str:
    # Qdrant point ids must be UUID or unsigned int; this is deterministic UUID from text. [web:349]
    return str(uuid.uuid5(uuid.NAMESPACE_URL, text))


def extract_entities(chunk: str) -> List[Tuple[str, str]]:
    rules = {
        "Company": ["Apple", "AAPL"],
        "Segment": ["Services", "iPhone", "Mac", "iPad", "Wearables"],
        "Product": ["App Store", "iCloud", "Apple Music", "Apple TV+", "Apple Pay"],
        "Metric": ["revenue", "gross margin", "installed base", "ARPU", "subscriptions", "paid subscriptions", "paying accounts"],
        "Risk": ["regulation", "antitrust", "competition", "FX", "privacy"],
    }
    out = []
    lower = chunk.lower()
    for etype, names in rules.items():
        for n in names:
            if n.lower() in lower:
                out.append((etype, n))
    seen = set()
    uniq = []
    for e in out:
        if e not in seen:
            uniq.append(e)
            seen.add(e)
    return uniq


def neo4j_upsert_graph(driver, chunk_id: str, entities: List[Tuple[str, str]]) -> None:
    with driver.session() as session:
        session.run("MERGE (c:Chunk {id: $id})", id=chunk_id)

        for etype, name in entities:
            session.run(
                "MERGE (e:Entity {type: $type, name: $name}) "
                "WITH e "
                "MATCH (c:Chunk {id: $chunk_id}) "
                "MERGE (c)-[:MENTIONS]->(e)",
                type=etype,
                name=name,
                chunk_id=chunk_id,
            )

        # CO_OCCURS edges
        for i in range(len(entities)):
            for j in range(i + 1, len(entities)):
                (t1, n1), (t2, n2) = entities[i], entities[j]
                session.run(
                    "MATCH (a:Entity {type:$t1, name:$n1}), (b:Entity {type:$t2, name:$n2}) "
                    "MERGE (a)-[:CO_OCCURS]->(b) "
                    "MERGE (b)-[:CO_OCCURS]->(a)",
                    t1=t1,
                    n1=n1,
                    t2=t2,
                    n2=n2,
                )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--docs_dir", default="data/docs")
    p.add_argument("--qdrant_path", default="artifacts/qdrant_local")
    p.add_argument("--collection", default="filings_chunks")
    p.add_argument("--neo4j_uri", default="bolt://localhost:7687")
    p.add_argument("--neo4j_user", default="neo4j")
    p.add_argument("--neo4j_password", default="password")
    p.add_argument("--embed_model", default="sentence-transformers/all-MiniLM-L6-v2")
    p.add_argument("--chunk_size", type=int, default=900)
    p.add_argument("--out_mapping", default="artifacts/chunkid_to_pointid.json")
    args = p.parse_args()

    cfg = Config(
        docs_dir=args.docs_dir,
        qdrant_path=args.qdrant_path,
        qdrant_collection=args.collection,
        neo4j_uri=args.neo4j_uri,
        neo4j_user=args.neo4j_user,
        neo4j_password=args.neo4j_password,
        embed_model=args.embed_model,
        chunk_size=args.chunk_size,
        out_mapping_path=args.out_mapping,
    )

    Path(cfg.qdrant_path).mkdir(parents=True, exist_ok=True)
    Path("artifacts").mkdir(parents=True, exist_ok=True)

    # Qdrant local persistent
    qdrant = QdrantClient(path=cfg.qdrant_path)
    embedder = SentenceTransformer(cfg.embed_model)
    dim = embedder.get_sentence_embedding_dimension()

    existing = {c.name for c in qdrant.get_collections().collections}
    if cfg.qdrant_collection not in existing:
        qdrant.create_collection(
            collection_name=cfg.qdrant_collection,
            vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
        )

    # Neo4j
    driver = GraphDatabase.driver(cfg.neo4j_uri, auth=(cfg.neo4j_user, cfg.neo4j_password))

    docs = sorted(Path(cfg.docs_dir).glob("*.txt"))
    if not docs:
        raise SystemExit(f"No .txt docs found in {cfg.docs_dir}")

    points: List[models.PointStruct] = []
    chunkid_to_pointid: Dict[str, str] = {}

    for doc_path in docs:
        doc_text = doc_path.read_text(encoding="utf-8")
        doc_id = doc_path.stem

        chunks = chunk_text(doc_text, cfg.chunk_size)
        vectors = embedder.encode(chunks, normalize_embeddings=True)

        for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
            chunk_id = make_chunk_id(doc_id, i, chunk)
            point_id = stable_uuid(chunk_id)

            payload = {
                "doc_id": doc_id,
                "chunk_id": chunk_id,   # used by Neo4j + for audit
                "point_id": point_id,   # Qdrant UUID id (debug)
                "text": chunk,
            }

            points.append(models.PointStruct(id=point_id, vector=vec.tolist(), payload=payload))
            chunkid_to_pointid[chunk_id] = point_id

            ents = extract_entities(chunk)
            neo4j_upsert_graph(driver, chunk_id, ents)

    qdrant.upsert(collection_name=cfg.qdrant_collection, points=points)  # PointStruct upsert [web:349]

    Path(cfg.out_mapping_path).write_text(json.dumps(chunkid_to_pointid, indent=2), encoding="utf-8")

    driver.close()
    print(f"Done. Indexed {len(points)} chunks into Qdrant and Neo4j.")
    print(f"Wrote mapping: {cfg.out_mapping_path}")


if __name__ == "__main__":
    main()
