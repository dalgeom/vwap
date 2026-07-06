# A-4 일일 리포트 설계 — daily_report.py

> 작성: 2026-07-06 | 근거: PROJECT_ANALYSIS_ROADMAP.md §6-A(A-4) / 목적2("매일 성장")
> 성격: **인프라(거래로직 무변경)** — 봇 수익·승률에 영향 0, v10 검증과 병행 안전.
> 목적: 매 세션 수동으로 하던 "현상황 브리핑"을 자동화. 매일 1회 봇이 알아서 성적표를 `reports/YYYY-MM-DD.md`로 남긴다.
> 선행: A-2(`fix_estimated.py`)·A-3·`corrections.py`(`apply_corrections`)는 완료됨. A-4는 그 위에 얹는다.

---

## 1. 실행 — 하나의 매일 배치

`daily_report.py`(repo 루트 `vwap_trader/`). 실행: `PYTHONIOENCODING=utf-8 python daily_report.py`.

`main()` 흐름:
1. **`fix_estimated.run()` 호출** — estimated를 거래소 실값으로 먼저 정정(corrections append). 리포트 누적이 정확해지도록 선행.
2. **trades 로드 + `apply_corrections`** — 원본 trades에 corrections 오버레이(정확한 최근 손익).
3. **`state` 로드** — bar_counter, daily_pnl, daily_trades, slippage_cooldown, last_save.
4. **거래소 조회**(`fix_estimated._build_client` 재사용) — 잔고 totalEquity, 보유 포지션 실시간 미실현.
5. **집계 → `reports/YYYY-MM-DD.md` 저장 + 콘솔 출력.**

스케줄러(윈도 작업 스케줄러)엔 `daily_report.py` 하나만 매일 1회 등록(fix_estimated를 내부 포함하므로 별도 등록 불필요). 봇 정각 scan 회피 위해 매시 30분 권장.

---

## 2. ★ 핵심 원칙 — "equity가 진짜 누적, trades는 통계"

- **자산 지표 = 거래소 `totalEquity`**: 실현+미실현 총합이라 절대 정확. 리포트 헤더의 대표 숫자.
- **거래 통계(승률·EV·PF·당일손익) = raw trades ⊕ corrections**: 최근분은 정확. 단 과거분 PnL 버그 오염(§5.7, prom §7)은 알려진 한계 → 통계 옆에 **각주 "정밀 누적은 rebuild_pnl 정본 기준"** 표기.
- 전체 정본을 매일 `rebuild_pnl.py`로 재구축하지 않는다(무겁고 corrected 덮어쓰기 위험 — A-1의 몫이며 이 작업 범위 밖).

---

## 3. 리포트 섹션 (Markdown)

1. **헤더**: 날짜 · equity(거래소) · bar_counter · 봇 생존(heartbeat가 N분 이내면 정상, 아니면 ⚠️).
2. **보유 포지션**: 심볼 · 방향 · 진입가 · 현재가(mark) · **실시간 미실현**(거래소) · 손절선. 무포지션이면 "없음".
3. **당일 청산**: 오늘(리포트 날짜, UTC 자정 경계) 청산된 trades — 심볼 · 방향 · exit_reason · 손익. 합계.
4. **성적 요약**: 전체 trades 및 v10 구간(`bot_version=="v10"`) 각각 건수 · 승률 · EV · PF · 누적. + top winner 몇 건 · 손절 수.
5. **shadow(거른 신호)**: 당일 shadow reason 분포(counter_trend/rank_cutoff/low_vol_coin 등 카운트).
6. **인프라 상태**: estimated 잔존 수 · 7일 시한임박 수 · slippage_cooldown 활성 코인 · corrections 누적 수.
7. **경고**: heartbeat 정체(예: >10분) 시 ⚠️ / estimated 시한임박(≤2일) 시 ⚠️.

---

## 4. 코드 구조 (테스트 가능)

**순수함수**(거래소·파일 I/O 없음, 단위테스트 대상):
- `build_stats(trades: list) -> dict`: 건수·승률·EV·PF·누적을 전체 및 버전별로. corrections는 호출 전 `apply_corrections`로 이미 반영된 리스트를 받는다.
- `todays_closes(trades: list, day: date) -> list`: `exit_timestamp_utc`가 그 날(UTC)인 trade만.
- `shadow_reason_counts(shadow: list, day: date) -> dict`: 당일 shadow reason 카운트.
- `render_report(ctx: dict) -> str`: 위 집계 + 포지션/equity/경고를 Markdown 문자열로.

**I/O 얇게**(`main()`):
- 정정 호출, 파일 로드, 거래소 조회, `render_report` 결과를 `reports/YYYY-MM-DD.md`에 쓰기 + print. 거래소 조회 실패 시 미실현 부분만 "조회 실패"로 degrade하고 리포트는 계속 생성.

---

## 5. 데이터 소스

| 값 | 소스 |
|----|------|
| equity, 보유 미실현 | 거래소 `get_wallet_balance`/`get_positions` |
| 당일 청산·통계 | `trades_momentum.jsonl` ⊕ `pnl_corrections.jsonl` |
| bar·daily·slippage_cooldown | `state_momentum.json` |
| 봇 생존 | `heartbeat_momentum` mtime/내용 |
| shadow 분포 | `shadow_momentum.jsonl` |
| estimated 잔존 | trades에서 `pnl_source=="estimated"` 및 corrections 미포함 |

---

## 6. 테스트

- `build_stats`: 승/패 섞인 mock trades → 승률·EV·PF·버전별 분리 정확.
- `todays_closes`: UTC 날짜 경계 필터(어제/오늘/내일 섞어 오늘만).
- `shadow_reason_counts`: reason 카운트.
- `render_report`: 핵심 필드(equity·포지션·경고)가 출력 문자열에 포함. 무포지션·경고 케이스.
- 거래소 조회·파일 쓰기는 `main()`에 격리, 단위테스트 대상 아님(실행 검증은 1회 라이브).

---

## 7. 범위 밖 (YAGNI / 스코프 경계)

- **A-5(watchdog 알림)**: 이번 작업 아님. heartbeat 정체를 리포트에 ⚠️로 표기만 하고, 별도 알림 채널(텔레그램/윈도)은 만들지 않는다.
- **A-1 정본 자동병합 완전판**·매일 rebuild_pnl 재구축: 안 함. equity + trades⊕corrections로 충분.
- **JSON 출력·과거 리포트 비교·차트**: 안 함(Markdown 단일).
- 거래로직(사이징·게이트·정원 등): 일절 안 건드림(v10 검증 보호).
