"""把 assets/icon.png 转成 Windows 多尺寸 ICO（assets/icon.ico）。

build_exe.ps1 打包前会自动调用；手动替换图标后也可单独执行：
    python scripts/make_icon.py

要求：正方形 PNG，建议 1024x1024；脚本会一次性生成全部标准尺寸，
避免 Windows 在资源管理器/任务栏/高 DPI 缩放下插值放大导致模糊。
"""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets" / "icon.png"
DST = ROOT / "assets" / "icon.ico"
SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"未找到源图：{SRC}（请准备一张正方形 PNG）")

    icon = Image.open(SRC)
    if icon.mode != "RGBA":
        icon = icon.convert("RGBA")

    icon.save(DST, format="ICO", sizes=SIZES)
    print(f"已生成 {DST}，含 {len(SIZES)} 个尺寸：{[s[0] for s in SIZES]}")


if __name__ == "__main__":
    main()
