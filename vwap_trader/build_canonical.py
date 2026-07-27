"""A-1: 정본 자동 병합기 — corrected + raw 필드유니온 + corrections 오버레이.
입력 3파일(trades_momentum_corrected / trades_momentum / pnl_corrections)은 전부 읽기 전용.
분석에서는: from build_canonical import load_canonical
스냅샷 파일 생성: python build_canonical.py → data/trades_canonical.jsonl
"""
import json
import os
from pathlib import Path

from corrections import apply_corrections

_ENV_ROOT = os.environ.get("VWAP_PROJECT_ROOT")
ROOT = Path(_ENV_ROOT).resolve() if _ENV_ROOT else Path(__file__).resolve().parent
RAW = ROOT / "data" / "trades_momentum.jsonl"
CORRECTED = ROOT / "data" / "trades_momentum_corrected.jsonl"
OUT = ROOT / "data" / "trades_canonical.jsonl"


def _load_jsonl(path) -> list:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def merge_trades(raw: list, corrected: list) -> list:
    """corrected 값 우선 필드유니온 + raw-only 통과 + canonical_src 표식 + 청산시각 정렬.
    입력 내부 trade_id 중복 시 즉시 예외(조용한 오염 금지)."""
    raw_by_id = {t["trade_id"]: t for t in raw}
    if len(raw_by_id) != len(raw):
        raise ValueError("raw trades 내 trade_id 중복 — 정본 생성 중단")
    if len({c["trade_id"] for c in corrected}) != len(corrected):
        raise ValueError("corrected 내 trade_id 중복 — 정본 생성 중단")
    out, seen = [], set()
    for c in corrected:
        tid = c["trade_id"]
        out.append({**raw_by_id.get(tid, {}), **c, "canonical_src": "corrected+raw"})
        seen.add(tid)
    for t in raw:
        if t["trade_id"] not in seen:
            out.append({**t, "canonical_src": "raw"})
    out.sort(key=lambda t: t.get("exit_timestamp_utc") or t.get("timestamp_utc") or "")
    return out


def load_canonical(raw_path=RAW, corrected_path=CORRECTED, corrections=None) -> list:
    """정본 로드: corrected+raw 필드유니온 → corrections 오버레이 → 정렬된 list 반환.
    corrections=None이면 data/pnl_corrections.jsonl 자동 사용(corrections.py 기본값)."""
    if not Path(raw_path).exists():
        raise FileNotFoundError(f"raw trades 없음: {raw_path}")
    raw = _load_jsonl(raw_path)
    corrected = _load_jsonl(corrected_path)
    if not corrected:
        print(f"⚠ corrected 파일 없음/비어있음 — raw+corrections만으로 정본 생성: {corrected_path}")
    return apply_corrections(merge_trades(raw, corrected), corrections)


def main():
    from collections import Counter
    trades = load_canonical()
    with open(OUT, "w", encoding="utf-8") as f:
        for t in trades:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    total = sum(t.get("pnl_usd") or 0 for t in trades)
    print(f"정본 {len(trades)}건 → {OUT}")
    print(f"누적 PnL: ${total:,.2f}")
    print(f"canonical_src: {dict(Counter(t['canonical_src'] for t in trades))}")
    print(f"pnl_source: {dict(Counter(t.get('pnl_source') for t in trades))}")


if __name__ == "__main__":
    main()
