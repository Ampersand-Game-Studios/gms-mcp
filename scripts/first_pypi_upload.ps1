Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "[INFO] Building distributions..." -ForegroundColor Cyan
python -m pip install -U build twine | Out-Null

if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }

python -m build

Write-Host "[INFO] Checking distributions..." -ForegroundColor Cyan
python -m twine check dist/*

Write-Host ""
Write-Host "[ACTION REQUIRED] Enter your PyPI API token (starts with 'pypi-')." -ForegroundColor Yellow
$secure = Read-Host -AsSecureString "PyPI token"
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}

$env:TWINE_USERNAME = "__token__"
$env:TWINE_PASSWORD = $token

Write-Host "[INFO] Uploading to PyPI..." -ForegroundColor Cyan
python -m twine upload dist/*
if ($LASTEXITCODE -ne 0) {
    throw "twine upload failed with exit code $LASTEXITCODE"
}

Write-Host "[OK] Uploaded. Next: configure Trusted Publishing in PyPI for GitHub Actions." -ForegroundColor Green
