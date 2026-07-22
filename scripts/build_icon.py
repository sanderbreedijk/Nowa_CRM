"""Create the Windows executable icon from the repository's vector app icon."""
from pathlib import Path

from PIL import Image
from PySide6.QtGui import QGuiApplication, QIcon


root = Path(__file__).parents[1]
source = root / "src" / "nowa_crm" / "assets" / "nowa_crm_app.svg"
output_dir = root / "build"
output_dir.mkdir(exist_ok=True)
png = output_dir / "nowa_crm_app.png"
ico = output_dir / "nowa_crm_app.ico"

app = QGuiApplication.instance() or QGuiApplication([])
pixmap = QIcon(str(source)).pixmap(256, 256)
if pixmap.isNull() or not pixmap.save(str(png), "PNG"):
    raise SystemExit("Het app-icoon kon niet worden gerenderd.")
with Image.open(png) as image:
    image.save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print(ico)

