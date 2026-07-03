# 데이터 안전 인프라 설계 — A-2 estimated 자동정정 + A-3 무결성 가드

> 작성: 2026-07-03 | 근거: PROJECT_ANALYSIS_ROADMAP.md §6-A / PLAN.md §5.9(무결성 사고 2회)·§8.7·§8.8
> 성격: **인프라(거래로직 무변경)** — 봇 수익·승률에 영향 0, v10 검증과 병행 안전.
> 목적: 이번 세션에 반복 겪은 두 고통을 자동화로 제거 —
> ① estimated 값 수동정정(06-29·07-02) + 거래소 7일 시한 초과로 24건 영구 유실
> ② 봇 켠 채 `trades_momentum.jsonl` IDE 저장 → 데이터 롤백 사고 2회(06-19, 06-22→29)

---

## 1. 제1원칙 (전체 구조의 뿌리)

**원본 `data/trades_momentum.jsonl`은 봇의 append 외 어떤 외부 수정도 하지 않는다.**

- 이번 세션 무결성 사고 2건의 근본 원인 = "봇이 켜진 채 원본을 외부에서 수정". 지금까지 estimated 정정을 Edit으로 원본에 직접 하던 방식이 바로 그 위험을 안고 있었다.
- 따라서 모든 정정은 별도 파일 `data/pnl_corrections.jsonl`에 **append만** 한다.
- 분석/브리핑은 `원본 ⊕ corrections`를 trade_id로 오버레이해 읽는다.

이 원칙 하나로 A-2가 스스로 사고를 유발할 가능성을 원천 차단한다.

---

## 2. A-2 — `fix_estimated.py` (외부 스크립트, 봇과 완전 분리)

### 목적
청산 직후 봇이 추정(estimated)으로 남긴 손익을, 거래소 정산 후 실값(exchange)으로 정정한다. 거래소 데모 API의 7일 보관 시한 안에 자동으로 처리해 영구 유실을 0으로.

### 동작
1. 원본 trades에서 `pnl_source == "estimated"` 이고 `exit_timestamp_utc`가 최근 7일 이내인 건 추출.
2. 이미 `pnl_corrections.jsonl`에 있는 trade_id는 skip (**멱등**).
3. 각 대상에 대해 거래소 `get_closed_pnl(symbol)` 풀 정밀도 조회 → `createdTime >= 진입시각` freshness 게이트(§8.8)로 옛 레코드 오매칭 방지 → trade_id/side/entry 근접으로 매칭.
4. 매칭되면 `pnl_corrections.jsonl`에 1줄 append:
   ```json
   {"trade_id": "4681aa45", "symbol": "TAIKOUSDT", "pnl_usd": 469.48228494,
    "exit_price": 0.15393, "pnl_pct": 46.9451, "src": "exchange",
    "fixed_at": "2026-07-03T...Z", "prev_estimated": 425.8282}
   ```
   (`pnl_pct`는 원본 entry_price와 거래소 avgExitPrice로 가격변화율 재계산. `prev_estimated`는 감사용 원값 보존.)
5. 종료 시 요약 출력: `정정 N건 / 시한임박(≤2일) M건 / 시한초과 유실 K건 / 매칭실패 J건`.

### 재사용·주의
- 매칭 로직은 봇 `_get_closed_pnl_record`(momentum_bot.py:663)와 동형. 가능하면 공통 함수로 추출하되, 최소 변경 원칙상 스크립트에 별도 구현해도 무방(단 freshness 게이트는 필수).
- 거래소 private 조회는 `config/.env` 키·`pybit HTTP(demo=True)`. 봇 정각(분=0) scan과 겹치지 않는 시각에 실행.
- **원본 trades는 절대 열어 쓰지 않는다**(읽기 전용). corrections만 append.

### 트리거 (운영)
- 스크립트 단독 실행 가능: `PYTHONIOENCODING=utf-8 python fix_estimated.py`.
- **윈도 작업 스케줄러 매일 1회 등록법을 README/문서에 기재**(봇 정각 피한 시각, 예: 매시 30분 아무 때). "상시 데몬"은 만들지 않는다(YAGNI).

---

## 3. A-3 — 무결성 가드 (`momentum_bot.py` 내장, 다음 재시작 발효)

### 목적
봇 켠 채 원본이 외부에서 수정/삭제되는 사고를 (1) 백업으로 복구 가능하게 하고 (2) 다음 시작 때 감지·경고한다.

