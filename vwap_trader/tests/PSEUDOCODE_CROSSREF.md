# Pseudocode ↔ Code Cross-Reference

> 마지막 업데이트: 2026-04-20
> 담당: Dev-Backtest (정민호)

---

## 부록 F.4.2 — structural_anchor (SL 구조 기준점)

### Pseudocode (PLAN.md 부록 F.3)

| 모듈 | 방향 | structural_anchor |
|---|---|---|
| Module A 롱 | long | `deviation_candle.low` |
| Module A 숏 | short | `deviation_candle.high` |
| Module B 롱 | long | `pullback_candle.low` |
| Module B 숏 | short | `bounce_candle.high` |

### 구현 매핑

#### `backtest/engine.py` — `_build_position_a()`

| Pseudocode | 코드 | 파일:라인 |
|---|---|---|
| `structural_anchor = deviation_candle.low` (long) | `decision.evidence.get("deviation_low", bar.low)` | engine.py:445 |
| `structural_anchor = deviation_candle.high` (short) | `decision.evidence.get("deviation_high", bar.high)` | engine.py:447 |

#### `backtest/engine.py` — `_build_position_b()`

| Pseudocode | 코드 | 파일:라인 |
|---|---|---|
| `structural_anchor = pullback_candle.low` (long) | `decision.evidence.get("pullback_low", ...)` | engine.py:501 |
| `structural_anchor = bounce_candle.high` (short) | `decision.evidence.get("bounce_high", ...)` | engine.py:503 |

#### `main.py` — `_handle_entry()`

| Pseudocode | 코드 | 파일:라인 |
|---|---|---|
| `structural_anchor = deviation_candle.low` (long) | `decision.evidence.get("deviation_low", bar.low)` | main.py:371 |
| `structural_anchor = deviation_candle.high` (short) | `decision.evidence.get("deviation_high", bar.high)` | main.py:373 |
| `structural_anchor = pullback_candle.low` (long) | `decision.evidence.get("pullback_low", ...)` | main.py:378 |
| `structural_anchor = bounce_candle.high` (short) | `decision.evidence.get("bounce_high", ...)` | main.py:380 |

### evidence 공급처

| 키 | 공급 모듈 | 파일:라인 |
|---|---|---|
| `deviation_low` | `check_module_a_long()` | module_a.py:205 |
| `deviation_high` | `check_module_a_short()` | module_a.py:272 |
| `pullback_low` | `check_module_b_long()` | module_b.py:95 |
| `bounce_high` | `check_module_b_short()` | module_b.py:169 |

### 수정 이력

| 날짜 | 변경 내용 | 티켓 |
|---|---|---|
| 2026-04-20 | `bar.low/high` 프록시 → `deviation_candle/pullback_candle` 실제 값으로 수정 | BT-2026-001 / IF-2026-001 |
| 2026-04-21 | Long 이탈 트리거 재설계 (std+low → ATR(14)+close). evidence 에 `deviation_close`, `close_used`, `atr_14`, `deviation_threshold` 추가. `deviation_low` 는 SL structural_anchor 소비자 호환 유지. 공급 라인 196 → 205. | BUG-CORE-002 / DOC-PATCH-005 |

---

## 부록 F.2 — `compute_sl_distance()`

| Pseudocode | 코드 | 파일:라인 |
|---|---|---|
| `raw_sl = structural_anchor - ATR_BUFFER * atr_1h` | 동일 | sl_tp.py:55 |
| `raw_sl = structural_anchor + ATR_BUFFER * atr_1h` (short) | 동일 | sl_tp.py:57 |
| `min_sl_distance = entry_price * MIN_SL_PCT` | 동일 | sl_tp.py:59 |
| `ATR_BUFFER = 0.3` | 동일 | sl_tp.py:13 |
| `MIN_SL_PCT = 0.015` | 동일 | sl_tp.py:14 |