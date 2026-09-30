# -*- mode: python ; coding: utf-8 -*-
"""
DevDocs Copilot 桌面版 PyInstaller 打包配置（唯一事实来源）。

用法（项目根目录）：
    pip install -r requirements-build.txt
    pyinstaller --noconfirm --clean devdocs-copilot.spec

产物：dist/DevDocsCopilot/（onedir 绿色目录，双击其中 DevDocsCopilot.exe 运行）
设计说明：
  - onedir 而非 onefile：chromadb 带 onnxruntime 等重依赖，onefile 每次启动
    都要把几百 MB 解压到临时目录，启动慢且磨损磁盘；
  - datas 只带"只读资源"：前端 static、预置语料、.env 模板。
    .env / data / uploads 全部在运行时生成于 exe 旁，绝不进包；
  - 图标 assets/icon.ico 存在则使用，缺失时退回 PyInstaller 默认图标，
    保证图标未就位时打包链路也能跑通。
"""
import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# ---- 1. 随包只读资源：(源路径, 包内目标目录) ----
datas = [
    ("static", "static"),
    ("desktop_seed", "desktop_seed"),
    (".env.example", "."),
]
binaries = []
hiddenimports = [
    # python-multipart / aiofiles：FastAPI 文件上传链路运行时才查找
    "multipart",
    "multipart.multipart",
    "aiofiles",
]

# ---- 2. 带数据文件或动态发现子模块的包，整包收集（静态分析扫不全） ----
for pkg in (
    "chromadb",        # 迁移脚本/thrift/otel 等大量动态导入
    "opentelemetry",   # chromadb 依赖，exporter 子模块动态加载
    "jieba",           # 自带 dict.txt 词典数据
    "docx",            # python-docx 自带 default.docx 模板
    "pypdf",           # 纯 py，整包收集成本极低，防 cmaps 类资源遗漏
):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

# uvicorn 的 loops/protocols/lifecycle 按字符串动态导入，hook 外再补一层保险
hiddenimports += collect_submodules("uvicorn")

# ---- 3. 明确用不到的大件，排除掉控制体积 ----
excludes = [
    "tkinter",
    "matplotlib",
    "PIL",
    "PySide6",
    "PyQt5",
    "PyQt6",
    "IPython",
    "notebook",
    "jupyterlab",
    "pytest",
]

icon_path = os.path.abspath(os.path.join("assets", "icon.ico"))
exe_icon = icon_path if os.path.exists(icon_path) else None


a = Analysis(
    ["run_desktop.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DevDocsCopilot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,          # 控制台版：服务日志可见，关窗即退出
    disable_windowed_traceback=False,
    icon=exe_icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="DevDocsCopilot",
)
