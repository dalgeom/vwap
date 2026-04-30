# TASK-INFRA-S01-DATA — S-01 ESC 정밀검증용 15m 데이터 페치

**상태**: CLOSED (2026-04-30)  
**발행**: 의장 (2026-04-30)  
**담당**: Dev-Infra(박소연)  
**블로킹**: TASK-BT-S01 ESC-S01 정밀 검증

---

## 요청 배경

ESC-S01 선행 검증(상한선) 결과 합산 N=69 → 조건부 PASS.  
15m 조건 C(pullback 타이밍) 포함 정밀 검증을 위해 15m 캐시가 필요하나 현재 전무.

---

## 요청 사항

### 1. 15m 봉 캐시 페치

**기존 6심볼** (1H 캐시 보유):
- BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, AVAXUSDT, LINKUSDT

**추가 4심볼** (아래 기준으로 선정):
- 거래량 10M USDT/일 이상, 상장 90일 이상
- 기존 6심볼과 상관관계 낮은 섹터 우선 (예: OPUSDT, ARBUSDT, DOTUSDT, NEARUSDT)

**기간**: 2022-07-01 ~ 2025-12-31  
**파일 형식**: `{SYMBOL}_15m.csv`  
**저장 경로**: `vwap_trader/data/cache/`  
**컬럼**: `timestamp, open, high, low, close, volume`

### 2. 추가 4심볼 1H 캐시

동일 심볼의 1H 캐시도 함께 페치 (ESC 검증 + WF BT 모두 필요).

---

## 완료 조건

- 10심볼 × 15m 캐시 파일 생성 확인
- 10심볼 × 1H 캐시 파일 생성 확인 (추가 4심볼)
- 완료 보고 시 Dev-Backtest(정민호)에게 ESC-S01 정밀 재실행 요청

---

## 우선순위

**HIGH** — TASK-BT-S01 전체 블로킹 중
