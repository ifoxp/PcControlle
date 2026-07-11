# PC Control — єдиний build-скрипт.
#
#   .\build.ps1 exe    — зібрати EXE (сервер) + чистий ZIP-дистрибутив у release\
#   .\build.ps1 apk    — зібрати APK (мобільний) у release\
#   .\build.ps1 all    — і EXE, і APK
#   .\build.ps1        — те саме, що all
#
# EXE збирається кореневим .venv (там cryptography/qrcode/pythonnet/PySide6 — без
# них exe падає на старті). ZIP містить ЛИШЕ PC Control.exe + README, без твоїх
# особистих файлів (.env, config.json, devices.json, cert/key, логи, скріни, стан).

param(
    [ValidateSet("exe", "apk", "all")]
    [string]$What = "all"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$VENV_PY = Join-Path $root ".venv\Scripts\python.exe"
$RELEASE = Join-Path $root "release"
New-Item -ItemType Directory -Force $RELEASE | Out-Null

function Build-Exe {
    Write-Host "`n=== [EXE] Збірка сервера ===" -ForegroundColor Cyan

    if (-not (Test-Path $VENV_PY)) {
        throw "Не знайдено $VENV_PY — потрібен кореневий .venv з залежностями (requirements.txt)."
    }

    # 1) зупинити запущений PC Control (файл exe інакше заблокований)
    $procs = Get-Process "PC Control" -ErrorAction SilentlyContinue
    if ($procs) {
        Write-Host "Зупиняю запущений PC Control (може зʼявитись UAC)..." -ForegroundColor Yellow
        try {
            $p = Start-Process taskkill -ArgumentList '/F', '/IM', '"PC Control.exe"', '/T' `
                 -Verb RunAs -PassThru -WindowStyle Hidden
            $p.WaitForExit(15000) | Out-Null
        } catch {
            Get-Process "PC Control" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 1
    }

    # 2) PyInstaller кореневим venv. PyInstaller пише прогрес у stderr — під
    # $ErrorActionPreference='Stop' це помилково вважається фатальним, тож на час
    # виклику знімаємо Stop і зливаємо stderr у stdout; успіх — за $LASTEXITCODE.
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $VENV_PY -m PyInstaller "PC Control.spec" --noconfirm 2>&1 | Out-Host
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prev
    if ($code -ne 0) { throw "PyInstaller failed (код $code)" }

    $exe = Join-Path $root "dist\PC Control.exe"
    if (-not (Test-Path $exe)) { throw "Не знайдено зібраний exe: $exe" }

    # 3) чистий ZIP-дистрибутив (лише exe + README) — БЕЗ особистих файлів
    Write-Host "=== [EXE] Пакування чистого ZIP ===" -ForegroundColor Cyan
    $stage = Join-Path $env:TEMP ("pcctl_release_" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force $stage | Out-Null
    Copy-Item $exe (Join-Path $stage "PC Control.exe") -Force
    $readme = Join-Path $root "dist_readme.txt"
    if (Test-Path $readme) { Copy-Item $readme (Join-Path $stage "README.txt") -Force }

    $ver = Get-Date -Format "yyyyMMdd"
    $zip = Join-Path $RELEASE "PC_Control_$ver.zip"
    if (Test-Path $zip) { Remove-Item $zip -Force }
    Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -Force
    Remove-Item $stage -Recurse -Force

    $mb = [math]::Round((Get-Item $zip).Length / 1MB, 1)
    Write-Host "DONE (EXE): $zip  ($mb МБ)" -ForegroundColor Green
}

function Build-Apk {
    Write-Host "`n=== [APK] Збірка мобільного ===" -ForegroundColor Cyan
    $apkScript = Join-Path $root "mobile_app\build_apk.ps1"
    if (-not (Test-Path $apkScript)) { throw "Не знайдено $apkScript" }

    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $apkScript 2>&1 | Out-Host
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prev
    if ($code -ne 0) { throw "APK build failed (код $code)" }

    $apk = Join-Path $root "mobile_app\build\flutter\build\app\outputs\flutter-apk\app-release.apk"
    if (-not (Test-Path $apk)) { throw "Не знайдено зібраний APK: $apk" }

    $ver = Get-Date -Format "yyyyMMdd"
    $dst = Join-Path $RELEASE "PC_Control_$ver.apk"
    Copy-Item $apk $dst -Force
    # також лишаємо копію в корені (звичний шлях для adb install)
    Copy-Item $apk (Join-Path $root "app-release.apk") -Force

    $mb = [math]::Round((Get-Item $dst).Length / 1MB, 1)
    Write-Host "DONE (APK): $dst  ($mb МБ)" -ForegroundColor Green
}

switch ($What) {
    "exe" { Build-Exe }
    "apk" { Build-Apk }
    "all" { Build-Exe; Build-Apk }
}

Write-Host "`nГотово. Артефакти у: $RELEASE" -ForegroundColor Green
