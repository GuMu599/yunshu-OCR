"""公式 → LaTeX. 离线方案: 渲染公式区域 → RapidOCR → unicode→LaTeX 符号映射.

texify 权重在本机不可用 (HF 不通且无缓存) 时, 这是主路径。
texify 模型日后可用时作为升级 (保持 ocr_formula_latex 接口不变)。

已知局限 (诚实记录, 写入 layout.json):
- OCR 会把 χ 读成 x、下标拍平 (μ0 -> muo)、分数结构丢失
- 返回的是"近似 LaTeX", 供 AI 理解, 不是严格排版级 LaTeX
"""

from __future__ import annotations

import re

from . import ocr as ocr_mod


class FormulaModel:
    """pix2tex (LaTeX-OCR) 公式模型 — 图像→LaTeX, 分数/下标/矩阵/希腊字母均正确.

    权重首次运行从 HuggingFace 下载 (LaTeX-OCR ~90M)。加载失败或无权重时
    available() 返回 False, 调用方回退 RapidOCR + 符号映射。
    CPU 上每条公式约 1-3s。

    注: texify 0.2.1 与新版 transformers 不兼容 (AttributeError to_dict),
    故用更活跃维护的 pix2tex。
    """

    _model = None
    _failed = False

    @classmethod
    def available(cls) -> bool:
        try:
            import pix2tex  # noqa: PLC0415
            return True
        except ImportError:
            return False

    @classmethod
    def _ensure(cls) -> bool:
        if cls._failed:
            return False
        if cls._model is None:
            try:
                from pix2tex.cli import LatexOCR  # noqa: PLC0415

                cls._model = LatexOCR()
            except Exception:
                cls._failed = True
                return False
        return True

    @classmethod
    def recognize(cls, png_bytes: bytes) -> str | None:
        """返回 pix2tex LaTeX; 失败返回 None (调用方回退 RapidOCR)."""
        if not cls._ensure():
            return None
        try:
            import io  # noqa: PLC0415

            from PIL import Image  # noqa: PLC0415

            img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
            latex = cls._model(img)
            return _clean_formula_latex(str(latex)) if latex else None
        except Exception:
            return None


def _clean_formula_latex(latex: str) -> str:
    """清理公式模型输出中的排版伪影.

    pix2tex 会在公式编号前输出大段 \\qquad/\\quad/~ 垫白, 以及数学间距命令。
    统一塌缩为单空格, 保持可读。
    """
    s = latex
    s = re.sub(r"(?:\\qquad|\\quad|\\;|\\,|~)+", " ", s)  # 间距命令/垫白 → 单空格
    s = re.sub(r"\s{2,}", " ", s)
    s = re.sub(r"\s+\.", ".", s)                # 空格紧贴句号
    s = re.sub(r"\\left\.\s*\\right\.", " ", s)  # 空 \left.\right. 壳
    s = s.strip()
    return s

SYMBOL_MAP = {
    "α": r"\alpha", "β": r"\beta", "γ": r"\gamma", "δ": r"\delta",
    "ε": r"\varepsilon", "ζ": r"\zeta", "η": r"\eta", "θ": r"\theta",
    "ϑ": r"\vartheta", "ι": r"\iota", "κ": r"\kappa", "λ": r"\lambda",
    "μ": r"\mu", "ν": r"\nu", "ξ": r"\xi", "π": r"\pi", "ρ": r"\rho",
    "σ": r"\sigma", "ς": r"\varsigma", "τ": r"\tau", "υ": r"\upsilon",
    "φ": r"\phi", "ϕ": r"\varphi", "χ": r"\chi", "ψ": r"\psi", "ω": r"\omega",
    "Γ": r"\Gamma", "Δ": r"\Delta", "Θ": r"\Theta", "Λ": r"\Lambda",
    "Ξ": r"\Xi", "Π": r"\Pi", "Σ": r"\Sigma", "Φ": r"\Phi",
    "Ψ": r"\Psi", "Ω": r"\Omega",
    "∞": r"\infty", "∂": r"\partial", "∇": r"\nabla", "√": r"\sqrt{}",
    "≤": r"\leq", "≥": r"\geq", "≠": r"\neq", "≈": r"\approx", "∝": r"\propto",
    "×": r"\times", "÷": r"\div", "±": r"\pm", "∓": r"\mp",
    "→": r"\rightarrow", "←": r"\leftarrow", "↔": r"\leftrightarrow",
    "⇒": r"\Rightarrow", "⇔": r"\Leftrightarrow",
    "∈": r"\in", "∉": r"\notin", "⊂": r"\subset", "⊃": r"\supset",
    "⊆": r"\subseteq", "∀": r"\forall", "∃": r"\exists", "∅": r"\emptyset",
    "∫": r"\int", "∬": r"\iint", "∑": r"\sum", "∏": r"\prod",
    "⋅": r"\cdot", "·": r"\cdot", "∙": r"\cdot",
    "⟨": r"\langle", "⟩": r"\rangle", "‖": r"\|",
    "−": r"-", "–": r"-", "—": r"-", "…": r"\dots", "⋯": r"\cdots",
    "∴": r"\therefore", "∵": r"\because",
    "½": r"\frac{1}{2}", "¼": r"\frac{1}{4}", "¾": r"\frac{3}{4}",
}


