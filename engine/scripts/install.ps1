# Zylch installer for Windows
# Run: irm https://raw.githubusercontent.com/malemi/zylch/main/scripts/install.ps1 | iex

Write-Host ""
Write-Host "  Zylch - Sales Intelligence"
Write-Host "  ==========================="
Write-Host ""

$url = "https://github.com/malemi/zylch/releases/latest/download/zylch-windows-x64.exe"
$installDir = "$env:LOCALAPPDATA\Zylch"
$exe = "$installDir\zylch.exe"

# Detect install vs upgrade
$isUpgrade = Test-Path $exe

# Create install directory
if (-not (Test-Path $installDir)) {
    New-Item -ItemType Directory -Path $installDir -Force | Out-Null
}

# Download
Write-Host "  Downloading..."
try {
    Invoke-WebRequest -Uri $url -OutFile $exe -UseBasicParsing
} catch {
    Write-Host "  Download failed. Check: https://github.com/malemi/zylch/releases"
    Write-Host ""
    Write-Host "  Alternative (requires Python 3.11+):"
    Write-Host "    pip install zylch"
    exit 1
}

# Add to PATH if not already there
$currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($currentPath -notlike "*$installDir*") {
    [Environment]::SetEnvironmentVariable("Path", "$currentPath;$installDir", "User")
    Write-Host "  Added to PATH (restart terminal to use)"
}

$action = if ($isUpgrade) { "Updated" } else { "Installed" }

Write-Host ""
Write-Host "  $action! Run:"
Write-Host ""
if ($isUpgrade) {
    Write-Host "    zylch --help"
} else {
    Write-Host "    zylch init"
}
Write-Host ""
