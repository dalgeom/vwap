"""계기판 — 봇 고장 경보 + 환경 지표 기록 (2026-08-03).

경보는 '봇이 설계대로 도는가'만 본다. 시장 예측은 하지 않는다.
2026-08-03 검증에서 시장 지표(급등 구간 수익률)가 v10 호황기(7/16~28)에도 거의
매일 기준을 벗어나 경보로 쓸 수 없다는 게 드러났다. 시장 지표는 경보 없이
기록만 하고 매매일지의 재료로 넘긴다.

경보 지표는 정상일 때 값이 안정적이라 거짓 경보가 낮다는 점이 선정 기준이다.
"""
import json
from datetime import date
from pathlib import Path

METRICS_FILE = ("data", "daily_metrics.jsonl")

ALERT_KEYS = ("atr_accuracy", "position_match", "bar_gap",
              "slippage", "order_fail_rate")

# 같은 경보로 며칠간 재발동을 막는다 — 국면이 지속되면 매일 조사하는 낭비가 된다.
COOLDOWN_DAYS = 5
# 이 기간 내내 조용하면 강제 점검 1회 — 조용한 게 꼭 정상은 아니다.
QUIET_DAYS_FOR_SWEEP = 7

ATR_LOW, ATR_HIGH = 0.90, 1.10
BAR_GAP_MAX = 1                 # 1봉 누락은 스캔 타이밍으로 생길 수 있어 용인
SLIPPAGE_MEDIAN_PCT = 0.5
SLIPPAGE_WORST_PCT = 2.0
ORDER_FAIL_RATE = 0.40


def recompute_atr(bars: list, end_idx: int, period: int = 20) -> float | None:
    """(ts, high, low, close) 봉으로 end_idx를 마지막으로 하는 SMA ATR.

    momentum.MomentumStrategy._compute_atr 과 같은 공식이다. 봇이 기록한
    atr_at_entry 와 대조해 캔들 캐시 오염을 감시한다(2026-08-03 결함).
    """
    if end_idx < period:
        return None
    trs = []
    for j in range(end_idx - period + 1, end_idx + 1):
        _, h, l, _ = bars[j]
        pc = bars[j - 1][3]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / period


def atr_ratios_for_day(trades: list, fetch_bars) -> list[float]:
    """진입 건별 (봇 ATR ÷ 재계산 ATR). 1.00이 정상.

    fetch_bars(symbol) -> [(ts, high, low, close)] 를 주입받는다(테스트·오프라인 대비).
    조회 실패한 종목은 조용히 건너뛴다 — 거래소가 죽어도 리포트는 진행돼야 한다.
    """
    from datetime import datetime
    out, cache = [], {}
    for t in trades:
        bot_atr = t.get("atr_at_entry")
        ts_iso = t.get("timestamp_utc")
        if not bot_atr or not ts_iso:
            continue
        sym = t.get("symbol")
        if sym not in cache:
            try:
                cache[sym] = fetch_bars(sym)
            except Exception:
                cache[sym] = []
        bars = cache[sym]
        if not bars:
            continue
        try:
            ms = datetime.fromisoformat(ts_iso).timestamp() * 1000
        except (ValueError, TypeError):
            continue
        idx = max((i for i in range(len(bars)) if bars[i][0] <= ms), default=None)
        if idx is None:
            continue
        real = recompute_atr(bars, idx)
        if real:
            out.append(round(bot_atr / real, 4))
    return out


def _median(xs: list[float]) -> float | None:
    v = sorted(x for x in xs if x is not None)
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def compute_metrics(*, day: str, trades: list, entered: list, shadow: list,
                    slippage: list, atr_ratios: list, position_match: bool,
                    bar_gap: int, market: dict | None = None) -> dict:
    """하루치 지표 한 벌. 측정만 하고 판정은 check_alerts가 한다.

    trades:     그날 '청산'된 거래 (승률·손절률의 모집단)
    entered:    그날 '진입'한 거래 (신호 수·ATR 대조의 모집단)
                ★ 2026-08-06 수리: 둘을 같은 인자로 받아 n_entries가 청산 수를,
                  order_fail_rate가 청산을 신호로 세고 있었다(08-05 일지가 발견).
    atr_ratios: 진입 건별 (봇 atr_at_entry ÷ 같은 시점 재계산 ATR).
                진입이 없으면 빈 리스트 → atr_accuracy None(경보 대상 아님).
    market:     유니버스 전체 기준 시장 지표(경보 없음, 일지 재료).
    """
    sl = [s.get("slippage_pct") or 0.0 for s in slippage]
    signals = len(entered) + len(shadow)
    fails = sum(1 for s in shadow if s.get("shadow_reason") == "order_failed")
    closed = [t for t in trades if t.get("exit_reason")]
    m = {
        "day": day,
        "atr_accuracy": _median(atr_ratios),
        "position_match": position_match,
        "bar_gap": bar_gap,
        "slippage_median_pct": _median(sl) or 0.0,
        "slippage_worst_pct": max(sl) if sl else 0.0,
        "order_fail_rate": (fails / signals) if signals else 0.0,
        "sl_rate": (sum(1 for t in closed if t["exit_reason"] == "SL") / len(closed))
                   if closed else 0.0,
        "n_entries": len(entered),
        "n_closed": len(trades),
        "n_blocked": len(shadow),
        "alerts": [],
    }
    m.update(market or {})
    return m