def to_latex(text: str) -> str:
    """OCR 公式文本 → 近似 LaTeX: 符号映射 + 常见指数恢复."""
    s = text.strip()
    for ch, latex in SYMBOL_MAP.items():
        s = s.replace(ch, latex)
    # 科学计数法: 10-7 -> 10^{-7}
    s = re.sub(r"\b10-(\d+)\b", r"10^{-\1}", s)
    # 常见单位上标: cm-1 / Hm-1 / m-2 -> cm^{-1} 等
    s = re.sub(r"\b([A-Za-z]{1,3})([mn])-(\d+)\b", r"\1\2^{-\3}", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def ocr_formula_latex(page, rect, dpi: int = 300, use_model: bool = True) -> tuple[str, float, str]:
    """识别一个公式区域 → (latex, 置信度, 引擎).

    公式模型 (pix2tex) 可用时优先 (直接输出 LaTeX, 分数/下标/矩阵正确);
    RapidOCR + 符号映射兜底。空识别返回 ("", 0.0, "")。
    """
    import fitz  # noqa: PLC0415

    rect_ = fitz.Rect(*rect) & page.rect
    if rect_.is_empty:
        return "", 0.0, ""
    scale = max(1.0, float(dpi) / 72.0)
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rect_, alpha=False)
    png = pix.tobytes("png")

    if use_model and FormulaModel.available():
        latex = FormulaModel.recognize(png)
        if latex and latex.strip():
            return latex.strip(), 0.99, "pix2tex"

    try:
        out = ocr_mod.ocr_image(png)
    except Exception:
        return "", 0.0, ""
    if not out:
        return "", 0.0, ""
    text = " ".join(t for t, _ in out if t)
    conf = sum(s for _, s in out) / len(out)
    return to_latex(text), round(float(conf), 3), "rapidocr"


_MATH_HINTS = set("=+−×÷μμπΣ∫∂√≤≥≠±→∞θλσφψαβγδΩΓΔ∇⟨⟩^_²³¹")
# 结构性数学 LaTeX 命令 (pix2tex 输出全是命令, 不能只看字面符号).
# 不含 mathrm/mathbf/vec: 它们也出现在纯散文输出里, 会误判.
_MATH_CMDS = re.compile(
    r"\\(frac|int|sum|prod|sqrt|cdot|times|pm|mp|leq|geq|neq|approx|"
    r"mu|alpha|beta|gamma|delta|lambda|theta|sigma|pi|phi|psi|omega|epsilon|"
    r"partial|nabla|infty|left|right|begin|end|"
    r"rightarrow|leftarrow|langle|rangle)"
)


def is_real_formula(latex: str) -> bool:
    """假公式守卫: 无任何数学线索 → 不是真公式 (降为正文).

    兼容两种输出: pix2tex 的 LaTeX 命令 (含 \\frac/\\mu/\\int 等) 与
    RapidOCR 的 Unicode 数学符号。用于过滤 YOLO 把标题/短句误判为 formula。
    """
    if not latex:
        return False
    # 超长结果 / 超大数组 → 不是单条公式 (框式文本误判, 如目录框)
    if len(latex) > 300:
        return False
    m = re.search(r"\\begin\{array\}\{([^}]*)\}", latex)
    if m and len(m.group(1)) > 12:
        return False
    if _MATH_CMDS.search(latex):
        return True
    return any(c in latex for c in _MATH_HINTS)


