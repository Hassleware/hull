"""Build Hull.exe (one file, no console) with PyInstaller: python scripts/build_exe.py → dist/Hull.exe
Needs: pip install pyinstaller. Hull.exe keeps hull.toml and data/ next to itself, and writes the default hull.toml
there on its first run."""
import subprocess, sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

hull = Path(__file__).resolve().parent.parent
build = hull / "build"
build.mkdir(exist_ok=True)

# the hull icon, as the .ico Windows shows for the exe
app = QGuiApplication(sys.argv[:1])
sizes = []
for n in (16, 32, 48, 256):
    img = QImage(n, n, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    QSvgRenderer(str(hull / "hull" / "assets" / "hull-icon.svg")).render(p)
    p.end()
    img.save(str(build / f"icon-{n}.png"))
    sizes.append(build / f"icon-{n}.png")
from PIL import Image  # noqa: E402 (Pillow is one of Hull's own dependencies)
Image.open(sizes[-1]).save(build / "hull.ico", sizes=[(n, n) for n in (16, 32, 48, 256)])

sep = ";" if sys.platform == "win32" else ":"
subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed", "--name", "Hull",
                "--icon", str(build / "hull.ico"),
                "--add-data", f"{hull / 'hull' / 'assets'}{sep}hull/assets",
                "--add-data", f"{hull / 'hull.toml'}{sep}.",
                "--distpath", str(hull / "dist"), "--workpath", str(build / "pyinstaller"), "--specpath", str(build),
                str(hull / "scripts" / "hull_exe.py")], check=True, cwd=hull)
print("built", hull / "dist" / "Hull.exe")
