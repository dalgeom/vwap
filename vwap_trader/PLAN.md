# Momentum Bot — 전략 계획서 (v5.1)

> 최종 업데이트: 2026-05-27
> 이전 펀딩 역추세 봇 PLAN은 [PLAN_funding_legacy.md](PLAN_funding_legacy.md) 참조 (폐기됨)

---

## 1. 프로젝트 목표

Bybit USDT 무기한 선물 데모 계좌에서 **모멘텀 추종(Big Move Follow-Through)** 전략 자동 운영.
P99.5 percentile 이상 1h 봉 수익률 → 모멘텀 방향으로 진입 → BE+Trailing Stop 청산.

- **현재 단계**: v5.1 운영, 데이터 수집 중 (37 trades, 2 open)
- **검증 임계점**: 50건(첫 평가), 200건(Go/No-Go)

---

## 2. 현재 전략 — v5.1

### 핵심 원리
"1시간 봉 수익률이 과거 500봉의 99.5%ile을 초과하면, 그 방향으로 모멘텀이 계속될 확률이 높다."

### 2.1 동작 흐름

1. **매 1분**: 오픈 포지션 BE/Trail SL 갱신 (`_manage_positions`)
2. **매 정각 (분=0)**: 클럭 재sync + universe 스캔 + 신호 발생 시 진입
3. SL/TP는 Bybit 거래소에 등록 → 봇 다운 시에도 청산 보호
4. 봉 종가 close → 다음 1h 봉 open에서 시장가 진입

### 2.2 설정값 ([config/momentum_config.yaml](config/momentum_config.yaml))

| 항목 | 값 |
|------|----|
| Timeframe | 1h (signal) |
| 신호 임계값 | abs(ret) > 500봉 rolling 99.5%ile |
| ATR 기간 | 20 |
| 초기 SL | 1.5 × ATR |
| BE Trigger | 1.5 × ATR 수익 시 SL → entry |
| Trailing | best ± 2.0 × ATR |
| Max Hold | 48 bars (48h) |
| Cooldown | 1 bar (코인별) |
| 거래당 리스크 | 0.5% |
| 동시 포지션 | max 10 (long 3 + short 3 cap) |
| 정각당 max 진입 | 2건 |
| min 24h volume | $20M |

### 2.3 Tier Cap (v5.1 신규)

24h turnover 기준 position notional cap:

| Tier | 24h Volume | Max Position |
|------|------|------|
| 1 | > $500M | $10,000 |
| 2 | > $100M | $5,000 |
| 3 | > $50M | $2,000 |
| 4 | < $50M | $1,000 |
| Hard cap | — | $10,000 |

risk_pct로 계산된 사이즈가 cap을 넘으면 qty 비례 축소 (lot_size 단위 floor).

---

## 3. 버전 히스토리

| 버전 | 날짜 | 변경 내용 | 결과 |
|------|------|-----------|------|
| v1 | 2026-05-09 | 5분봉 모멘텀 + Fixed TP/SL | 비용 > edge, PF 0.88 |
| v2 | — | 데이터 수집만 | 동일 |
| v3.1 | 2026-05-17 | BTC DOWN 필터 (옵션 B) | EV -$70, 상관관계 집중 실패 |
| v4 | — | Pullback Entry (옵션 C) | MFE=0 75%, adverse selection |
| v4.1 | 2026-05-19 | 클러스터 제한 (옵션 G) | EV -$52, 5분봉 한계 명확 |
| v5 | 2026-05-21 | **1h 봉 전환 + BE+Trailing Stop** | OOS WR 98.7% 백테스트 |
| **v5.1** | **2026-05-23~27** | **1m 폴링 + Tier Cap + Clock resync + bot_version** | **운영 중** |

자세한 옵션 실패 분석은 [docs/upgrade_options.md](docs/upgrade_options.md) 참조.

---

## 4. v5.1 변경 사항 상세

### 4.1 1분 폴링 (가장 중요)

**발견된 결함**: v5 코드에서 `_main_loop`가 1h 정각에만 깨어남 → BE/Trail SL 갱신이 1h 지연.
**증거**: HYPEUSDT trade 2번 (be_triggered=true인데 SL은 초기값, -2.81% 손실).

