전략 카테고리 지도
#	카테고리	상태	핵심 로직	암호화폐 1H 적합성	예시 전략
1	추세 추종 (VWAP 기반)	탐색완료 ✅ LIVE	VWAP+EMA 정렬 + 스윙 되돌림 후 재진입	상	Module B Long
2	가격 구조 (스윙 돌파)	탐색완료 ✅ LIVE	4H 스윙 고점 돌파 + 1H 풀백 확인	상	4H Swing Breakout
3	평균회귀 (통계적)	탐색완료 ❌ DEP	볼린저 밴드 이탈 후 평균 복귀	하 (추세 시장 충격)	Module A Long
4	변동성 수축 (스퀴즈)	보류 ⏸	BB 폭 수축 후 방향 이탈 + OI 확인	중	BB Squeeze + OI
5	시간대 돌파 (아시아)	탐색완료 ❌ DEP	아시아 세션 레인지 → 런던 오픈 돌파	하 (BTC/ETH mean-reversion 우위)	Asia Range Breakout
6	시간대 돌파 (ORB-NY)	탐색완료 ❌ DEP	NY 오픈 첫 봉 레인지 돌파	하 (Sharpe 0.16, MDD 104%)	ORB-NY
7	펀딩비 차익	미탐색	극단 펀딩비(>0.1%) 역방향 진입 — 시장이 과도하게 한쪽으로 쏠릴 때 반대 베팅	상 (암호화폐 고유 메커니즘)	Funding Rate Contrarian
8	모멘텀 (가격 변화율)	미탐색	ROC/RSI 모멘텀 지속성 — 크게 오른 자산이 단기적으로 더 오르는 경향 활용	상 (고변동성 시장 검증됨)	Cross-Asset Momentum (BTC→ALT 전파)
9	유동성 레벨 사냥	미탐색	전 고점/저점 위 청산 클러스터 → 스팟 방향 추종 진입	상 (암호화폐 선물 고유)	Liquidity Grab + Reversal
10	통계적 차익 (페어)	미탐색	BTC↔ETH 또는 ETH↔SOL 상관계수 이탈 → 수렴 베팅	중 (상관관계 체계적 붕괴 위험)	Crypto Pairs Trading
11	OI 모멘텀	미탐색	OI 급증 + 가격 방향 일치 → 포지션 누적 추종	상 (선물 전용, 암호화폐 데이터 풍부)	OI-Led Trend Entry
12	VWAP 앵커 되돌림	미탐색	주요 이벤트(주봉/캔들 오픈) 앵커 VWAP → 이탈 후 재접근 시 매매	중	Anchored VWAP Reversion
13	Ichimoku 구름 돌파	미탐색	구름(Kumo) 위/아래 확정 + 선행 스팬 기울기 방향 일치 진입	중 (1H 노이즈 多)	Kumo Breakout
14	CVD (누적 거래량 편차) 다이버전스	미탐색	가격 신고점인데 CVD 하락 → 실제 매수세 약화 → 추세 전환	상 (tick 데이터 필요 없음, 1H CVD 집계 가능)	CVD Divergence
15	주봉/일봉 레벨 돌파	미탐색	상위 봉 구조(W, D) 지지/저항 돌파를 1H 확정 신호로 진입	상	Multi-Timeframe Level Break
16	거래량 프로파일 (VPOC)	미탐색	가장 많이 거래된 가격대(VPOC) 재방문 + 이탈 방향 추종	중 (계산 복잡, 심볼 의존성 高)	VPOC Retest Continuation
17	갭 필링	미탐색	가격 갭(CME 갭, 주말 갭) 형성 후 복귀 수렴	하 (암호화폐 24/7 — 갭 구조 제한적)	CME Gap Fill
18	이벤트 드리븐 (온체인)	미탐색	고래 이동, 거래소 입출금 급증 → 단기 방향 신호	하 (1H봉 OHLCV 외 데이터 필요, 구현 난이도 高)	On-chain Event Trigger
19	분기/월별 계절성	미탐색	암호화폐 월별 수익률 패턴(1월 효과, 선물 만기 주기) 활용	하 (표본 수 부족, p-hacking 위험)	Crypto Seasonality
20	머신러닝 피처 앙상블	미탐색	다수 기술 지표 → ML 모델(XGBoost 등) 신호 생성	중 (과적합 위험 극심, 검증 프로세스 필요)	ML Ensemble Signal