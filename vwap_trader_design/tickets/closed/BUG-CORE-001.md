# BUG-CORE-001 — va_slope 하드코딩 제거 및 계산 구현

| 항목 | 내용 |
|---|---|
| **발행자** | Dev-PM (한재원) |
| **수신자** | Dev-Core (이승준) |
| **발행일** | 2026-04-20 |
| **우선순위** | 🔴 P0 (Phase 1 백테스트 유일 잔존 블로커) |
| **근거 명세** | PLAN.md 부록 H-1.2 (회의 #15 신설) |

## 문제

현재 `va_slope=0.0` 하드코딩 2개소:

1. [main.py:296](../../vwap_trader/src/vwap_trader/main.py#L296) — 실전 루프
2. [backtest/engine.py:267](../../vwap_trader/src/vwap_trader/backtest/engine.py#L267) — 백테스트 엔진

부록 A `va_slope_threshold = 0.005` 임계와 무관하게 Regime 판정 동작 → Accumulation 오판 가능.

## 작업

1. `core/volume_profile.py` 에 `compute_va_slope(candles_1h, *, window_hours=168) -> float` 추가 (부록 H-1.2 pseudocode 1:1).
2. `main.py` 와 `engine.py` 에서 `compute_va_slope` import 후 실제 계산값 전달.
3. 데이터 부족 시 (`len < 2 * window_hours`) 0.0 반환 — 부록 B-0 엣지 1 준용.

## DoD

- [ ] `compute_va_slope` 구현 + 부록 H-1.2 대응 docstring
- [ ] main.py/engine.py 에서 하드코딩 제거 완료
- [ ] `tests/test_volume_profile.py` 에 합성 데이터 기반 단위 테스트 1개 이상 (상승/하락/평탄)
- [ ] Dev-PM 직접 검토 (부록 H-1.2 pseudocode 대조)