**수정** ([momentum_bot.py:833-890](src/vwap_trader/momentum_bot.py#L833)):
- `_wait_next_minute()` 신규 (1분 단위 깨어남)
- 매 분 `_manage_positions()` (BE/Trail/Bybit SL update)
- 정각(분=0)에만 `_scan_universe()` (신호 검출 빈도 동일)

**검증**:
- NEARUSDT trade 23 (5/24): be_triggered=true, sl=entry → 정확한 BE 청산 (-0.06%, -$5.75)
- LITUSDT trade 28 (5/25): 동일 패턴 (-0.12%, -$13)

### 4.2 Tier Cap

**발견된 결함**: GRASSUSDT trade 27 (5/25 19:00) — 5분 만에 -30.10% (-$1,798) catastrophic slip. position $5,953, SL distance -2%였으나 호가창 잠식으로 -30% 체결.

**수정**: `_apply_tier_cap()` 신규 ([momentum_bot.py:172-237](src/vwap_trader/momentum_bot.py#L172)). 24h volume 기반 tier 분류 → notional 초과 시 qty 비례 축소.

**상태**: 코드 작동 검증됨 (NEAR trade 32에서 Tier 1 cap 안에 들어옴 → 미적용). **Tier 3/4 작은 코인 진입 시 실제 발동 검증 대기**.

### 4.3 Clock Resync (2단계 강화)

**발견된 결함**: 봇 3시간 운영 후 시스템 시계 drift → ErrCode 10002 폭주 → 거래 처리 마비.

**1차 수정** (5/26):
- 시작 시 monkey-patch 무조건 적용 (offset 작아도) — lambda가 글로벌 `_clock_offset_ms` 매 호출 lookup
- `_resync_clock_offset()` 매 **정각** 호출 ([momentum_bot.py:53-66](src/vwap_trader/momentum_bot.py#L53))

**2차 강화** (5/27): 정각만으로는 drift catch 못 함 (6분 만에 1초+ drift 케이스 발견)
- `_resync_clock_offset()` 호출 빈도: 정각 → **매 분**
- Balance fetch 실패 시 즉시 추가 resync ([momentum_bot.py:859-867](src/vwap_trader/momentum_bot.py#L859))

**검증**: 1시간당 약 -150ms drift 관찰. 매 분 자동 보정 → ErrCode 10002 = 0건.

### 4.4 bot_version 필드 + 시스템 시계 NTP

- `_log_trade` record에 `"bot_version": "v5.1"` 추가 → 분석 시 `t.get("bot_version") == "v5.1"`로 필터링.
- 외부 조치: 관리자 PowerShell에서 `w32tm /resync /force` (봇 시작 전 OS 시계 정확도 보장).

### 4.5 slippage_cooldown State 저장/복원

**발견된 결함**: 메모리 dict이라 봇 재시작 시 cooldown 정보 소실. GRASSUSDT가 catastrophic slip 후 48h cooldown 적용됐으나 봇 재시작으로 정보 사라져 cooldown 안에 재진입 발생.

**수정** ([momentum_bot.py:768-803](src/vwap_trader/momentum_bot.py#L768)):
- `_save_state`에서 `slippage_cooldown` dict를 ISO datetime 문자열로 직렬화 저장
- `_load_state`에서 복원 + 만료된 항목 자동 필터링
- 로그: `State loaded: N positions, bar=X, slip_cooldowns=Y`

### 4.6 Rate Limit 완화 (5/27, 2단계)

**발견**: 매 정각 universe scan 시 ErrCode 10006 폭주 (UTC 10/14시 특히 심함, 시간대 의존). _manage_positions에서도 산발적 발생. 자동 retry로 처리되지만 scan 시간 70초+ + 일부 심볼 skip (38/41).

**수정**:
| 위치 | 변경 |
|---|---|
| `_fetch_candles` 페이지네이션 sleep | 0.25s → **0.4s** |
| `_scan_universe` 심볼 간 sleep | 0.5s → **0.7s** |
| `_manage_positions` candle fetch sleep | 0.2s → **0.4s** |

**결과**: _manage_positions RL 4→1건. scan RL은 시간대별 큰 차이 (sleep만으로 한계). 더 줄이려면 옵션 검토 §8.4.

---

## 5. 운영 현황 스냅샷 (2026-05-28 기준, 37 trades)

> 실시간 데이터는 [data/trades_momentum.jsonl](data/trades_momentum.jsonl), [data/state_momentum.json](data/state_momentum.json) 직접 참조.

### 5.1 누적 통계

| 그룹 | 건수 | WR | 누적 PnL |
|------|------|------|------|
| v5 (1h polling) | 14 | 35.7% | +$1,358 |
| v5 (1m polling, no cap) | 17 | 35.3% | -$1,775 (GRASS2 -$1,798 포함) |
| **v5.1** | **6** | **33.3%** | **-$78** (BSB +$275, GRASS +$35, 4건 SL) |
| **합계** | **37** | **32.4%** | **-$495** |

### 5.2 청산 유형 분포

| 유형 | 건수 | 평균 PnL |
|---|---|---|
| TrailSL (winner) | 7 | +19.9% (BSB, BEAT1, NEAR1, BSB2, GRASS2(v5.1), HYPE3, NEAR3) |
| Timeout | 1 | +14.2% (PROVE) |
| BE 보호 | 3 | -1.00% (HYPE1 v5 결함, NEAR2/LIT3 v5.1 보호 ✓) |
| 일반 SL | 25 | -3.3% |
| Catastrophic SL | 1 | **-30.1%** (GRASS2 v5) ⚠️ |

### 5.3 패턴 인사이트

- **Hold 0~3봉 (즉시 반전)**: 거의 100% 손실. 신호 직후 trend reversal — 전략 자체 한계.
- **Hold 7~38봉 (모멘텀 형성)**: trailing이 큰 winner 견인 (BSB +24%, +50%).
- **누적 수익은 6~7건의 jackpot에 의존**: BSB(x2), BEAT1, NEAR1, PROVE, IN2 등.
- **v5.1 trailing 정상 작동 검증**: BSB(38h) +24%, GRASS(22h) +4% — 1m 폴링이 trailing edge 확보.
- **즉시 반전 SL 비율 (v5.1)**: 4/6 = 67% — 전략 약점 지속.

### 5.4 Signal_ret 임계값 분석 (n=37)

| Threshold | n | WR | Avg PnL | Net PnL |
|---|---|---|---|---|
| 모두 | 37 | 32.4% | -0.5% | -$495 |
| **abs >= 8%** | ~10 | **~50%** | **~+6%** | **약 +$1,200** 🌟 |
| abs < 5% (weak) | ~14 | ~35% | ~-0.5% | 음수 |

**핵심**: 약한 신호 (abs < 5%)가 손실 주범. 강한 신호 (abs >= 8%)는 net positive.

**단 표본 작음** (abs >= 8% n=10). 즉시 적용 보류. 그러나 NEAR1 +21%(sig +4%), PROVE +14%(sig -4.5%) 같은 weak winner도 존재 → 단순 threshold filter 위험. **volume spike, regime 등 추가 filter 필요**.

---

## 6. 안전장치 종합

| 항목 | 위치 | 동작 |
|------|------|------|
| Bybit SL 등록 | place_order 시 | 거래소가 자동 청산 |
| BE/Trail 1분 갱신 | _manage_positions | best 추적, SL 이동 |
| Tier Cap | _apply_tier_cap | catastrophic slip 손실 한정 |
| Slippage Cooldown | _log_trade | slip > 1%p 시 해당 심볼 48h 차단 |
| **Cooldown State 저장** (v5.1) | _save/_load_state | 봇 재시작 시 cooldown 정보 복원 |
| **Clock Resync 매 분** (v5.1) | _main_loop | timestamp drift 보정 (정각 → 매 분 강화) |
| **Balance Fail 시 즉시 Resync** (v5.1) | _main_loop | timestamp 의심 시 추가 보정 |
| **API Rate Limit 완화** (v5.1) | _fetch_candles, _scan, _manage | sleep 0.5/0.2 → 0.7/0.4 (ErrCode 10006 감소) |
| Daily PnL Reset | UTC 자정 | daily_pnl, daily_trades 초기화 |
| STOP 파일 | data/STOP_MOMENTUM | 다음 분에 봇 정상 종료 |
| Heartbeat | data/heartbeat_momentum | 외부 watchdog용 |

---

## 7. 향후 모니터링 항목

### 7.1 v5.1 효과 검증 (단기, 50건까지)

- [x] **Tier Cap 실제 발동** ✓ — PHA $1,000, ESPORTS $908, GRASS $999, XPL $999 (4건 적용 확인)
- [x] **BE 보호 작동** ✓ — NEAR2, LIT3, ERA(오픈) 3건 검증
- [x] **Trailing winner** ✓ — BSB +24%(v5.1), GRASS +4%(v5.1) — 1m 폴링이 trailing edge 확보
- [x] **ErrCode 10002 차단** ✓ — clock resync 매 분 강화 후 0건
- [x] **Rate Limit 완화** ✓ — manage_positions RL 4→1건, scan은 시간대별 변동 (UTC 10/14시 폭주)
- [ ] **즉시 반전 SL 비율** ⚠️ — v5.1 4/6 = 67% (NEAR/ESPORTS/PHA/ETH). 전략 약점 지속
- [ ] **50건 누적 시 winner ratio 안정성**

### 7.2 전략 자체 평가 (중기, 200건)

- [ ] **Winner ratio 안정성** — 큰 winner 5건 의존도 지속? 신뢰성 확인
- [ ] **Catastrophic loss 빈도** — GRASS2 같은 케이스가 다시 나오는지 + tier cap이 손실 1/6 수준으로 한정하는지
- [ ] **regime별 성과** — UP/DOWN/FLAT_HIGH × long/short 분포
- [ ] **시간대별 성과** — 정각 동시 다발 fail 패턴 분석

### 7.3 Go/No-Go 기준 (200건 시점)

- **Go**: WR > 40%, PF > 1.2, 평균 EV > 0, max DD < 15%
- **No-Go**: 위 조건 미달 시 v6 또는 전략 변경 검토

### 7.4 전략 사망 판정

- 60일 rolling Sharpe < 0.5
- 100거래 승률 < 30%
- 월간 누적 PnL < 0% 3개월 연속

---

## 8. 알려진 한계 / 향후 개선 후보

### 8.1 즉시 반전 SL (전략 한계 — 가장 큰 문제)
**문제**: hold 0~3봉 SL이 전체 손실의 주요 원인. 신호 직후 trend reversal. v5.1 후에도 지속.
**가설**: P99.5% 신호 중 일부는 "exhaustion spike" (반전 임박). momentum follow가 아니라 mean reversion 대상.
**5/27 데이터 분석 시사점** (n=34, 표본 작음):
- abs(signal_ret) >= 8% 만 거래했을 시 가상 net +$1,246 (현재 -$728 대비)
- 약한 신호 (3~5%)가 손실의 주범
- 단순 threshold filter는 NEAR1 (+20%, sig +4%) / PROVE (+14%, sig -4.5%) 같은 weak signal winner도 잃음
**후보 대응**:
- volume spike 확인 추가 (momentum의 "real" 시그널 식별)
- BTC regime과 alt direction 일치 여부 필터
- 신호 직후 1~2분 가격 행동 확인 후 지연 진입 (백테스트 검증 필요)
- pullback 진입 재검토 (v4 실패 이유 재분석 후)

### 8.2 Catastrophic Slip
**문제**: Tier Cap으로 손실 1/6 한정 가능 (검증됨). 그러나 근본 원인(저유동성 코인의 호가창 잠식)은 해결 못 함.
**후보 대응**:
- min_volume_usdt $20M → $50M~100M (universe 축소)
- 진입 직후 -10% 도달 시 강제 reduce-only market order (이중 가드)
- Bybit native trailingStop 사용 (거래소가 1초 단위 처리)
- ESPORTS 같은 고변동성 코인 별도 blacklist (1.5 ATR이 entry의 10%+ 인 코인)

### 8.3 Smart Position Sizing (현재 미적용)
**가능성**: 코인별 historical 슬리피지 데이터 누적 후 tier cap을 더 정밀하게 (예: median slip > 0.5% 코인은 추가 축소).
**제약**: 표본 부족. 50~100건 더 누적 필요.

### 8.4 Rate Limit 부하 (5/27 2단계 완화 — 부분 해결)
**문제**: 매 정각 universe scan 시 ErrCode 10006. **시간대 의존성** 명확: UTC 10/14시 (미국 시장 시간) 5~6건 폭주, 다른 시간대 1~2건 안정. sleep만으론 burst limit 한계.
**적용** (§4.6 참조): _fetch_candles 페이지 0.25→0.4, _scan 심볼 0.5→0.7, _manage 0.2→0.4.
**결과**: _manage_positions RL 4→1건 ✓. scan RL은 시간대별 큰 차이 잔존.
**효과 부족 시 후보**: 심볼 간 sleep 0.7→1.0, universe scan을 정각+30초로 분산, incremental cache 강화.

---

## 9. 봇 실행

```powershell
cd c:\Users\PC\Desktop\현진\code\vwap_trader
.\venv\Scripts\Activate.ps1
python -m vwap_trader.momentum_bot
```

**중단**:
- 안전: `data/STOP_MOMENTUM` 파일 생성 → 다음 분에 정상 종료
- 즉시: 프로세스 kill (state.json 매 분 저장되어 손실 거의 없음)

**실전 전환 시**: [config/momentum_config.yaml](config/momentum_config.yaml)에서 `exchange.demo: true` → `false`

---

## 10. 의사결정 이력

| 날짜 | 결정 |
|------|------|
| 2026-05-21 | 5분봉 v1~v4.1 전부 실패 → 1h봉 v5 전환 + BE+Trailing |
| 2026-05-23 | 실전 WR 30% vs 백테스트 98.7% 괴리 진단 시작 |
| 2026-05-23 | 가설 검증: 인트라바 SL ❌, 유니버스 편향 ❌, 신호 검출 차이 ❌ |
| 2026-05-23 | **진짜 원인 확정**: BE/Trail 1h 폴링 지연 (HYPE1 케이스) |
| 2026-05-23 | **v5.1 시작**: 1m 폴링 적용 |
| 2026-05-24 | BE 보호 첫 검증 (NEAR2, -0.06%) |
| 2026-05-25 | LIT3 BE 보호 두 번째 검증 (-0.12%) |
| 2026-05-25 | **GRASS2 catastrophic loss** (-$1,798) → tier cap 필요성 확인 |
| 2026-05-26 | tier cap 구현 + bot_version 필드 추가 |
| 2026-05-26 | ErrCode 10002 timestamp drift → 주기적 clock resync (매 정각) 구현 |
| 2026-05-27 | Tier Cap 실제 발동 검증 (PHA/ESPORTS/GRASS 모두 Tier 4 cap 적용) |
| 2026-05-27 | signal_ret 임계값 분석 — "weak 신호가 손실 주범", 8% threshold 시 net +$1,246 추정. 표본 작아 즉시 적용 보류 |
| 2026-05-27 | slippage_cooldown state.json 저장/복원 구현 (봇 재시작 시 cooldown 정보 유지) |
| 2026-05-27 | Clock resync 매 분 강화 + balance fail 시 즉시 resync (정각만으론 부족) |
| 2026-05-27 | Rate Limit 완화 1차: `_fetch_candles` 페이지 sleep 0.25→0.4s, `_scan_universe` 심볼 sleep 0.5→0.7s |
| 2026-05-27 | Rate Limit 완화 2차: `_manage_positions` candle fetch sleep 0.2→0.4s (산발적 RL 차단) |
| 2026-05-27 | **BSB v5.1 첫 trailing winner** +23.92% (+$275, hold 38봉) — 1m 폴링 + BE/Trail 정상 작동 검증 |
| 2026-05-28 | GRASS v5.1 두 번째 trailing winner +3.63% (+$35, hold 22봉) |
| 2026-05-28 | ETH 즉시 반전 SL (-0.66%, weak signal -2.25%) — 약한 신호 즉시 반전 패턴 재확인 |
| 2026-05-28 | XPL 신규 진입 (Tier 4 cap $999.94) — 4번째 cap 발동 사례 |
| 2026-05-28 | Rate Limit 시간대 의존성 확인 (UTC 10/14시 폭주, sleep만으론 한계) |
