# TICKET-BT-001 — Phase 1 Regime Grid Search 백테스트 실행

| 항목 | 내용 |
|---|---|
| **발행자** | Dev-PM (한재원) |
| **수신자** | Dev-Backtest (정민호) |
| **발행일** | 2026-04-20 |
| **우선순위** | 🔴 P0 (블로커 — 이후 모든 단계 대기 중) |
| **근거 명세** | PLAN.md 부록 L (백테스트 설계 명세), 특히 L.1 ~ L.4, L.7 |
| **예상 소요** | 데이터 수집 4~8시간 + Grid Search 실행 2~4시간 |

---

## 0. 배경

코드 뼈대는 완성 상태이나 **백테스트 결과가 전무**. Chapter 10 (DRY_RUN 전환)과 Chapter 12 (실패 시나리오 검증)의 진입 관문.

Agent F 판결: "백테스트 결과 나오기 전 실전 전환 승인 금지" — 본 티켓 완료 전에는 어떤 키 발급/DRY_RUN 전환도 없음.

## 1. 범위

### 1.1 본 티켓 범위 (IN)

- **Phase 1**: Regime Detection 파라미터 Grid Search (**60 조합**) — PLAN.md L.3
- 데이터 수집: **2023-01-01 ~ 2026-03-31 UTC (39개월, 결정 #16)**
- 메인 제외 구간: 없음 (LUNA/FTX 는 본 기간 밖). Stress test 는 별도 티켓
- 심볼 유니버스: 부록 K 기준 상위 유동성 심볼(최소 BTCUSDT, ETHUSDT부터 시작)
- 결과 산출: 각 조합별 PF, MDD, Win Rate, EV, 거래 수 → JSON + CSV 리포트

### 1.2 본 티켓 범위 (OUT)

- Phase 2A (Module A Grid 60) — 별도 **TICKET-BT-002** (Phase 1 완료 후 발행)
- Phase 2B (Module B Grid 80) — 별도 **TICKET-BT-003**
- Walk-Forward 검증 (L.5) — Phase 1~2 완료 후 **TICKET-BT-004**
- Regime별 분리 검증 (L.6) — **TICKET-BT-005**
- Stress test (LUNA/FTX) — **TICKET-BT-006**

## 2. 선행 작업 (Dev-Infra 박소연에게 요청)

### 2.1 BybitClient 확장

현재 [bybit_client.py:105](vwap_trader/src/vwap_trader/infra/bybit_client.py#L105) `get_candles(symbol, interval, limit)` 는 **start/end 미지원** — 과거 데이터 페이지네이션 불가.

**요청 명세**:
```python
def get_candles_range(
    self, symbol: str, interval: str,
    start_ms: int, end_ms: int,
) -> list[Candle]:
    """
    pybit HTTP.get_kline 의 start/end 파라미터 활용.
    limit=1000 단위로 페이지네이션, rate limit 준수 (50ms sleep).
    캔들은 시간 오름차순 보장.
    """
```

**담당**: Dev-Infra 박소연  
**DoD**: 단위 테스트 포함 (빈 구간, 경계 타임스탬프, 페이지 경계 1개 캔들)

### 2.2 스크립트 배치

- [vwap_trader/scripts/fetch_historical.py](vwap_trader/scripts/fetch_historical.py) — 이미 첨부 (본 티켓과 함께 생성)
- [vwap_trader/scripts/run_backtest_phase1.py](vwap_trader/scripts/run_backtest_phase1.py) — 이미 첨부

두 스크립트는 **선행 작업 2.1 완료 전까지 실행 불가**. 코드 골격은 완성 상태.

## 3. 작업 순서

1. **2.1 완료 대기** (Dev-Infra)
2. `python -m vwap_trader.scripts.fetch_historical --symbols BTCUSDT,ETHUSDT --start 2022-01-01 --end 2024-12-31` 실행 → `vwap_trader/data/cache/` 에 CSV 저장
3. LUNA/FTX 제외 구간을 별도 파일로 분리 저장 (stress test 재활용용)
4. `python -m vwap_trader.scripts.run_backtest_phase1` 실행 → 60 조합 Grid Search
5. 결과: `vwap_trader/data/backtest_results/phase1_YYYYMMDD.json` 생성
6. 스코어 상위 5개 조합을 Dev-PM에게 보고

## 4. 완료 기준 (DoD)

- [ ] 데이터 캐시 파일이 `data/cache/` 에 심볼별 1H, 4H 각 1개씩 존재
- [ ] LUNA/FTX 제외 검증 (캐시 데이터에 해당 기간 타임스탬프 부재)
- [ ] 60개 조합 전부 실행 완료 (중단된 조합 0개)
- [ ] JSON 리포트에 각 조합별 PF, MDD, Win Rate, Trade Count 존재
- [ ] Agent F 스코어 함수 (`pf * (1/max(mdd,0.05)) * win_rate`, L.4) 적용된 랭킹 CSV 존재
- [ ] 자동 탈락 조건 (`pf<1.0` or `mdd>0.20`) 적용된 필터링 결과 존재
- [ ] 룩어헤드 바이어스 체크: `BacktestEngine.check_lookahead_bias()` 호출 후 `violations == []` 확인
- [ ] Dev-PM 직접 검토: 스코어 상위 3개 조합의 pseudocode 대조 일치 확인

## 5. 리스크 / 블로커

| 리스크 | 완화책 |
|---|---|
| Bybit API rate limit (120 req/min) | 페이지 간 50ms sleep, 심볼 1개씩 순차 수집 |
| 수집 중 네트워크 단절 | 재시작 시 마지막 타임스탬프부터 이어받기 (스크립트 내 구현) |
| PLAN.md L.1 은 CCXT 지정, 현재 구현은 pybit | **기획팀 확인 필요** → L-REQ-2026-04-20 #5 질의 예정 |
| 엔진 비용 모델이 L.2 tier_1/tier_2 미반영 | 본 Phase 1 은 Regime 파라미터만 변경 → 허용. Phase 2 전 **TICKET-BT-007** 로 별도 처리 |

## 6. 연관 태스크

- 완료 후 → **TICKET-BT-002** (Phase 2A, Module A Grid) 발행
- 동시에 → **TICKET-QA-001** (단위 테스트 Batch 1) 진행 중 (병렬)
- 결과 수령 후 → **TICKET-PM-002** (결과 검토 및 Phase 2 승인)