def _violations(m: dict) -> list[tuple[str, str]]:
    """오늘 값이 경보선을 벗어났는가. (키, 사람이 읽는 메시지) 목록."""
    out = []
    a = m.get("atr_accuracy")
    if a is not None and not (ATR_LOW <= a <= ATR_HIGH):
        out.append(("atr_accuracy",
                    f"ATR 정확도 {a:.2f} (정상 1.00) — 봇이 쓰는 ATR이 실제와 어긋납니다. "
                    "손절선이 설계와 다른 자리에 놓입니다"))
    if m.get("position_match") is False:
        out.append(("position_match",
                    "거래소 포지션과 state가 불일치 — 고아 포지션 가능성"))
    gap = m.get("bar_gap") or 0
    if gap > BAR_GAP_MAX:
        out.append(("bar_gap", f"봉 {gap}개 누락 — 스캔이 걸렀거나 봇이 멈췄습니다"))
    med = m.get("slippage_median_pct") or 0.0
    worst = m.get("slippage_worst_pct") or 0.0
    if med >= SLIPPAGE_MEDIAN_PCT or worst >= SLIPPAGE_WORST_PCT:
        out.append(("slippage",
                    f"슬리피지 중앙 {med:.2f}% / 최악 {worst:.2f}% — 체결이 밀립니다"))
    fr = m.get("order_fail_rate") or 0.0
    if fr >= ORDER_FAIL_RATE:
        out.append(("order_fail_rate",
                    f"주문 실패율 {fr * 100:.0f}% — 거래소 거부가 진입을 막고 있습니다"))
    return out


def _fired_days(key: str, history: list[dict]) -> list[str]:
    return [h.get("day") for h in history if key in (h.get("alerts") or []) and h.get("day")]


def _suppressed(key: str, today: str | None, history: list[dict]) -> bool:
    """쿨다운 판정. 마지막 발동 뒤 정상 복귀한 날이 있으면 쿨다운은 풀린다."""
    fired = _fired_days(key, history)
    if not fired or not today:
        return False
    last = max(fired)
    for h in history:
        d = h.get("day")
        if d and d > last and key not in (h.get("alerts") or []):
            return False          # 해소됨 → 재발동 허용
    try:
        gap = (date.fromisoformat(today) - date.fromisoformat(last)).days
    except ValueError:
        return False
    return gap < COOLDOWN_DAYS


def _needs_sweep(history: list[dict]) -> bool:
    if len(history) < QUIET_DAYS_FOR_SWEEP:
        return False
    return all(not (h.get("alerts") or []) for h in history[-QUIET_DAYS_FOR_SWEEP:])


def check_alerts(today: dict, history: list[dict]) -> list[dict]:
    """오늘 울려야 할 경보 목록. 쿨다운·해소·주간점검을 반영한다."""
    out = []
    for key, msg in _violations(today):
        if not _suppressed(key, today.get("day"), history):
            out.append({"key": key, "message": msg})
    if not out and _needs_sweep(history):
        out.append({"key": "weekly_sweep",
                    "message": f"{QUIET_DAYS_FOR_SWEEP}일간 경보 없음 — 주간 강제 점검"})
    return out


def summarize_alerts(alerts: list[dict]) -> str:
    return " / ".join(a["message"] for a in alerts) if alerts else ""


# ── 저장·조회 ────────────────────────────────────────────
def _path(project_root: Path, demo: bool | None = None) -> Path:
    """demo/real 분리(2026-08-10): real 지표는 data/real/에 산다. None이면 config로 판별."""
    from vwap_trader.mode_paths import data_dir, read_demo_flag
    if demo is None:
        demo = read_demo_flag(project_root)
    return data_dir(project_root, demo) / METRICS_FILE[-1]


def append_metrics(project_root: Path, metrics: dict, demo: bool | None = None) -> None:
    p = _path(project_root, demo)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(metrics, ensure_ascii=False) + "\n")


def read_metrics(project_root: Path, days: int = 30, demo: bool | None = None) -> list[dict]:
    p = _path(project_root, demo)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out[-days:]
