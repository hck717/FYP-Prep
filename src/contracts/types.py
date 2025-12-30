# src/contracts/types.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------- SQL tool output ----------
@dataclass(frozen=True)
class SqlMeta:
    tool: str
    db_path: str
    max_limit: int
    allowlisted_tables: List[str]
    raw_preview: str = ""



@dataclass(frozen=True)
class SqlResult:
    query: str
    columns: List[str]
    rows: List[List[Any]]
    meta: SqlMeta
    sql_evidence_id: str  # stable reference you can cite later


# ---------- EvidencePack (GraphRAG tool output) ----------
@dataclass(frozen=True)
class EvidenceChunk:
    evidence_id: str           # e.g. "seed:<chunk_id>" or "exp:<chunk_id>"
    chunk_id: str
    doc_id: Optional[str]
    text: Optional[str]
    score: Optional[float] = None


@dataclass(frozen=True)
class EvidencePack:
    query: str
    seed_chunks: List[EvidenceChunk] = field(default_factory=list)
    expanded_chunks: List[EvidenceChunk] = field(default_factory=list)
    graph_paths: List[Dict[str, Any]] = field(default_factory=list)
    provenance: Dict[str, Any] = field(default_factory=dict)


# ---------- Skill outputs ----------
@dataclass(frozen=True)
class FundamentalsInputs:
    ticker: str
    horizon: str = "8q"
    focus: str = "overall"


@dataclass(frozen=True)
class ValuationInputs:
    ticker: str
    horizon: str = "12m"
    base_case: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FundamentalsJSON:
    ticker: str
    horizon: str
    financials_summary: Dict[str, Any]
    drivers: List[Dict[str, Any]]
    risks: List[Dict[str, Any]]


@dataclass(frozen=True)
class ValuationJSON:
    ticker: str
    horizon: str
    valuation_range: Dict[str, Any]
    assumptions: List[Dict[str, Any]]
    sensitivity: Dict[str, Any]
