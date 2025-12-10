#!/usr/bin/env python3
"""
Генератор иконок приложения для всех платформ.
Создаёт .ico (Windows), .icns (macOS) и .png (Linux).
"""

import sys
import os
from pathlib import Path

# Добавляем путь к app
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QPixmap, QPainter, QColor, QPen, QBrush, QImage
    from PyQt6.QtCore import Qt
except ImportError:
    print("PyQt6 не установлен. Установите: pip install PyQt6")
    sys.exit(1)


def create_app_icon(size: int = 256) -> QPixmap:
    """Создать иконку приложения программно."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))  # Прозрачный фон

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Цвет
    main_color = QColor(220, 220, 220)
    bg_color = QColor(30, 30, 35)

    # Круг фона
    painter.setBrush(QBrush(bg_color))
    painter.setPen(QPen(main_color, size * 0.03))
    margin = int(size * 0.06)
    painter.drawEllipse(margin, margin, size - margin * 2, size - margin * 2)

    # Микрофон (упрощённый)
    mic_color = main_color
    painter.setBrush(QBrush(mic_color))
    painter.setPen(Qt.PenStyle.NoPen)

    # Головка микрофона
    head_w = size * 0.25
    head_h = size * 0.35
    head_x = (size - head_w) / 2
    head_y = size * 0.2
    painter.drawRoundedRect(
        int(head_x), int(head_y),
        int(head_w), int(head_h),
        head_w / 2, head_w / 2
    )

    # Ножка микрофона
    pen = QPen(mic_color, size * 0.08)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    center_x = size / 2
    painter.drawLine(
        int(center_x), int(head_y + head_h),
        int(center_x), int(size * 0.72)
    )

    # Подставка
    painter.drawLine(
        int(center_x - size * 0.12), int(size * 0.72),
        int(center_x + size * 0.12), int(size * 0.72)
    )

    painter.end()
    return pixmap


def save_png(pixmap: QPixmap, path: Path, size: int = None):
    """Сохранить PNG файл."""
    if size and size != pixmap.width():
        pixmap = pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    pixmap.save(str(path), "PNG")
    print(f"  Создан: {path} ({pixmap.width()}x{pixmap.height()})")


def create_ico(pixmap: QPixmap, path: Path):
    """Создать .ico файл для Windows."""
    # ICO содержит несколько размеров
    sizes = [16, 24, 32, 48, 64, 128, 256]

    # Для простоты используем PIL если доступен
    try:
        from PIL import Image
        import io

        images = []
        for size in sizes:
            scaled = pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

            # Конвертируем QPixmap в PIL Image
            buffer = scaled.toImage()
            buffer = buffer.convertToFormat(QImage.Format.Format_RGBA8888)

            ptr = buffer.bits()
            ptr.setsize(buffer.sizeInBytes())

            img = Image.frombytes("RGBA", (buffer.width(), buffer.height()), bytes(ptr))
            images.append(img)

        # Сохраняем как ICO
        images[0].save(str(path), format='ICO', sizes=[(s, s) for s in sizes])
        print(f"  Создан: {path} (ICO с размерами {sizes})")
        return True

    except ImportError:
        print("  PIL не установлен, сохраняем как PNG вместо ICO")
        save_png(pixmap, path.with_suffix('.png'), 256)
        return False


def create_icns(pixmap: QPixmap, path: Path):
    """Создать .icns файл для macOS."""
    # ICNS требует специальный формат
    # Для простоты создаём PNG и конвертируем через iconutil если доступен

    import subprocess
    import tempfile

    # Размеры для iconset
    sizes = [16, 32, 64, 128, 256, 512, 1024]

    with tempfile.TemporaryDirectory() as tmpdir:
        iconset_dir = Path(tmpdir) / "app.iconset"
        iconset_dir.mkdir()

        for size in sizes:
            # Обычная версия
            scaled = pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            scaled.save(str(iconset_dir / f"icon_{size}x{size}.png"), "PNG")

            # @2x версия (Retina)
            if size <= 512:
                size2x = size * 2
                scaled2x = pixmap.scaled(size2x, size2x, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                scaled2x.save(str(iconset_dir / f"icon_{size}x{size}@2x.png"), "PNG")

        # Конвертируем через iconutil (только на macOS)
        try:
            subprocess.run(
                ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(path)],
                check=True, capture_output=True
            )
            print(f"  Создан: {path} (ICNS)")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            # iconutil недоступен (не macOS)
            print(f"  iconutil недоступен, сохраняем набор PNG")
            # Сохраняем PNG для последующей конвертации на Mac
            save_png(pixmap, path.with_suffix('.png'), 1024)
            return False


def main():
    # Инициализируем Qt
    app = QApplication(sys.argv)

    # Пути
    root_dir = Path(__file__).parent.parent
    icons_dir = root_dir / "assets" / "icons"
    icons_dir.mkdir(parents=True, exist_ok=True)

    print("=== Генерация иконок приложения ===")
    print(f"Папка: {icons_dir}")
    print()

    # Создаём основную иконку
    print("Создание базовой иконки...")
    pixmap = create_app_icon(1024)  # Максимальный размер

    # PNG для Linux
    print("\nPNG для Linux:")
    save_png(pixmap, icons_dir / "app.png", 256)
    save_png(pixmap, icons_dir / "app_512.png", 512)

    # ICO для Windows
    print("\nICO для Windows:")
    create_ico(pixmap, icons_dir / "app.ico")

    # ICNS для macOS
    print("\nICNS для macOS:")
    create_icns(pixmap, icons_dir / "app.icns")

    print("\n=== Готово ===")


if __name__ == "__main__":
    main()







