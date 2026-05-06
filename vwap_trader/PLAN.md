# VWAP Trader — Simple Is Best 전략 계획서

> 최종 업데이트: 2026-05-06

---

## 1. 프로젝트 목표

Bybit 선물 데모 계좌에서 **EMA9/EMA21 + VWAP 필터** 전략을 자동으로 운영하여 실전 전환 가능성을 검증한다.

- **현재 단계**: 데모 계좌 실시간 운영 (실전 미전환)
- **최종 목표**: 데모 검증 통과 후 실계좌 전환, 지속적 수익 창출

---

## 2. 왜 리셋했는가 — Bootstrap Round 실패 기록

2026년 초부터 약 3개월간 **Agent 9개 + 설계 문서 80+개** 구조로 복잡한 전략 탐색을 진행했다.

### 탐색 결과 (Cat.1 ~ Cat.27)

| 구분 | 결과 |
|------|------|
| 탐색한 전략 수 | 27개 카테고리 (100+ 변형) |
| ESC Gate 통과 | 0개 |
| 주요 실패 원인 | 신호 빈도 부족 (< 0.5회/일), OOS/IS 과적합 (WF비율 0.099) |

### 결론

- 다중 조건 → 신호 희소화 → 통계 부족
- Agent 복잡도가 전략 품질을 높이지 않음
- 단순한 전략을 제대로 운영하는 것이 우선

**결정: 전면 리셋. 복잡도 제거. Simple Is Best.**

---

## 3. 현재 전략 스펙 — EMA Cross + VWAP

### 3.1 진입 조건

| 항목 | 롱 | 숏 |
|------|----|----|
| EMA 조건 | EMA9이 EMA21을 **위로 크로스** | EMA9이 EMA21을 **아래로 크로스** |
| VWAP 필터 | 종가 **> VWAP** | 종가 **< VWAP** |
| 타임프레임 | 1H 캔들 | 1H 캔들 |
| 대상 심볼 | BTCUSDT, ETHUSDT, SOLUSDT | 동일 |

- VWAP: 최근 24봉 Rolling VWAP (추세 방향 필터)
- 크로스오버 감지: 이전 봉 EMA9 ≤ EMA21, 현재 봉 EMA9 > EMA21 (단순 레벨 비교 아님)

### 3.2 SL / TP 계산

```
롱 진입:
  SL = 진입 캔들 Low
  TP = 진입가 + (진입가 - SL) × 2   (1:2 손익비)

숏 진입:
  SL = 진입 캔들 High
  TP = 진입가 - (SL - 진입가) × 2   (1:2 손익비)
```

### 3.3 청산 우선순위

1. **SL 히트** — Bybit에 설정된 Stop Loss 자동 발동
2. **TP 히트** — Bybit에 설정된 Take Profit 자동 발동
3. **EMA 역크로스** — EMA9/21이 반대 방향으로 교차 시 즉시 시장가 청산
4. **48h 타임아웃** — 최대 보유 시간 초과 시 강제 청산

> **이유**: EMA 역크로스 청산이 없으면 횡보 구간에서 자본이 3일씩 묶이는 문제 발생.

### 3.4 포지션 관리

| 항목 | 값 |
|------|----|
| 동시 최대 포지션 | **1개** |
| 거래당 리스크 | 잔고의 **2%** |
| 레버리지 설정 | **5x** |
| 손익비 | **1:2** |
| 롱/숏 | **둘 다** |
| 운영 시간 | **24시간** |

> 동시 1포지션인 이유: BTC/ETH/SOL 상관관계 0.85~0.92. 동시 진입은 분산이 아니라 리스크 집중.

---

## 4. 프로젝트 구조

```
vwap_trader/
├── src/vwap_trader/
│   ├── main.py                  # 메인 루프 — 1H 캔들 폴링, 진입/청산 오케스트레이션
│   ├── models.py                # Candle, Position 등 공통 데이터 모델
│   ├── notifier.py              # Discord 웹훅 알림 (DISCORD_WEBHOOK_URL)
│   ├── strategy/
│   │   └── ema_vwap.py          # EMA9/21 + VWAP 신호 계산 (check_entry, check_exit)
│   ├── core/
│   │   ├── position_sizer.py    # 리스크 기반 수량 계산
│   │   └── risk_manager.py      # 일간 손실 한도 추적 (현재 미사용, 향후 활용)
│   └── infra/
│       ├── bybit_client.py      # Bybit V5 API 래퍼 (demo=True)
│       ├── data_pipeline.py     # 캔들 데이터 조회
│       └── order_executor.py    # 주문 실행 (현재 미사용, bybit_client 직접 호출)
├── config/
│   └── .env                     # API 키, Discord 웹훅 URL
├── data/
│   └── state.json               # 현재 오픈 포지션 상태 (재시작 시 복원)
└── logs/
    ├── bot.log                  # 운영 로그 (5MB 롤링)
    └── crash_reason.log         # 비정상 종료 시 트레이스백
```

---

## 5. 환경 설정

### config/.env

```env
BYBIT_API_KEY=your_api_key
BYBIT_API_SECRET=your_api_secret
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
DRY_RUN=false
```

- `DRY_RUN=true`: 실제 주문 없이 로그만 출력 (기본값)
- `DRY_RUN=false`: 실제 Bybit 데모 계좌에 주문

### 실전 전환 시

[`bybit_client.py:45`](src/vwap_trader/infra/bybit_client.py) 에서 `demo=True` → `demo=False` 변경

---

## 6. 봇 실행

```bash
cd vwap_trader
python -m vwap_trader.main
```

또는 가상환경 사용 시:
```bash
.\venv\Scripts\activate
python -m vwap_trader.main
```

---

## 7. 알림 (Discord)

Discord 웹훅 URL을 `.env`에 설정하면 아래 이벤트 시 알림 발송:

- 봇 시작 / 종료
- 포지션 진입 (심볼, 방향, 수량, 진입가, SL)
- 포지션 청산 (청산 사유, 수익률)
- 에러 발생

---

## 8. 향후 검토 사항

아래 항목은 현재 스펙에서 제외했으나, 데모 운영 결과에 따라 추가 검토:

| 항목 | 현재 | 검토 조건 |
|------|------|-----------|
| 간단한 백테스트 | 없음 | 데모 1개월 후 신호 빈도 분석 |
| 일간 손실 한도 | 미적용 | 연속 손실 3회 이상 발생 시 |
| 심볼 확대 | BTC/ETH/SOL | 3개월 이상 검증 후 |
| 실전 전환 | demo=True | 데모 30+ 트레이드, 승률 > 50%, EV > 0 |

---

## 9. 핵심 결정 이력

| 날짜 | 결정 |
|------|------|
| 2026-05-06 | Bootstrap Round 종료 — 27개 전략 탐색 모두 실패 |
| 2026-05-06 | 전면 리셋 — 설계 문서·에이전트·백테스트 스크립트 전체 삭제 |
| 2026-05-06 | Simple Is Best 채택 — EMA9/21 + VWAP, 1H, BTC/ETH/SOL |
| 2026-05-06 | 동시 포지션 3 → 1 변경 — 상관관계 0.85+ 리스크 집중 방지 |
| 2026-05-06 | EMA 역크로스 청산 추가 — 횡보 구간 자본 묶임 방지 |
