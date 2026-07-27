"""읽기 전용 거래소 조회 — 주문 계열 메서드는 이 모듈에 절대 추가하지 않는다.
호출 시점 주의: 봇이 정각(분=0)에 스캔하므로 스케줄러/폴링은 정각을 피해 호출."""
from pathlib import Path

from pybit.unified_trading import HTTP

from app.settings import read_env_keys, read_demo_flag


def build_private_client(project_root: Path) -> HTTP:
    keys = read_env_keys(project_root / "config" / ".env")
    demo = read_demo_flag(project_root / "config" / "momentum_config.yaml")
    return HTTP(testnet=False, demo=demo,
                api_key=keys["BYBIT_API_KEY"], api_secret=keys["BYBIT_API_SECRET"])


def get_equity(client: HTTP) -> float:
    w = client.get_wallet_balance(accountType="UNIFIED")["result"]["list"][0]
    return float(w["totalEquity"])


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


def validate_keys(api_key: str, api_secret: str, demo: bool) -> tuple[bool, str]:
    """저장 전 키 검증 — 잔고 조회 1회. (성공여부, 메시지)."""
    try:
        c = HTTP(testnet=False, demo=demo, api_key=api_key, api_secret=api_secret)
        eq = get_equity(c)
        return True, f"연결 성공 — 현재 자산 ${eq:,.2f}"
    except Exception as e:
        return False, f"연결 실패: {e}"
