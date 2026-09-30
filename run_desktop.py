"""
DevDocs Copilot —— 桌面版启动器（PyInstaller 打包入口）

运行形态：本地 HTTP 服务 + 浏览器界面（不是传统窗口程序）。
双击 DevDocsCopilot.exe 后的流程：
  1. 首次启动在 exe 旁生成 .env（从包内模板拷贝），给出免费申请指引，
     可自动打开 Key 申请网页，并用记事本打开 .env 引导填入两个 API Key；
  2. 向量库为空时自动灌入随包预置语料（仅首次，之后重启秒开）；
  3. 挑选一个空闲端口启动本地服务，并自动打开默认浏览器。
关闭控制台窗口（或 Ctrl+C）即停止服务。

开发态也可用 ``python run_desktop.py`` 调试这套桌面启动流程。
注意：本模块顶部只能导入标准库——app.config 的 settings 在导入时即实例化，
而 .env 就位必须早于它，所以所有 app.* 导入都延迟到函数内部。
"""
import asyncio
import os
import shutil
import socket
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

# Chroma 默认带匿名遥测，桌面版直接关掉，少一笔对外流量
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

APP_NAME = "DevDocs Copilot"


def _setup_console() -> None:
    """Windows 控制台默认 GBK 代码页，强制 UTF-8 输出，避免中文横幅炸成 UnicodeEncodeError"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def _print_banner(url: str, app_home: Path) -> None:
    line = "=" * 66
    print("\n" + line)
    print(f"  {APP_NAME}  ·  本地技术文档问答助手")
    print("-" * 66)
    print(f"  服务地址：{url}")
    print(f"  数据目录：{app_home}")
    print("  退出方式：直接关闭本窗口，或按 Ctrl+C")
    print(line + "\n")


def _ensure_env_file(app_home: Path, resource_dir: Path) -> Path:
    """exe 旁没有 .env 时，从包内模板拷一份；顺手把 DEBUG 关成桌面模式。

    .env.example 里 DEBUG=true 是给开发者热重载用的；桌面版以 app 对象直传
    uvicorn（本就不会 reload），改配置只是让用户看到的值与实际运行形态一致。
    """
    env_path = app_home / ".env"
    if env_path.exists():
        return env_path

    template = resource_dir / ".env.example"
    if template.exists():
        shutil.copyfile(template, env_path)
        text = env_path.read_text(encoding="utf-8").replace("DEBUG=true", "DEBUG=false")
        env_path.write_text(text, encoding="utf-8")
    else:
        env_path.touch()
    return env_path


def _is_real_key(value: str) -> bool:
    """空值或模板占位符（your-xxx）都视为未配置"""
    value = (value or "").strip()
    return bool(value) and not value.startswith("your-")


def _check_keys(settings, env_path: Path) -> None:
    """两个 Key 缺一不可：免费申请说明 + 可选自动打开申请页 + 记事本引导。"""
    missing = []
    if not _is_real_key(settings.AGNES_API_KEY):
        missing.append((
            "(1)", "Agnes", "聊天模型（理解问题、组织回答）",
            "AGNES_API_KEY", "https://agnes-ai.com",
        ))
    if not _is_real_key(settings.SILICONFLOW_API_KEY):
        missing.append((
            "(2)", "硅基流动 SiliconFlow", "向量 / 精排模型（文档语义检索）",
            "SILICONFLOW_API_KEY", "https://siliconflow.cn",
        ))
    if not missing:
        return

    line = "=" * 66
    print("\n" + line)
    print("  首次使用 · 只差最后一步：填写两个 API Key")
    print(line)
    print("  程序本身不含 AI 模型，需要两个云端平台的 Key。")
    print("  放心，这两个平台的对应模型【目前官网均可免费申请】，")
    print("  注册即领，免费额度足够日常学习使用：")
    print()
    for index, name, desc, key_line, url in missing:
        print(f"  {index} {name} —— {desc}")
        print(f"        申请地址：{url}")
        print(f"        填写位置：{key_line}=  等号后面")
        print()
    print("-" * 66)
    print("  配置文件顶部有完整说明（含换用其他模型的方法），")
    print("  马上为你用记事本打开：")
    print(f"    {env_path}")
    print()

    try:
        choice = input(
            "  直接回车：自动打开申请网页并打开配置文件\n"
            "  输入 n 回车：只打开配置文件（已有 Key 时选这个）\n"
            "  > "
        ).strip().lower()
    except EOFError:
        choice = "n"

    if choice != "n":
        for item in missing:
            webbrowser.open(item[-1])

    try:
        subprocess.Popen(["notepad.exe", str(env_path)])
    except OSError:
        # 极端情况（精简版系统没带记事本）退回系统默认关联程序
        os.startfile(str(env_path))  # type: ignore[attr-defined]

    print()
    print("  接下来：")
    print("    1. 在网页里注册并创建两个 Key（复制好）")
    print("    2. 回到记事本，把两个 Key 粘贴到对应等号后面，Ctrl+S 保存")
    print("    3. 关闭记事本，回到本窗口按回车退出")
    print("    4. 重新双击 DevDocsCopilot.exe，会自动灌入预置文档并打开界面")
    print(line + "\n")

    try:
        input("  全部填好后，按回车键退出……")
    except EOFError:
        pass
    sys.exit(0)


def _find_free_port(preferred: int) -> int:
    """从首选端口开始找一个本机空闲 TCP 端口，最多试 20 个；都不行就交 OS 分配"""
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    return 0


def _seed_bundled_corpus_if_empty(resource_dir: Path) -> None:
    """库为空且包内带了预置语料时，首次启动自动灌库（幂等，失败不封死入口）。"""
    corpus_dir = resource_dir / "desktop_seed"
    if not corpus_dir.is_dir():
        return

    # 延迟导入：确保此时 settings 已读到 exe 旁的 .env
    from app.db.vector_store import VectorStore
    from app.scripts.seed import run_seed

    if VectorStore().count() > 0:
        return

    line = "-" * 66
    print(line)
    print("  首次启动：正在灌入 3 篇随包项目文档（仅一次，需要联网调用 Embedding，文档较多约需几分钟）")
    print(line)
    try:
        result = asyncio.run(run_seed(corpus_dir, recursive=False))
    except Exception as exc:
        print("\n[警告] 预置语料灌入失败：")
        print(f"  原因：{exc}")
        print("  常见原因：API Key 填错、网络不通。修正后重启会自动重试。")
        choice = input("  输入 y 仍然启动（库为空，可稍后在网页里自行上传文档）；直接回车退出：")
        if choice.strip().lower() != "y":
            sys.exit(1)
    else:
        if result.failed:
            print(f"[提示] {len(result.failed)} 个文档灌入失败，其余文档已可正常问答。")
    print()


def main() -> None:
    _setup_console()

    # 路径锚定必须早于 settings 实例化，所以先拷 .env、再导入 app.config
    from app.config import APP_HOME, RESOURCE_DIR

    APP_HOME.mkdir(parents=True, exist_ok=True)
    env_path = _ensure_env_file(APP_HOME, RESOURCE_DIR)

    from app.config import settings
    _check_keys(settings, env_path)

    import uvicorn
    from main import app

    port = _find_free_port(int(settings.PORT))
    url = f"http://127.0.0.1:{port}/"

    _seed_bundled_corpus_if_empty(RESOURCE_DIR)

    _print_banner(url, APP_HOME)
    # 服务起来后再开浏览器：1.5 秒覆盖本地 localhost 绑定的常规耗时
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    try:
        # 直接传 app 对象：frozen 下字符串导入（"main:app"）与 reload/multiprocess 都不可用。
        # host 固定 127.0.0.1：桌面单机程序，不向局域网暴露端口。
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
    except KeyboardInterrupt:
        print("\n已退出，再会。")


if __name__ == "__main__":
    main()
