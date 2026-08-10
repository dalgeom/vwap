"""화면용 데이터 공급. 거래는 반드시 정본 로더(A-1 load_canonical) 경유 —
raw jsonl 직접 합산 금지(과거 PnL 버그 오염, PLAN §데이터 규율).
잭팟 판정은 절대기준 R≥7.8(§5.13) — daily_report.JACKPOT_R 재사용(DRY)."""
import json
import re
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
EQUITY_FILE = ("data", "equity_history.jsonl")
_REPORT_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EQUITY_RE = re.compile(r"현재 자산은 \*\*\$([\d,]+(?:\.\d+)?)\*\*")


def _mode_data(project_root: Path, demo: bool | None) -> Path:
    """demo/real 분리(2026-08-10): real 계좌 산출물은 data/real/에 산다."""
    from vwap_trader.mode_paths import data_dir, read_demo_flag
    if demo is None:
        demo = read_demo_flag(project_root)
    return data_dir(project_root, demo)


def _mode_reports(project_root: Path, demo: bool | None) -> Path:
    from vwap_trader.mode_paths import read_demo_flag, reports_dir
    if demo is None:
        demo = read_demo_flag(project_root)
    return reports_dir(project_root, demo)


def load_trades(project_root: Path, demo: bool | None = None) -> list:
    from build_canonical import load_canonical
    from corrections import read_corrections
    dd = _mode_data(project_root, demo)
    corr = read_corrections(dd / "pnl_corrections.jsonl")
    return load_canonical(
        raw_path=dd / "trades_momentum.jsonl",
        corrected_path=dd / "trades_momentum_corrected.jsonl",
        corrections=corr)


def visible_trades(trades: list) -> list:
    """v11 표시 경계 이후 청산만 — 화면용. 정본(load_trades)은 전량 그대로 둔다."""
    from daily_report import visible_trades as _filter   # 리포트와 같은 경계를 쓴다(DRY)
    return _filter(trades)


def trade_r(t: dict) -> float:
    """손절 각오액 대비 몇 배 벌었나. 리스크 산출 불가(결손)면 0.0 — 잭팟 오인 방지."""
    from daily_report import risk_usd
    risk = risk_usd(t)
    if not risk:
        return 0.0
    return (t.get("pnl_usd", 0) or 0) / risk


def _jackpot_r() -> float:
    from daily_report import JACKPOT_R
    return JACKPOT_R


def summarize(trades: list) -> dict:
    from daily_report import _agg
    a = _agg(trades)   # 일일 리포트와 같은 계산기 — 화면·리포트 숫자 불일치 방지
    cut = _jackpot_r()
    return {"n": a["n"], "total": round(a["total"], 2),
            "win_rate": round(a["wr"], 1), "ev": round(a["ev"], 2),
            "jackpots": sum(1 for t in trades if trade_r(t) >= cut)}


def trades_for_ui(trades: list) -> list:
    cut = _jackpot_r()
    out = []
    for t in reversed(trades):   # 최신 먼저
        ts = t.get("exit_timestamp_utc") or t.get("timestamp_utc") or ""
        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)   # naive → UTC 간주
            ts_kst = dt.astimezone(KST).strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            ts_kst = ts
        out.append({
            "ts": ts_kst,
            "symbol": t.get("symbol", "?"),
            "side": {"long": "롱", "short": "숏"}.get(t.get("side"), "?"),
            "entry": t.get("entry_price"),
            "exit": t.get("exit_price"),
            "pnl": round(t.get("pnl_usd", 0) or 0, 2),
            "hold_h": float(t.get("hold_time_bars", 0) or 0),   # 1bar=1h
            "arm": {"A": "본전잠금 느린(A)", "B": "본전잠금 빠른(B)"}.get(t.get("ab_arm"), "-"),
            "jackpot": trade_r(t) >= cut,
        })
    return out


# ── 리포트 ──────────────────────────────────────────────
def list_reports(project_root: Path, demo: bool | None = None) -> list[str]:
    rd = _mode_reports(project_root, demo)
    if not rd.exists():
        return []
    days = [f.stem for f in rd.glob("*.md") if _REPORT_DAY_RE.match(f.stem)]
    return sorted(days, reverse=True)


def visible_reports(project_root: Path, demo: bool | None = None) -> list[str]:
    """v11 표시 경계 날짜부터 — 화면용. 백필·연구는 list_reports(전체)를 계속 쓴다."""
    from daily_report import DISPLAY_SINCE
    cut = DISPLAY_SINCE.astimezone(KST).date().isoformat()
    return [d for d in list_reports(project_root, demo) if d >= cut]


def read_report(project_root: Path, day: str, demo: bool | None = None) -> str | None:
    if not _REPORT_DAY_RE.match(day):   # 경로 탈출 차단
        return None
    p = _mode_reports(project_root, demo) / f"{day}.md"
    return p.read_text(encoding="utf-8") if p.exists() else None


# ── 자산 이력 (exe가 기록자 — 설계 결정) ─────────────
def _equity_path(project_root: Path, demo: bool | None = None) -> Path:
    return _mode_data(project_root, demo) / EQUITY_FILE[-1]


def append_equity(project_root: Path, ts_utc: datetime, equity: float,
                  demo: bool | None = None) -> None:
    ts = ts_utc if ts_utc.tzinfo else ts_utc.replace(tzinfo=timezone.utc)
    p = _equity_path(project_root, demo)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": ts.astimezone(timezone.utc).isoformat(),
                            "equity": round(equity, 2)}) + "\n")


def read_equity_history(project_root: Path, demo: bool | None = None) -> list[dict]:
    p = _equity_path(project_root, demo)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def last_equity_ts(project_root: Path, demo: bool | None = None) -> datetime | None:
    hist = read_equity_history(project_root, demo)
    if not hist:
        return None
    ts = datetime.fromisoformat(hist[-1]["ts"])
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def backfill_from_reports(project_root: Path, demo: bool | None = None) -> list[dict]:
    """일일 리포트의 자산 문구에서 과거 점 복원. 리포트는 D+1 00:30 KST 생성이므로 그 시각."""
    out = []
    for day in sorted(list_reports(project_root, demo)):
        text = read_report(project_root, day, demo) or ""
        m = _EQUITY_RE.search(text)
        if not m:
            continue
        d = date.fromisoformat(day)
        ts = datetime.combine(d + timedelta(days=1), dtime(0, 30), tzinfo=KST)
        out.append({"ts": ts.astimezone(timezone.utc).isoformat(),
                    "equity": float(m.group(1).replace(",", ""))})
    return out


def equity_series(project_root: Path, demo: bool | None = None) -> list[dict]:
    """차트용 자산 시계열 — 리포트 백필(라이브 이전 구간) + 라이브 기록 병합.
    라이브 점이 생겨도 과거 백필 이력은 유지된다."""
    live = read_equity_history(project_root, demo)
    backfill = backfill_from_reports(project_root, demo)
    if not live:
        return backfill
    first_live = live[0]["ts"]
    return [p for p in backfill if p["ts"] < first_live] + live


def visible_equity_series(project_root: Path, demo: bool | None = None) -> list[dict]:
    """v11 표시 경계 이후 구간만 — 감액(31,632→695)이 만든 절벽을 곡선에서 걷어낸다."""
    from daily_report import DISPLAY_SINCE
    out = []
    for p in equity_series(project_root, demo):
        ts = datetime.fromisoformat(p["ts"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts >= DISPLAY_SINCE:
            out.append(p)
    return out
