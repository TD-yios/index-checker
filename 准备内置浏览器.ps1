$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Vendor = Join-Path $Root "vendor"
$Dest = Join-Path $Vendor "chrome-win64"
$Exe = Join-Path $Dest "chrome.exe"

if (Test-Path $Exe) {
    Write-Host "内置浏览器已存在：$Exe"
    exit 0
}

New-Item -ItemType Directory -Force -Path $Vendor | Out-Null
$ProgressPreference = "SilentlyContinue"
Write-Host "读取 Chrome for Testing 最新稳定版信息..."
$Info = Invoke-RestMethod -Uri "https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json" -TimeoutSec 30
$Stable = $Info.channels.Stable
$Item = $Stable.downloads.chrome | Where-Object { $_.platform -eq "win64" } | Select-Object -First 1
if (-not $Item) { throw "未找到 win64 版本的下载地址" }

$Zip = Join-Path $Vendor "chrome-win64.zip"
Write-Host "下载 Chrome $($Stable.version) ..."
& curl.exe -L --fail --retry 2 -o $Zip $Item.url
if ($LASTEXITCODE -ne 0) { throw "下载失败，退出码 $LASTEXITCODE" }

Write-Host "解压..."
if (Test-Path $Dest) { Remove-Item $Dest -Recurse -Force }
Expand-Archive -Path $Zip -DestinationPath $Vendor -Force
Set-Content -Path (Join-Path $Dest "version.txt") -Value $Stable.version -Encoding UTF8
Write-Host "完成：$Exe"
