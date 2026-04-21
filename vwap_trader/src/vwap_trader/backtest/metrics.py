"""
백테스트 성과 지표 계산 및 Chapter 0.3 성공 기준 판정.
Dev-Backtest(정민호) 구현
"""
from __future__ import annotations

import math
from vwap_trader.models import BacktestResult


def max_drawdown(result: BacktestResult) -> float:
    """
    누적 수익률 기준 MDD 계산.
    반환: 0~1 (예: 0.15 = 15%)
    """
    if not result.trades:
        return 0.0
    cumulative = 0.0
    peak = 0.0
    mdd = 0.0
    for t in result.trades:
        cumulative += t.pnl_pct
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > mdd:
            mdd = dd
    return mdd


def sharpe_ratio(result: BacktestResult, risk_free: float = 0.0) -> float:
    """
    거래 단위 Sharpe Ratio.
    risk_free: 거래당 무위험 수익률 (기본 0).
    """
    if len(result.trades) < 2:
        return 0.0
    pnls = [t.pnl_pct - risk_free for t in result.trades]
    mean = sum(pnls) / len(pnls)
    variance = sum((p - mean) ** 2 for p in pnls) / (len(pnls) - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0
    return mean / std if std > 0 else 0.0


def annual_return(result: BacktestResult) -> float:
    """
    연간화 수익률 추정.
    전체 기간 대비 누적 수익률을 365일로 환산.
    """
    if not result.trades:
        return 0.0
    total_pnl = sum(t.pnl_pct for t in result.trades)
    first_t = result.trades[0].entry_time
    last_t = result.trades[-1].exit_time
    days = (last_t - first_t).total_seconds() / 86400
    if days <= 0:
        return 0.0
    return total_pnl * (365 / days)


def avg_weekly_trades(result: BacktestResult) -> float:
    """주 평균 거래 횟수."""
    if not result.trades:
        return 0.0
    first_t = result.trades[0].entry_time
    last_t = result.trades[-1].exit_time
    weeks = (last_t - first_t).total_seconds() / (7 * 86400)
    return len(result.trades) / weeks if weeks > 0 else 0.0


def backtest_score(pf: float, mdd: float, win_rate: float) -> float:
    """
    Grid Search 최적화 기준 지표 (부록 L.4, Agent F 확정).
    pf: Profit Factor
    mdd: Maximum Drawdown (0~1)
    win_rate: 승률 (0~1)
    """
    if pf < 1.0 or mdd > 0.20:
        return -999.0
    return pf * (1.0 / max(mdd, 0.05)) * win_rate


def evaluate_success_criteria(result: BacktestResult) -> dict[str, bool]:
    """
    Chapter 0.3 성공 기준 자동 판정.
    모든 항목 True여야 통과.
    """
    mdd = max_drawdown(result)
    weekly = avg_weekly_trades(result)
    return {
        "win_rate_ok":        result.win_rate >= 0.55,
        "ev_ok":              result.ev_per_trade >= 0.0015,
        "tp1_reach_ok":       result.tp1_rate >= 0.30,
        "timeout_ok":         result.timeout_rate <= 0.20,
        "weekly_freq_ok":     weekly >= 5.0,
        "profit_factor_ok":   result.profit_factor >= 1.3,
        "mdd_ok":             mdd <= 0.15,
    }


def module_breakdown(result: BacktestResult) -> dict[str, dict]:
    """모듈별(A/B) 분리 성과 집계."""
    out: dict[str, dict] = {}
    for module in ("A", "B"):
        trades = [t for t in result.trades if t.module == module]
        if not trades:
            out[module] = {"total": 0}
            continue
        wins = [t for t in trades if t.pnl_pct > 0]
        losses = [t for t in trades if t.pnl_pct < 0]
        gain = sum(t.pnl_pct for t in wins)
        loss = abs(sum(t.pnl_pct for t in losses))
        sub = BacktestResult(trades=trades)
        out[module] = {
            "total": len(trades),
            "win_rate": len(wins) / len(trades),
            "ev": sum(t.pnl_pct for t in trades) / len(trades),
            "profit_factor": gain / loss if loss > 0 else float("inf"),
            "mdd": max_drawdown(sub),
        }
    return out
