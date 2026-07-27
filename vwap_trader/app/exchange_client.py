"""읽기 전용 거래소 조회 — 주문 계열 메서드는 이 모듈에 절대 추가하지 않는다.
호출 시점 주의: 봇이 정각(분=0)에 스캔하므로 스케줄러 틱은 정각을 피해 호출."""
from pathlib import Path

from pybit.unified_trading import HTTP

from app.settings import read_env_keys, read_demo_flag


def apply_clock_offset(offset_ms: float) -> None:
    """앱 프로세스의 pybit 서명 타임스탬프에 서버−로컬 오프셋 반영 (멱등 — 재호출 시 누적 없음).
    봇 프로세스는 momentum_bot이 자체 보정하므로 이 함수는 앱 전용."""
    import pybit._helpers as h
    if not hasattr(h, "_app_orig_ts"):
        h._app_orig_ts = h.generate_timestamp
    h.generate_timestamp = lambda: h._app_orig_ts() + int(offset_ms)


def build_private_client(project_root: Path) -> HTTP:
    keys = read_env_keys(project_root / "config" / ".env")
    if not keys["BYBIT_API_KEY"] or not keys["BYBIT_API_SECRET"]:
        raise RuntimeError("API 키가 설정되지 않았습니다 — 설정 탭에서 먼저 입력하세요.")
    from app.safety import measure_clock_offset_ms
    offset = measure_clock_offset_ms()
    if offset is not None:
        apply_clock_offset(offset)
    demo = read_demo_flag(project_root / "config" / "momentum_config.yaml")
    return HTTP(testnet=False, demo=demo, timeout=5, max_retries=1, retry_delay=1,
                api_key=keys["BYBIT_API_KEY"], api_secret=keys["BYBIT_API_SECRET"])


def get_equity(client: HTTP) -> float:
    lst = client.get_wallet_balance(accountType="UNIFIED")["result"]["list"]
    if not lst:
        raise RuntimeError("잔고 정보가 비어 있습니다 — 통합계좌(UNIFIED)인지, 키에 지갑 조회 권한이 있는지 확인하세요.")
    return float(lst[0]["totalEquity"])


def get_positions(client: HTTP) -> list[dict]:
    r = client.get_positions(category="linear", settleCoin="USDT")
    out = []
    for p in r["result"]["list"]:
        if float(p.get("size", 0) or 0) == 0:
            continue
        out.append({
            "symbol": p["symbol"],
            "side": "롱" if p["side"] == "Buy" else "숏",
            "size": p["size"],
            "entry": p["avgPrice"],
            "mark": p["markPrice"],
            "unrealised": round(float(p.get("unrealisedPnl", 0) or 0), 2),
            "stop_loss": p.get("stopLoss") or "-",
        })
    return out


def friendly_error(e: Exception) -> str:
    m = str(e)
    if "10002" in m:
        return ("PC 시계가 거래소 서버와 어긋난 것 같습니다 — 관리자 PowerShell에서 "
                "'w32tm /resync /force' 실행 후 다시 시도하세요.")
    if any(c in m for c in ("10003", "10004", "10005")):
        return "API 키/시크릿이 올바르지 않거나 읽기 권한이 부족합니다."
    if "Retries exceeded" in m or "retries exceeded" in m:
        return "거래소 응답이 지연되고 있습니다 — 잠시 후 다시 시도하세요."
    return m.splitlines()[0] if m else "알 수 없는 오류"


def validate_keys(api_key: str, api_secret: str, demo: bool) -> tuple[bool, str]:
    """저장 전 키 검증 — 잔고 조회 1회. (성공여부, 메시지)."""
    c = None
    try:
        c = HTTP(testnet=False, demo=demo, timeout=5, max_retries=1, retry_delay=1,
                 api_key=api_key, api_secret=api_secret)
        eq = get_equity(c)
        return True, f"연결 성공 — 현재 자산 ${eq:,.2f}"
    except Exception as e:
        return False, f"연결 실패: {friendly_error(e)}"
    finally:
        try:
            if c is not None:
                c.client.close()
        except Exception:
            pass
