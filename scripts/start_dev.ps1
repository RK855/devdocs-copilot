# ============================================================
# DevDocs Copilot 开发模式一键启动（Windows PowerShell）
#
# 入口是项目根目录的 start.bat（双击即可），逻辑集中在这里：
#   - 优先用项目自带 venv，找不到退回 PATH 里的 python
#   - .env 缺失时自动由 .env.example 生成
#   - 端口从 .env 读取，启动前提示端口冲突
#   - 启动后自动打开浏览器（-NoBrowser 可跳过）
#
# 与打包版区别：直接运行当前源码，改代码即刻生效（DEBUG 热重载）。
# ============================================================
param(
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

# 本脚本在 scripts\ 下，上一级即项目根
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = if (Test-Path ".\venv\Scripts\python.exe") { ".\venv\Scripts\python.exe" } else { "python" }

# 解释器可用性检查：venv 坏了会退回 python，两者都没有才报错
try {
    & $python --version | Out-Null
} catch {
    Write-Host "[错误] 找不到可用的 Python，请先在项目根执行：" -ForegroundColor Red
    Write-Host "        python -m venv venv" -ForegroundColor Red
    Write-Host "        venv\Scripts\pip install -r requirements.txt" -ForegroundColor Red
    Read-Host "按回车退出"
    exit 1
}

# .env 缺失时从示例生成，避免首次运行只看到一堆 API Key 报错
if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
    Write-Host "[提示] 未找到 .env，已由 .env.example 生成，请先填入 API Key" -ForegroundColor Yellow
}

# 端口与 .env 保持一致，避免浏览器打开错地址
$port = 8000
if (Test-Path ".env") {
    $hit = Select-String -Path ".env" -Pattern "^\s*PORT\s*=" | Select-Object -Last 1
    if ($hit) { $port = $hit.Line.Split("=", 2)[1].Trim() }
}

# 常见坑：已打包的 exe 还占着端口，开发版就起不来，提前说明
$busy = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    Write-Host "[警告] 端口 $port 已被占用（可能是已打包的 exe 仍在运行）" -ForegroundColor Yellow
    Write-Host "       请先关闭它，或在 .env 里把 PORT 改成别的值" -ForegroundColor Yellow
}

Write-Host "[启动] 开发模式（热重载）：http://127.0.0.1:$port/" -ForegroundColor Cyan
Write-Host "[提示] 已开启热重载，改代码即自动生效；按 Ctrl+C 停止服务" -ForegroundColor DarkGray
Write-Host ""

if (-not $NoBrowser) {
    # 后台等待服务就绪再开浏览器，直接开容易白屏
    $uri = "http://127.0.0.1:$port/"
    Start-Job -ArgumentList $uri -ScriptBlock {
        param($u)
        Start-Sleep -Seconds 5
        Start-Process $u
    } | Out-Null
}

# 直接跑 main.py，热重载开关由 settings.DEBUG 控制
& $python main.py

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[错误] 服务异常退出（退出码 $LASTEXITCODE）" -ForegroundColor Red
    Write-Host "       常见原因：端口 $port 被占用、.env 中 API Key 未填、依赖未安装" -ForegroundColor Red
    Read-Host "按回车退出"
    exit $LASTEXITCODE
}
