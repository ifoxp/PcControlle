# Build APK with working deep-link (pccontrol://pair).
#
# flet 0.85 reads [tool.flet.deep_linking] but leaves only a marker comment in the
# manifest without inserting the intent-filter (version bug). So:
#   1) flet build apk    - generates Flutter project + manifest (no deep-link)
#   2) patch_manifest.py  - inserts the intent-filter into the manifest
#   3) flutter build apk  - rebuilds APK with the patched manifest
#
# Run:  .\build_apk.ps1
# APK:  build\flutter\build\app\outputs\flutter-apk\app-release.apk

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$FLUTTER = "C:\Users\ifoxp\flutter\3.41.7\bin"
$ANDROID = "C:\Users\ifoxp\Android\sdk"
$FLET    = Join-Path $root ".venv\Scripts\flet.exe"
$PY      = Join-Path $root ".venv\Scripts\python.exe"

$env:PATH = "$FLUTTER;$env:PATH"
$env:ANDROID_HOME = $ANDROID
$env:ANDROID_SDK_ROOT = $ANDROID
$env:PYTHONIOENCODING = "utf-8"

Write-Host "[1 of 3] flet build apk ..." -ForegroundColor Cyan
& $FLET build apk --no-rich-output
if ($LASTEXITCODE -ne 0) { throw "flet build failed" }

Write-Host "[2 of 3] patch AndroidManifest deep-link ..." -ForegroundColor Cyan
& $PY (Join-Path $root "patch_manifest.py")
if ($LASTEXITCODE -ne 0) { throw "manifest patch failed" }

Write-Host "[3 of 3] flutter build apk ..." -ForegroundColor Cyan
$env:SERIOUS_PYTHON_SITE_PACKAGES = Join-Path $root "build\site-packages"
Push-Location (Join-Path $root "build\flutter")
& flutter build apk --release
$code = $LASTEXITCODE
Pop-Location
if ($code -ne 0) { throw "flutter build failed" }

$apk = Join-Path $root "build\flutter\build\app\outputs\flutter-apk\app-release.apk"
Write-Host "`nDONE: $apk" -ForegroundColor Green
