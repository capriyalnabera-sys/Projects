"""Replace the application icon.

Usage:  python scripts/set_app_icon.py path\\to\\my_icon.png
Writes assets/app_icon.png (window / taskbar) and assets/app_icon.ico (the .exe file icon).
Use a square PNG with a transparent background, ideally 256 x 256 or larger. Commit and push
the two files to have GitHub build a new .exe with the icon.
"""
import sys
from pathlib import Path

from PIL import Image

src = Image.open(sys.argv[1]).convert("RGBA")
src = src.crop(src.getbbox() or (0, 0, *src.size))
side = max(src.size)
square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
square.paste(src, ((side - src.size[0]) // 2, (side - src.size[1]) // 2))
icon = square.resize((256, 256), Image.LANCZOS)
out = Path(__file__).resolve().parents[1] / "assets"
out.mkdir(exist_ok=True)
icon.save(out / "app_icon.png")
icon.save(out / "app_icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("Icon updated:", out / "app_icon.png", "and", out / "app_icon.ico")
