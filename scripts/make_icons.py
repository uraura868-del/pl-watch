"""ホーム画面用アイコンの生成（Pillow）。python scripts/make_icons.py で assets/icons/ に書き出す"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "icons"
OUT.mkdir(parents=True, exist_ok=True)

BG_TOP = (26, 13, 18)
BG_BOTTOM = (13, 18, 32)
RED = (226, 35, 26)
WHITE = (243, 244, 248)


def font(size: int):
    for name in ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        for base in (Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype/dejavu")):
            p = base / name
            if p.exists():
                return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def draw_icon(size: int, rounded: bool, pad_ratio: float) -> Image.Image:
    s = size * 4  # 高解像度で描いて縮小
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    # 背景（上から下へのグラデーション）
    bg = Image.new("RGBA", (s, s))
    bd = ImageDraw.Draw(bg)
    for y in range(s):
        t = y / (s - 1)
        c = tuple(int(BG_TOP[i] * (1 - t) + BG_BOTTOM[i] * t) for i in range(3)) + (255,)
        bd.line([(0, y), (s, y)], fill=c)
    mask = Image.new("L", (s, s), 0)
    md = ImageDraw.Draw(mask)
    if rounded:
        md.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=255)
    else:
        md.rectangle([0, 0, s - 1, s - 1], fill=255)
    img.paste(bg, (0, 0), mask)

    d = ImageDraw.Draw(img)
    # ピッチの薄い線（上半分にゴールエリア風の枠）
    pad = int(s * pad_ratio)
    line = (255, 255, 255, 28)
    d.rectangle([pad, pad, s - pad, s - pad], outline=line, width=int(s * 0.012))
    d.rectangle([int(s * 0.33), pad, int(s * 0.67), int(s * 0.27)], outline=line, width=int(s * 0.012))

    # "PL" の文字と赤いバー
    f = font(int(s * 0.46))
    text = "PL"
    bbox = d.textbbox((0, 0), text, font=f)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx, ty = (s - tw) / 2 - bbox[0], s * 0.50 - th / 2 - bbox[1] - s * 0.06
    d.text((tx + s * 0.012, ty + s * 0.018), text, font=f, fill=(0, 0, 0, 110))  # 影
    d.text((tx, ty), text, font=f, fill=WHITE + (255,))
    bar_w, bar_h = s * 0.42, s * 0.055
    bx, by = (s - bar_w) / 2, s * 0.50 + th / 2 - s * 0.02
    d.rounded_rectangle([bx, by, bx + bar_w, by + bar_h], radius=int(bar_h / 2), fill=RED + (255,))
    # 右下に小さな「目を伏せた」印（ネタバレなしのしるし）: 赤い丸
    r = s * 0.045
    cx, cy = s * 0.80, s * 0.80
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=RED + (255,))
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    draw_icon(512, True, 0.10).save(OUT / "icon-512.png")
    draw_icon(192, True, 0.10).save(OUT / "icon-192.png")
    # maskable: 端が丸く切られても欠けないよう、余白を多めに
    m = draw_icon(512, False, 0.16)
    m.save(OUT / "icon-maskable-512.png")
    draw_icon(180, False, 0.10).convert("RGB").save(OUT / "apple-touch-icon.png")
    draw_icon(64, True, 0.10).save(OUT / "favicon-64.png")
    print("icons written to", OUT)


if __name__ == "__main__":
    main()