def looks_like_caption(text: str) -> bool:
    """YOLO 把图注误判为 formula 时, 用原生文字恢复而非 OCR 糟蹋."""
    t = text.strip()
    return bool(re.match(r"^(Fig\.?\s|Figure\s|Table\s|Tab\.?\s|Scheme\s|图\s*\d|表\s*\d)", t, re.IGNORECASE))


def find_equation_gaps(page, excluded_rects: list[list[float]], max_gaps: int = 8) -> list[list[float]]:
    """找文字块之间的空隙带 (有渲染内容但文字层不可见的区域 → 可能是显示公式).

    老式 LaTeX 排版的 PDF 数学用 Type3 字形, 文字层不可见, 只能视觉恢复。
    """
    import fitz  # noqa: PLC0415

    blocks = [b for b in page.get_text("blocks") if b[4].strip()]
    blocks.sort(key=lambda b: (b[1], b[0]))
    gaps: list[list[float]] = []
    excluded = [fitz.Rect(*r) for r in excluded_rects]
    for i in range(len(blocks) - 1):
        b0, b1 = blocks[i], blocks[i + 1]
        vgap = b1[1] - b0[3]
        if vgap < 12 or vgap > 120:
            continue
        x0 = max(b0[0], b1[0])
        x1 = min(b0[2], b1[2])
        if x1 - x0 < 60:
            continue
        rect = fitz.Rect(x0, b0[3], x1, b1[1])
        if any(not (rect & e).is_empty and (rect & e).get_area() > rect.get_area() * 0.5 for e in excluded):
            continue
        gaps.append([rect.x0, rect.y0, rect.x1, rect.y1])
        if len(gaps) >= max_gaps:
            break
    return gaps


def split_ink_lines(page, rect, dpi: int = 100, merge_gap: int = 6) -> list[list[float]]:
    """把空隙区域按墨迹行拆成独立公式行矩形.

    空隙带可能含多条堆叠的显示公式; 整体 OCR 会把它们合并成一条。
    行投影拆分后每条公式单独 OCR, 相邻近的行 (同一公式的多行) 合并。
    """
    import fitz  # noqa: PLC0415

    rect = fitz.Rect(*rect) & page.rect
    if rect.is_empty:
        return []
    pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), clip=rect, colorspace=fitz.csGRAY)
    w, h = pix.width, pix.height
    samples = pix.samples
    thr = max(1, int(w * 0.01))

    row_dark = [sum(1 for b in samples[y * w:(y + 1) * w] if b < 128) for y in range(h)]
    bands: list[tuple[int, int]] = []
    inb = False
    start = 0
    for y, d in enumerate(row_dark):
        if d > thr and not inb:
            start, inb = y, True
        elif d <= thr and inb:
            inb = False
            if y - start >= 2:
                bands.append((start, y))
    if inb:
        bands.append((start, h))

    merged: list[tuple[int, int]] = []
    for b in bands:
        if merged and b[0] - merged[-1][1] < merge_gap:
            merged[-1] = (merged[-1][0], b[1])
        else:
            merged.append(b)

    out: list[list[float]] = []
    scale_x = rect.width / w
    scale_y = rect.height / h
    for y0, y1 in merged:
        xs = [x for x in range(w) if any(samples[row * w + x] < 128 for row in range(y0, y1))]
        if not xs:
            continue
        pad = max(2, int(0.02 * w))
        out.append([
            rect.x0 + max(0, min(xs) - pad) * scale_x,
            rect.y0 + y0 * scale_y,
            rect.x0 + min(w, max(xs) + pad) * scale_x,
            rect.y0 + y1 * scale_y,
        ])
    return out


def has_ink(page, rect, dpi: int = 72, ratio: float = 0.001) -> bool:
    """渲染区域灰度, 检查是否有墨迹 (dark 像素占比 > ratio)."""
    import fitz  # noqa: PLC0415

    rect = fitz.Rect(*rect) & page.rect
    if rect.is_empty:
        return False
    pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), clip=rect, colorspace=fitz.csGRAY)
    samples = pix.samples
    if not samples:
        return False
    dark = sum(1 for b in samples if b < 128)
    return dark / len(samples) > ratio


def looks_formula_text(raw_text: str) -> bool:
    """启发式: 原生文本块看起来像公式 (含数学符号 / 运算符密集)."""
    if not raw_text:
        return False
    mathish = set("αβγδθλμπσΣΩ∂∫√∞≤≥≠×±→=+")
    dense = sum(1 for c in raw_text if c in mathish)
    return dense >= 2
