"""Build the README six-panel Attention Is All You Need OCR preview.

The input PDF and pdf2md output are intentionally kept under tmp/ (ignored).
This script only writes the distributable preview image under docs/assets/.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import fitz
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "tmp/attention-is-all-you-need/attention-is-all-you-need.pdf"
MD = ROOT / "tmp/attention-is-all-you-need/ocr-utf8/attention-is-all-you-need.md"
OUT = ROOT / "docs/assets/attention-is-all-you-need-preview.png"

W, H = 760, 470
BG = "#f6f7f9"
INK = "#17202a"
MUTED = "#5b6573"
BLUE = "#2563eb"
RED = "#dc2626"


def font(name: str, size: int):
    candidates = [
        Path("C:/Windows/Fonts") / name,
        Path("C:/Windows/Fonts/arial.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


FONT = font("arial.ttf", 22)
SMALL = font("arial.ttf", 18)
MONO = font("consola.ttf", 17)
MONO_SMALL = font("consola.ttf", 15)


def fit_crop(page: fitz.Page, bbox: tuple[float, float, float, float], margin: float = 28) -> Image.Image:
    rect = fitz.Rect(*bbox)
    rect.x0 = max(0, rect.x0 - margin)
    rect.y0 = max(0, rect.y0 - margin)
    rect.x1 = min(page.rect.width, rect.x1 + margin)
    rect.y1 = min(page.rect.height, rect.y1 + margin)
    pix = page.get_pixmap(matrix=fitz.Matrix(2.8, 2.8), clip=rect, alpha=False)
    image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    image.thumbnail((W - 44, H - 95), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (W - 44, H - 95), "white")
    canvas.paste(image, ((canvas.width - image.width) // 2, (canvas.height - image.height) // 2))
    return canvas


def panel(title: str, subtitle: str, body: Image.Image, accent: str) -> Image.Image:
    out = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(out)
    draw.rounded_rectangle((0, 0, W - 1, H - 1), radius=16, outline="#d6dbe2", width=2, fill=BG)
    draw.rectangle((0, 0, 10, H), fill=accent)
    draw.text((28, 18), title, font=FONT, fill=INK)
    draw.text((28, 50), subtitle, font=SMALL, fill=MUTED)
    out.paste(body, (22, 88))
    return out


def paragraph(draw: ImageDraw.ImageDraw, text: str, y: int, width: int = 72) -> int:
    for line in textwrap.wrap(text, width=width):
        draw.text((18, y), line, font=SMALL, fill=INK)
        y += 24
    return y + 8


def rendered_figure_body(image_path: Path) -> Image.Image:
    out = Image.new("RGB", (W - 44, H - 95), "white")
    draw = ImageDraw.Draw(out)
    draw.text((18, 14), "Figure 1. The Transformer — model architecture", font=FONT, fill=INK)
    figure = Image.open(image_path).convert("RGB")
    figure.thumbnail((out.width - 36, 270), Image.Resampling.LANCZOS)
    x = (out.width - figure.width) // 2
    out.paste(figure, (x, 56))
    draw.text((18, out.height - 38), "The Transformer follows this overall architecture.", font=SMALL, fill=MUTED)
    return out


def rendered_formula_body() -> Image.Image:
    out = Image.new("RGB", (W - 44, H - 95), "white")
    draw = ImageDraw.Draw(out)
    draw.text((18, 14), "3.2.1 Scaled Dot-Product Attention", font=FONT, fill=INK)
    y = paragraph(draw, "In practice, we compute the attention function on a set of queries simultaneously, packed together into a matrix Q.", 58)
    draw.rounded_rectangle((18, y, out.width - 18, y + 112), radius=8, fill="#0f172a")
    draw.text((34, y + 14), "LaTeX source", font=SMALL, fill="#93c5fd")
    draw.text((34, y + 48), r"\mathrm{Attention}(Q,K,V)=\mathrm{softmax}(\frac{Q K^{T}}{\sqrt{d_{k}}})V", font=MONO_SMALL, fill="#f8fafc")
    draw.text((18, y + 134), "(1)", font=SMALL, fill=MUTED)
    return out


def rendered_table_body() -> Image.Image:
    out = Image.new("RGB", (W - 44, H - 95), "white")
    draw = ImageDraw.Draw(out)
    draw.text((18, 14), "Self-attention complexity comparison", font=FONT, fill=INK)
    x0, y0 = 18, 60
    widths = [260, 150, 110, 135]
    rows = [
        ["Layer", "Complexity", "Sequential", "Path length"],
        ["Recurrent", "O(n · d²)", "O(n)", "O(n)"],
        ["Convolutional", "O(k · n · d²)", "O(1)", "O(logₖ(n))"],
        ["Self-Attention (restricted)", "O(r · n · d)", "O(1)", "O(n/r)"],
    ]
    row_h = 52
    for ri, row in enumerate(rows):
        x = x0
        fill = "#e8eef8" if ri == 0 else ("#f8fafc" if ri % 2 else "white")
        for ci, cell in enumerate(row):
            draw.rectangle((x, y0 + ri * row_h, x + widths[ci], y0 + (ri + 1) * row_h), fill=fill, outline="#cbd5e1")
            draw.text((x + 10, y0 + ri * row_h + 16), cell, font=SMALL if ri == 0 else MONO_SMALL, fill=INK)
            x += widths[ci]
    draw.text((18, y0 + len(rows) * row_h + 18), "<!-- table: full structure in layout.json -->", font=MONO_SMALL, fill=MUTED)
    return out


def main() -> None:
    if not PDF.exists() or not MD.exists():
        raise SystemExit("Run pdf2md first; expected PDF and Markdown under tmp/attention-is-all-you-need/")
    doc = fitz.open(PDF)
    panels: list[Image.Image] = []
    cases = [
        (
            "Figure · page 3",
            "Transformer model architecture · bbox from layout.json",
            3,
            (197.19, 72.49, 412.84, 394.01),
            "figure",
        ),
        (
            "Formula · page 4",
            "Scaled dot-product attention · LaTeX recovered as a formula block",
            4,
            (80, 400, 520, 550),
            "formula",
        ),
        (
            "Table · page 6",
            "Self-attention complexity comparison · Markdown table",
            6,
            (108, 104, 505, 205),
            "table",
        ),
    ]

    figure_path = ROOT / "tmp/attention-is-all-you-need/ocr-utf8/images/page003_figure_001.png"
    for title, subtitle, page_no, bbox, kind in cases:
        left = fit_crop(doc[page_no - 1], bbox)
        right = {
            "figure": lambda: rendered_figure_body(figure_path),
            "formula": rendered_formula_body,
            "table": rendered_table_body,
        }[kind]()
        panels.append(panel(title + " · Original PDF", subtitle, left, RED))
        panels.append(panel(title + " · yunshu-OCR Markdown", "Same page context · generated offline", right, BLUE))

    sheet = Image.new("RGB", (W * 2, H * 3), "white")
    for i, image in enumerate(panels):
        sheet.paste(image, ((i % 2) * W, (i // 2) * H))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(OUT, format="PNG", optimize=True)
    print(f"wrote {OUT} ({sheet.width}x{sheet.height})")


if __name__ == "__main__":
    main()
