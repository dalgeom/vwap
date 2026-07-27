# Momentum Bot 데스크톱 앱 빌드 (Python 3.12 venv_app 사용)
# 사용: .\build_exe.ps1   → dist\MomentumBot\momentum_app.exe
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path "venv_app")) {
    Write-Host "venv_app 생성 (Python 3.12)..."
    py -3.12 -m venv venv_app
    .\venv_app\Scripts\python.exe -m pip install --upgrade pip
}
.\venv_app\Scripts\pip.exe install -q -r requirements.txt -r requirements-app.txt

Write-Host "PyInstaller 빌드..."
.\venv_app\Scripts\pyinstaller.exe momentum_app.spec --noconfirm
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 빌드 실패 (exit $LASTEXITCODE) — 앱/exe가 실행 중이면 종료 후 재시도" }

# 스모크: --version이 앱 버전을 찍고 종료하는지
# console=False(GUI subsystem) exe라 PowerShell의 `&` 직접 캡처가 stdout을 못 읽음 → 파일 리다이렉트로 캡처
$tmpOut = New-TemporaryFile
Start-Process -FilePath ".\dist\MomentumBot\momentum_app.exe" -ArgumentList "--version" `
    -NoNewWindow -Wait -RedirectStandardOutput $tmpOut
$v = (Get-Content $tmpOut -Raw).Trim()
Remove-Item $tmpOut
if (-not $v) { throw "스모크 실패: --version 출력 없음" }
Write-Host "빌드 완료: dist\MomentumBot\momentum_app.exe (버전 $v)"
