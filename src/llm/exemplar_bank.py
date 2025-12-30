# src/llm/exemplar_bank.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def append_exemplar_jsonl(path: str | Path, record: Dict[str, Any]) -> None:
    """Append a single exemplar record to a JSONL file.

    This is a lightweight alternative to true fine-tuning: you collect high-quality outputs,
    then feed 1-2 relevant exemplars back into prompts (few-shot) to steadily improve style.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_exemplars_jsonl(path: str | Path) -> List[Dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def select_exemplars(
    exemplars: List[Dict[str, Any]],
    focus: str,
    max_n: int = 2,
) -> List[Dict[str, Any]]:
    if not exemplars:
        return []
    focus_l = (focus or "").lower()
    ranked = []
    for ex in exemplars:
        ex_focus = str(ex.get("focus", "")).lower()
        score = 1 if (focus_l and focus_l in ex_focus) else 0
        ranked.append((score, ex))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return [ex for _, ex in ranked[:max_n]]
