"""A-1: 정본 자동 병합기 — corrected + raw 필드유니온 + corrections 오버레이.
입력 3파일(trades_momentum_corrected / trades_momentum / pnl_corrections)은 전부 읽기 전용.
분석에서는: from build_canonical import load_canonical
스냅샷 파일 생성: python build_canonical.py → data/trades_canonical.jsonl
"""
import json
from pathlib import Path

from corrections import apply_corrections

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "trades_momentum.jsonl"
CORRECTED = ROOT / "data" / "trades_momentum_corrected.jsonl"
OUT = ROOT / "data" / "trades_canonical.jsonl"


def _load_jsonl(path) -> list:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def merge_trades(raw: list, corrected: list) -> list:
    """corrected 값 우선 필드유니온 + raw-only 통과 + canonical_src 표식."""
    raw_by_id = {t["trade_id"]: t for t in raw}
    out, seen = [], set()
    for c in corrected:
        tid = c["trade_id"]
        out.append({**raw_by_id.get(tid, {}), **c, "canonical_src": "corrected+raw"})
        seen.add(tid)
    for t in raw:
        if t["trade_id"] not in seen:
            out.append({**t, "canonical_src": "raw"})
    return out
