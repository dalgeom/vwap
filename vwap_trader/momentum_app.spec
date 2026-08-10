# -*- mode: python ; coding: utf-8 -*-
# 빌드: .\venv_app\Scripts\pyinstaller.exe momentum_app.spec --noconfirm
# onedir 채택: onefile은 시작 지연·임시폴더 추출·백신 오탐이 있어 배제.
a = Analysis(
    ["app\\main.py"],
    pathex=[".", "src"],
    binaries=[],
    datas=[("app/ui", "app/ui")],
    hiddenimports=[
        # 봇 (frozen --bot 모드)
        "vwap_trader.momentum_bot",
        # demo/real 경로 규칙 단일 출처 (지연 import — 정적 분석 누락 대비)
        "vwap_trader.mode_paths",
        # report_runner가 런타임 import하는 최상위 스크립트들
        "daily_report", "build_canonical", "corrections",
        "fix_estimated", "xcrowd_snapshot",
        # daily_report가 지연 import하는 보드 모듈 (정적 분석이 놓친다)
        "app.hypotheses", "app.metrics", "app.journal",
        # 거래소
        "pybit.unified_trading",
    ],
    hookspath=[], runtime_hooks=[], excludes=[],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="momentum_app",
    console=False,           # 창 없는 exe — 봇 로그는 logs/momentum_bot.log
    icon=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="MomentumBot")
