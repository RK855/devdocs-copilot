"""
DevDocs Copilot —— 桌面版启动器（PyInstaller 打包入口）

运行形态：本地 HTTP 服务 + 浏览器界面（不是传统窗口程序）。
双击 DevDocsCopilot.exe 后的流程：
  1. 首次启动在 exe 旁生成 .env（从包内模板拷贝），不做任何弹窗或记事本引导；
  2. 直接启动本地服务并自动打开默认浏览器——模型配置全部在网页里完成：
     没配置过模型时，前端会自动弹出「首次使用」弹窗（预填两个免费模型，填 Key 即可）；
  3. 向量库为空且硅基流动 Key 可用时，自动灌入随包预置语料（仅首次，之后重启秒开）。
关闭控制台窗口（或 Ctrl+C）即停止服务。

开发态也可用 ``python run_desktop.py`` 调试这套桌面启动流程。
注意：本模块顶部只能导入标准库——app.config 的 settings 在导入时即实例化，
而 .env 就位必须早于它，所以所有 app.* 导入都延迟到函数内部。
"""
import asyncio
import os
import shutil
import socket
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
    print("  首次使用：网页里会自动弹出模型配置，填一个免费模型的 Key 即可")
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



def _find_free_port(preferred: int) -> int:
    """从首选端口开始找一个本机空闲 TCP 端口，最多试 100 个；找不到返回 0"""
    for port in range(preferred, preferred + 100):
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
    from app.services import model_registry

    if not model_registry.embedding_ready():
        print("[提示] 尚未配置向量模型 Key（硅基流动），本次跳过预置语料灌入。")
        print("       请在网页弹窗里选择「硅基流动」预设填写 Key，或自行上传文档。")
        return

    if VectorStore().count() > 0:
        return

    line = "-" * 66
    print(line)
    print("  首次启动：正在灌入 3 篇随包项目文档（仅一次，需要联网调用 Embedding，文档较多约需几分钟）")
    print(line)
    try:
        result = asyncio.run(run_seed(corpus_dir, recursive=False))
    except Exception as exc:
        print("\n[警告] 预置语料灌入失败，服务仍会启动：")
        print(f"  原因：{exc}")
        print("  常见原因：Key 填错、网络不通。修正后重启会自动重试，也可直接在网页里上传文档。")
    else:
        if result.failed:
            print(f"[提示] {len(result.failed)} 个文档灌入失败，其余文档已可正常问答。")
    print()


def main() -> None:
    _setup_console()

    # 路径锚定必须早于 settings 实例化，所以先拷 .env、再导入 app.config
    from app.config import APP_HOME, RESOURCE_DIR

    APP_HOME.mkdir(parents=True, exist_ok=True)
    _ensure_env_file(APP_HOME, RESOURCE_DIR)

    from app.config import settings
    from app.services import model_registry

    # 界面里配置过的供应商 Key 优先于 .env：用户不需要再手改配置文件
    model_registry.apply_provider_keys()

    import uvicorn
    from main import app

    port = _find_free_port(int(settings.PORT))
    if port == 0:
        # 交 OS 分配随机端口的话，横幅与自动打开的浏览器拿不到真实端口，服务等于不可用
        print(f"[错误] 端口 {settings.PORT} 起连续 100 个端口都被占用，无法启动服务。")
        print("       请释放端口，或在 .env 中把 PORT 改为其他值后重试。")
        sys.exit(1)
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