### 동작
- **`run()` 시작부(`_load_state()` 직후)**:
  - `trades_momentum.jsonl` → `trades_momentum.jsonl.bak_YYYYMMDD_HHMMSS` 자동 백업.
  - 시작 시점 라인수를 인스턴스 변수에 기억(`self._trades_lines_at_start`).
  - (선택) 오래된 자동백업 정리: 최근 N개(예: 10개)만 유지해 무한 증식 방지.
- **`_log_trade` (momentum_bot.py:736)**: 봇이 append할 때 카운터(`self._trades_appended`) +1.
- **`run()` 종료부(`finally`, `_save_state()` 뒤)**:
  - 종료 시 실제 라인수를 다시 셈.
  - 기대값 = `_trades_lines_at_start + _trades_appended`.
  - 실제 ≠ 기대 → "⚠️ 외부 수정 감지: 시작 X + 봇append Y = 기대 Z, 실제 W" 경고 로그 + `notify()`.

### 범위 밖 (YAGNI)
- 가동 중 실시간 파일 mtime 감시 스레드: **넣지 않는다.** 시작 백업 + 종료 비교로 사고 감지·복구에 충분. 필요해지면 후속.

---

## 4. 분석 통합 — `apply_corrections` 최소 헬퍼

corrections를 실제로 쓰려면 병합이 필요하다. 완전 자동 정본병합(로드맵 A-1)은 **별도 항목**이며 이 작업 범위 밖. 여기서는 작은 함수 하나만 제공한다.

- `apply_corrections(trades: list[dict]) -> list[dict]`: 원본 trade 리스트에 `pnl_corrections.jsonl`을 trade_id로 오버레이(pnl_usd·exit_price·pnl_pct·pnl_source 교체). corrections 없으면 원본 그대로.
- 위치: 작은 공용 모듈(예: `corrections.py`)에 두고, `fix_estimated.py` 요약과 향후 브리핑/분석이 재사용. A-1은 나중에 이 함수를 감싼다.

---

## 5. 데이터 포맷 — `data/pnl_corrections.jsonl`

- JSONL, append-only, trade_id당 최대 1줄(멱등 보장은 A-2가 기존 trade_id skip으로).
- 필드: `trade_id, symbol, pnl_usd, exit_price, pnl_pct, src, fixed_at, prev_estimated`.
- git 추적 대상(데이터 자산). 봇은 이 파일을 쓰지 않는다(A-2 전용).

---

## 6. 테스트

- **A-2** (`test_fix_estimated`): mock 거래소 응답으로 ① estimated 건만 대상 ② 7일 필터 ③ freshness 게이트로 옛 레코드 배제 ④ corrections append 포맷 ⑤ 재실행 시 멱등(중복 append 0). 실거래 검증은 봇이 estimated 남긴 다음 청산 때.
- **A-3** (`test_integrity_guard`): 임시 파일로 ① 시작 백업 생성 ② 정상 종료(외부수정 0) → 경고 없음 ③ 외부에서 줄 삭제/추가 → 경고 발생. 순수 함수로 분리해 봇 실행 없이 단위테스트.
- **apply_corrections**: 오버레이 정확성 + corrections 없을 때 원본 보존.

---

## 7. 리스크 / 롤백

- A-2는 원본 미변경·append-only라 최악의 경우도 corrections 파일 삭제로 원복. 봇 무영향.
- A-3은 봇 코드 변경이라 **다음 graceful 재시작 때 발효**. 롤백 = 해당 커밋 revert 후 재시작. 백업/비교는 실패해도 봇 본 로직에 영향 없도록 try/except로 감싼다(가드가 봇을 죽이면 안 됨).
- 발효 확인: 재시작 로그에 백업 생성 메시지 + 시작 라인수 로그가 뜨는지.

---

## 8. 이 작업이 아닌 것 (스코프 경계)

- 로드맵 A-1(정본 자동병합기 전체)·A-4(일일 리포트)·A-5(watchdog)·B/C 항목은 **제외**. 본 작업은 A-2·A-3과 그 둘이 최소로 필요로 하는 `apply_corrections`·`pnl_corrections.jsonl`까지만.
- 거래로직(사이징·게이트·정원 등)은 일절 건드리지 않는다(v10 검증 보호).
