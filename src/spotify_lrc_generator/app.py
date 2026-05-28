import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from spotify_lrc_generator.resources import resource_path
from spotify_lrc_generator.ui.main_window import MainWindow


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
    screen = app.primaryScreen()
    if screen is not None:
        screen_geometry = screen.availableGeometry()
        window_geometry = window.frameGeometry()
        window_geometry.moveCenter(screen_geometry.center())
        window.move(window_geometry.topLeft())
    window.show()

    return app.exec()
