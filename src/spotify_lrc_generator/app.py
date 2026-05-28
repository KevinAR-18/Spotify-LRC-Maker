import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from spotify_lrc_generator.ui.main_window import MainWindow


def resource_path(relative_path: str) -> Path:
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base_path / relative_path


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Spotify LRC Maker")
    app.setOrganizationName("SpotifyLrcGenerator")

    icon_path = resource_path("icon.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow()
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.resize(1120, 720)
    window.show()

    return app.exec()
