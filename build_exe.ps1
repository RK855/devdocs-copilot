# ============================================================
# DevDocs Copilot 桌面版一键打包脚本（Windows PowerShell）
#
# 用法（在项目根目录）：
#   .\build_exe.ps1 -Version 1.0.0
#
# 产物：
#   dist/DevDocsCopilot/                      绿色版程序目录
#   dist/DevDocsCopilot-<ver>-windows-x64.zip 供 GitHub Releases 上传
# ============================================================
param(
    [string]$Version = "1.0.0"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# 优先使用项目自带 venv 的解释器（无需先手动激活），找不到再退回 PATH 中的 python
$python = if (Test-Path ".\venv\Scripts\python.exe") { ".\venv\Scripts\python.exe" } else { "python" }

if (Test-Path "assets/icon.png") {
    Write-Host "[0/3] 由 assets/icon.png 生成多尺寸 icon.ico ..." -ForegroundColor Cyan
    & $python scripts/make_icon.py
    if ($LASTEXITCODE -ne 0) { throw "图标生成失败" }
} elseif (-not (Test-Path "assets/icon.ico")) {
    Write-Host "[提示] 未找到 assets/icon.png / icon.ico，本次将使用默认图标" -ForegroundColor Yellow
}

Write-Host "[1/3] 执行 PyInstaller 打包..." -ForegroundColor Cyan
& $python -m PyInstaller --noconfirm --clean devdocs-copilot.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败" }

Write-Host "[2/3] 清理运行时残留（.env / data / uploads 不能进分发包）..." -ForegroundColor Cyan
foreach ($name in @(".env", "data", "uploads")) {
    $target = Join-Path "dist/DevDocsCopilot" $name
    if (Test-Path $target) {
        Remove-Item -Recurse -Force $target
        Write-Host "  已清理 $name"
    }
}

Write-Host "[3/3] 压缩发布 zip..." -ForegroundColor Cyan
$zip = "dist/DevDocsCopilot-$Version-windows-x64.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
Compress-Archive -Path "dist/DevDocsCopilot" -DestinationPath $zip

$size = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Host ""
Write-Host "打包完成：$zip （$size MB）" -ForegroundColor Green
