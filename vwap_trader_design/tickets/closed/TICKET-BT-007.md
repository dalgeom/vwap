# TICKET-BT-007 — 엔진 COST_MODEL tier_1/tier_2 구조 교체

| 항목 | 내용 |
|---|---|
| **발행자** | Dev-PM (한재원) |
| **수신자** | Dev-Backtest (정민호) |
| **발행일** | 2026-04-20 |
| **우선순위** | 🟡 P1 (Phase 2 실행 전 필수, Phase 1 은 flat 허용) |
| **근거 명세** | PLAN.md 부록 L.2 + 부록 K.1 (tier 분류, 회의 #15 신설) |

## 문제

[backtest/engine.py:40~42](../../vwap_trader/src/vwap_trader/backtest/engine.py#L40) `COST_MODEL` 이 flat 구조:

```python
COST_MODEL = {
    "module_a": {"fee_per_side": 0.0003, "slippage_per_side": 0.0002},
    "module_b": {"fee_per_side": 0.0006, "slippage_per_side": 0.0002},
}
```

부록 L.2 는 `tier_1 / tier_2 × module_a / module_b` 2×2 매트릭스 요구.

## 작업

1. `COST_MODEL` 을 2-레벨 dict 로 재편성: `COST_MODEL[tier][module]`.
2. `_round_trip_cost(entry, module, tier)` / `_pnl_pct(entry, exit, direction, module, tier)` 로 tier 파라미터 추가.
3. `_OpenPosition` dataclass 에 `tier: str = "tier_1"` 필드 추가.
4. `BacktestEngine.__init__` 에 `symbol_tiers: dict[str, str]` 옵션 지원. 미지정 시 `tier_1` 기본.
5. `universe/symbol_universe.py` 의 `classify_tier()` 를 import 해서 사용.

## DoD

- [ ] COST_MODEL tier 구조 교체
- [ ] 기존 호출부 signature 업데이트 완료 (engine.py 전역)
- [ ] Phase 1 회귀: 기존 테스트 통과 (tier_1 기본값으로 결과 동일해야 함)
- [ ] 단위 테스트: tier_2 에서 slippage 가 더 크게 반영되는지 검증
