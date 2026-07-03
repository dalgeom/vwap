"""거래소 실값 정정 오버레이 (A-2). 원본 trades는 절대 수정하지 않는다."""
import json
from pathlib import Path

CORRECTIONS_FILE = Path(__file__).resolve().parent / "data" / "pnl_corrections.jsonl"


def read_corrections(path=None) -> dict:
    """trade_id -> correction dict. 파일 없으면 빈 dict."""
    path = path or CORRECTIONS_FILE
    out = {}
    p = Path(path)
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        out[d["trade_id"]] = d
    return out


def append_correction(rec: dict, path=None):
    """corrections 파일에 1줄 append (원본 trades 무관)."""
    path = path or CORRECTIONS_FILE
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def apply_corrections(trades: list, corrections: dict | None = None) -> list:
    """원본 trade 리스트에 corrections를 trade_id로 오버레이한 새 리스트 반환."""
    if corrections is None:
        corrections = read_corrections()
    out = []
    for t in trades:
        c = corrections.get(t.get("trade_id"))
        if c:
            t = {**t, "pnl_usd": c["pnl_usd"], "exit_price": c["exit_price"],
                 "pnl_pct": c["pnl_pct"], "pnl_source": c["src"]}
        out.append(t)
    return out
