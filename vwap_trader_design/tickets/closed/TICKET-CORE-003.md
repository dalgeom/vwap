# TICKET-CORE-003 — 긴급정지 + 알림 시스템 구현

**발행일**: 2026-04-27  
**발행자**: 의장 (Dev-QA 결과 기반)  
**담당**: Dev-Core (이승준)  
**우선순위**: 블로커 — 항목 3 PASS 전까지 Testnet 실거래 진행 불가 (결정 #43)  
**상태**: OPEN

---

## 배경

TASK-QA-CHECKLIST 결과, PLAN.md §M.4/M.5 명세 대비 아래 기능이 미구현.  
서킷브레이커(FULL_HALT)는 신규 진입 차단만 하고, 오픈 포지션 강제 청산 및 외부 알림이 없음.

---

## 구현 필수 항목 (4개)

### 1. `emergency_stop(reason: str, catastrophic: bool = False)`
- 위치: `vwap_trader/src/vwap_trader/main.py` 또는 별도 `emergency.py`
- 호출 순서 (PLAN.md §M.5):
  1. `block_new_entries()` — 이미 구현된 FULL_HALT로 대체 가능
  2. `close_all_positions_market_order()`
  3. `send_critical_alert(reason)`
  4. `log_emergency_event(reason)`

### 2. `close_all_positions_market_order()`
- 위치: `OrderExecutor` 또는 `MainLoop`
- 동작: 현재 오픈 포지션 전량 시장가 청산 명령
- 응답 시간 목표: 트리거 후 < 5초 (결정 #43 F 판결)
- Bybit API: `cancel_all_orders()` + `close_position()` 순서

### 3. `send_critical_alert(reason: str)`
- 위치: 별도 `notifier.py` 권장
- 채널: Telegram (1순위) 또는 Slack (대안)
- 환경변수: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (.env 추가)
- AlertLevel: INFO / WARNING / CRITICAL (PLAN.md §M.4 명세 준수)
- CRITICAL 이하 레벨은 로컬 로그 유지 허용, CRITICAL은 외부 발송 필수

### 4. FULL_HALT → `emergency_stop()` 자동 호출 연결
- 트리거 위치: `risk_manager._update_state()` 또는 `main.py run()` 루프
- 조건: state가 FULL_HALT로 전환되는 순간 1회 호출
- 중복 호출 방지 플래그 필요 (`_emergency_triggered: bool`)

---

## 구현 제약

- 기존 서킷브레이커 로직(`risk_manager.py`) 수정 최소화
- `TEST_FORCE_ENTRY`, `DRY_RUN` 플래그 하에서도 동작해야 함
  (단, DRY_RUN=true 시 실제 청산 주문 대신 로그만 출력 허용)
- 외부 알림 미설정(토큰 없음) 시 graceful fallback — 예외 발생 금지

---

## 완료 기준

Dev-QA 재검증에서 아래 조건 모두 충족:
- [ ] `emergency_stop()` 트리거 → 포지션 청산 명령까지 < 5초
- [ ] CRITICAL 알림 외부 채널 발송 확인
- [ ] FULL_HALT 시 자동 호출 경로 코드 리뷰 통과
- [ ] DRY_RUN 모드에서 실주문 없이 정상 동작

---

## 참조

- PLAN.md §M.4 (알림 시스템), §M.5 (긴급정지 프로토콜)
- `vwap_trader/src/vwap_trader/main.py` (run loop: line 153-158, FULL_HALT: line 281-282)
- `vwap_trader/src/vwap_trader/core/risk_manager.py` (_update_state, on_trade_closed)
- 결정 #43 F 판결 (긴급정지 응답 시간 < 5초 기준)
