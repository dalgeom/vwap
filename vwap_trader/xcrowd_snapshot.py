# -*- coding: utf-8 -*-
"""횡단면 군중 역발상 — forward 검증용 일일 원자료 스냅샷 로거.

★ 봇 무관·순수 기록. src/vwap_trader/momentum_bot.py 및 봇 데이터 파일을 절대
읽거나 쓰지 않는다. 실주문·포지션 없음. 하루 1회 실행돼 data/xcrowd_snapshots.jsonl 에
"그날의 원자료" 1줄을 append 한다.

────────────────────────────────────────────────────────────────────────
사전등록 사양 (동결 — 로직 "개선" 금지, 스냅샷만 정확히 남긴다)
────────────────────────────────────────────────────────────────────────
전략(평가는 약 60거래일 후 별도): 매일 알트 유니버스를 롱숏비율(buyRatio)로 정렬 →
덜 붐비는 하위 N개 롱 / 가장 붐비는 상위 N개 숏, 달러중립.

이 스크립트는 바스켓·손익을 계산해 저장하지 않는다. **원자료(그날 유니버스 +
각 코인 buyRatio + 종가)만** 남긴다. 이유: ①나중에 N=3/5/7/10 등 어떤 변형도
재평가 가능 ②그날의 실제 유니버스가 박제된다(소급하면 생존편향 — 로깅의 최대 이유).

정의:
- 대상 UTC 날짜 = 마지막으로 완료된 UTC 일자(= 실행 시각 기준 어제). 이미 기록된
  날짜면 아무것도 안 하고 종료(멱등).
- 유니버스 = 봇과 동일: get_tickers(linear)에서 심볼 USDT로 끝나고 turnover24h ≥
  10_000_000, BTCUSDT 제외.
- 코인별: buyRatio = get_long_short_ratio(period=1d) 중 대상날짜 자정 UTC 값,
  close = get_kline(interval=D) 중 대상날짜 완료 일봉 종가. 둘 중 하나라도 없으면
  그 코인 제외(사유 카운트만).

⚠️ 설계 동결본(docs/superpowers/specs/2026-07-21-xs-crowd-contrarian-FOUND.md)이
부재해, 이 docstring이 사전등록 사양의 유일 정본이다(2026-07-22 확인).
"""
import json
import time
import sys
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "xcrowd_snapshots.jsonl"
LOG = ROOT / "logs" / "xcrowd_snapshot.log"
MIN_VOL = 10_000_000
BLACKLIST = ("BTCUSDT",)


# ── 순수함수 (테스트 대상) ─────────────────────────────────

def target_utc_date(now_utc: datetime) -> date:
    """마지막으로 완료된 UTC 일자 = 어제(오늘 봉은 미완이므로)."""
    return now_utc.date() - timedelta(days=1)


def date_to_midnight_ms(d: date) -> int:
    """UTC 자정 epoch ms. long_short_ratio·일봉 timestamp 매칭 키."""
    dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def parse_recorded_dates(lines) -> set:
    """기존 jsonl 줄들에서 date 집합(멱등 판정용). 빈 줄·파싱실패 무시."""
    out = set()
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.add(json.loads(ln)["date"])
        except (ValueError, KeyError):
            continue
    return out


def buy_ratio_at(ls_list, ts_ms: int):
    """long_short_ratio 리스트에서 timestamp==ts_ms인 buyRatio(float). 없으면 None."""
    for row in ls_list:
        if int(row["timestamp"]) == ts_ms:
            return float(row["buyRatio"])
    return None


def close_at(kline_list, ts_ms: int):
    """일봉 리스트에서 [0]==ts_ms인 종가 [4](float). 없으면 None."""
    for row in kline_list:
        if int(row[0]) == ts_ms:
            return float(row[4])
    return None


# ── I/O (수동 실행·스케줄러로 검증) ─────────────────────────

def _log(msg: str):
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _build_client():
    from backtest_delayed_entry import build_client
    return build_client()


def _universe(client):
    r = client.get_tickers(category="linear")
    return [t["symbol"] for t in r["result"]["list"]
            if t["symbol"].endswith("USDT") and t["symbol"] not in BLACKLIST
            and float(t.get("turnover24h", 0)) >= MIN_VOL]


def run(now_utc: datetime | None = None) -> str | None:
    """대상날짜 스냅샷 1줄 append. 이미 있으면 skip. 반환=기록한 날짜 or None."""
    now_utc = now_utc or datetime.now(timezone.utc)
    tgt = target_utc_date(now_utc)
    date_str = tgt.isoformat()
    ts_ms = date_to_midnight_ms(tgt)

    if OUT.exists():
        with open(OUT, encoding="utf-8") as f:
            if date_str in parse_recorded_dates(f):
                _log(f"{date_str} 이미 기록됨 — skip(멱등)")
                return None

    client = _build_client()
    universe = _universe(client)
    rows, miss_ratio, miss_close = [], 0, 0
    for i, sym in enumerate(universe, 1):
        try:
            lr = client.get_long_short_ratio(category="linear", symbol=sym,
                                             period="1d", limit=200)
            br = buy_ratio_at(lr["result"]["list"], ts_ms)
            time.sleep(0.1)
            kl = client.get_kline(category="linear", symbol=sym,
                                  interval="D", limit=200)
            cl = close_at(kl["result"]["list"], ts_ms)
            time.sleep(0.1)
        except Exception as e:
            _log(f"  {sym} fetch 실패: {type(e).__name__} {e}")
            continue
        if br is None:
            miss_ratio += 1
            continue
        if cl is None:
            miss_close += 1
            continue
        rows.append({"symbol": sym, "buy_ratio": br, "close": cl})

    record = {"date": date_str, "n_universe": len(universe), "n_ok": len(rows),
              "rows": rows, "fetched_at": datetime.now(timezone.utc).isoformat()}
    OUT.parent.mkdir(exist_ok=True)
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    _log(f"{date_str} 기록: 유니버스 {len(universe)} → 정상 {len(rows)} "
         f"(비율누락 {miss_ratio}, 종가누락 {miss_close})")
    return date_str


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        _log(f"치명 오류: {type(e).__name__} {e}")
        sys.exit(1)
