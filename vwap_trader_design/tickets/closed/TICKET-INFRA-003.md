# TICKET-INFRA-003 — DRY_RUN 라운드트립 카운터 구현

| 항목 | 내용 |
|---|---|
| **발행자** | Dev-PM (한재원) |
| **수신자** | Dev-Infra (박소연) |
| **발행일** | 2026-04-20 |
| **우선순위** | 🟡 P1 (DRY_RUN 단계 전 필수) |
| **근거 명세** | 회의 #15 판결 2-1 ~ 2-3 |

## 문제

Chapter 10 "DRY_RUN 100건" 의 "건" 이 **라운드트립 완료 건수 (Module A/B 각 100건)** 로 회의 #15 에서 확정됨. 그러나 현재 코드에는 카운터 부재.

## 작업

1. `core/risk_manager.py` 에 `RoundtripCounter` dataclass 신설 — 모듈별 3개 카운터:
   - `completed`: SL/TP/트레일링 정상 청산
   - `timeout_exits`: max_hold 강제 청산
   - `blocked_entries`: RiskManager.can_enter() 가 False 반환한 횟수
2. `RiskManager` 에 `counter: RoundtripCounter = field(default_factory=RoundtripCounter)` 추가.
3. `can_enter()` 에서 False 리턴 직전 `counter.record_block(module, reason)` 호출.
4. `main.py` 의 포지션 종료 지점(3곳: TP1 partial 제외, max_hold, trailing, 루프 종료)에서 `counter.record_close(module, reason)` 호출.
5. 매 tick 마다 카운터 상태 INFO 로깅 (Module A/B 각 3개 값).
6. `RoundtripCounter.is_dry_run_complete()` helper — Module A + B 각 100건 달성 여부 bool 반환.

## DoD

- [ ] `RoundtripCounter` 구현 + 3개 record 메서드
- [ ] main.py 훅업 완료
- [ ] 리셋 정책: `reset_daily()` 와 **독립** (라운드트립 카운터는 누적)
- [ ] 단위 테스트: 100건 경계값, A/B 독립 카운트 검증
