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
        # report_runner가 런타임 import하는 최상위 스크립트들
        "daily_report", "build_canonical", "corrections",
        "fix_estimated", "xcrowd_snapshot",
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
