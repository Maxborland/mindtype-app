"""
Генерация System-7 баннеров для Inno Setup (wizard_large.bmp, wizard_small.bmp).
Запуск: py -3.13 installer/make_wizard_images.py
Стиль: чёрно-белый, полосатый title bar, острые рамки/бевели, шрифт Chicago.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT = ROOT / "app" / "ui" / "fonts" / "Chicago.ttf"
OUT = ROOT / "assets" / "icons"

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GREY = (128, 128, 128)


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT), size)


def text_w(d: ImageDraw.ImageDraw, s: str, f) -> int:
    box = d.textbbox((0, 0), s, font=f)
    return box[2] - box[0]


def stripes(d: ImageDraw.ImageDraw, x0: int, y0: int, x1: int, y1: int) -> None:
    """Горизонтальные полоски System-7 (через строку)."""
    y = y0
    while y < y1:
        d.line([(x0, y), (x1, y)], fill=BLACK, width=1)
        y += 2


def bevel(d: ImageDraw.ImageDraw, x0: int, y0: int, x1: int, y1: int) -> None:
    """3D-бевель (свет сверху-слева, тень снизу-справа) в System-7."""
    d.rectangle([x0, y0, x1, y1], fill=WHITE, outline=BLACK, width=1)
    d.line([(x0 + 1, y0 + 1), (x1 - 1, y0 + 1)], fill=WHITE, width=1)
    d.line([(x1 - 1, y0 + 1), (x1 - 1, y1 - 1)], fill=GREY, width=1)
    d.line([(x0 + 1, y1 - 1), (x1 - 1, y1 - 1)], fill=GREY, width=1)


def make_large(path: Path) -> None:
    W, H = 164, 314
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)

    # Рамка окна System-7 (2px)
    d.rectangle([0, 0, W - 1, H - 1], outline=BLACK, width=2)

    # Полосатый title bar
    bar_y0, bar_y1 = 2, 28
    stripes(d, 3, bar_y0 + 3, W - 3, bar_y1 - 1)
    # close box слева
    d.rectangle([8, 9, 18, 19], fill=WHITE, outline=BLACK, width=1)
    # заголовок в белом лозенге
    tf = font(14)
    title = "MindType"
    tw = text_w(d, title, tf)
    lx0 = (W - tw) // 2 - 8
    lx1 = (W + tw) // 2 + 8
    d.rectangle([lx0, bar_y0 + 2, lx1, bar_y1 - 2], fill=WHITE)
    d.text(((W - tw) // 2, 7), title, font=tf, fill=BLACK)
    d.line([(2, bar_y1), (W - 3, bar_y1)], fill=BLACK, width=1)

    # Центральный логотип — бевель-бокс с большой «M»
    box = 92
    bx0 = (W - box) // 2
    by0 = 70
    bevel(d, bx0, by0, bx0 + box, by0 + box)
    mf = font(64)
    mw = text_w(d, "M", mf)
    d.text(((W - mw) // 2, by0 + 10), "M", font=mf, fill=BLACK)

    # Подпись
    cf = font(13)
    cap = "Speech-to-Text"
    cw = text_w(d, cap, cf)
    d.text(((W - cw) // 2, by0 + box + 18), cap, font=cf, fill=BLACK)
    sf = font(11)
    cap2 = "offline + AI"
    cw2 = text_w(d, cap2, sf)
    d.text(((W - cw2) // 2, by0 + box + 40), cap2, font=sf, fill=GREY)

    img.save(path, "BMP")
    print("saved", path, img.size)


def make_small(path: Path) -> None:
    W, H = 55, 58
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    # мини-окно: рамка + полосатый заголовок + «M»
    d.rectangle([2, 2, W - 3, H - 3], outline=BLACK, width=1)
    stripes(d, 4, 5, W - 4, 13)
    d.rectangle([5, 6, 11, 12], fill=WHITE, outline=BLACK, width=1)  # close box
    d.line([(2, 15), (W - 3, 15)], fill=BLACK, width=1)
    mf = font(28)
    mw = text_w(d, "M", mf)
    d.text(((W - mw) // 2, 22), "M", font=mf, fill=BLACK)
    img.save(path, "BMP")
    print("saved", path, img.size)


if __name__ == "__main__":
    make_large(OUT / "wizard_large.bmp")
    make_small(OUT / "wizard_small.bmp")
