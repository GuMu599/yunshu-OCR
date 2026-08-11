"""公式 → LaTeX. 离线方案: 渲染公式区域 → RapidOCR → unicode→LaTeX 符号映射.

texify 权重在本机不可用 (HF 不通且无缓存) 时, 这是主路径。
texify 模型日后可用时作为升级 (保持 ocr_formula_latex 接口不变)。

已知局限 (诚实记录, 写入 layout.json):
- OCR 会把 χ 读成 x、下标拍平 (μ0 -> muo)、分数结构丢失
- 返回的是"近似 LaTeX", 供 AI 理解, 不是严格排版级 LaTeX
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import unicodedata
from pathlib import Path
from types import SimpleNamespace

from . import ocr as ocr_mod
from . import models as model_assets


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
    _error: str | None = None

    _manifest = model_assets.load_manifest()
    _CHECKPOINT_SHA256 = {
        "weights.pth": _manifest.by_name("pix2tex_weights").sha256,
        "image_resizer.pth": _manifest.by_name("pix2tex_resizer").sha256,
    }

    @classmethod
    def checkpoint_dir(cls) -> Path:
        return model_assets.model_path("pix2tex_weights").parent

    @classmethod
    def arguments(cls) -> dict[str, object]:
        spec = importlib.util.find_spec("pix2tex")
        if spec is None or not spec.submodule_search_locations:
            raise RuntimeError("model_missing:pix2tex-package")
        package = Path(next(iter(spec.submodule_search_locations))).resolve()
        return {
            "config": str(package / "model" / "settings" / "config.yaml"),
            "checkpoint": str(model_assets.model_path("pix2tex_weights")),
            "no_cuda": True,
            "no_resize": False,
        }

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @classmethod
    def checkpoint_status(cls, checkpoint_dir: str | os.PathLike | None = None) -> dict:
        """Verify all pickle-backed pix2tex files before importing its loader."""
        if checkpoint_dir is None:
            directory = cls.checkpoint_dir()
        else:
            directory = Path(checkpoint_dir).expanduser().resolve()

        actual: dict[str, str] = {}
        for name, expected in cls._CHECKPOINT_SHA256.items():
            path = directory / name
            if not path.is_file():
                return {
                    "available": False, "error": "model_missing:pix2tex",
                    "path": str(path),
                }
            digest = cls._file_sha256(path)
            actual[name] = digest
            if digest != expected:
                return {
                    "available": False, "error": "model_integrity:pix2tex",
                    "path": str(path), "expected_sha256": expected, "sha256": digest,
                }
        return {
            "available": True, "verified": True, "path": str(directory),
            "sha256": actual,
        }

    @classmethod
    def available(cls) -> bool:
        status = cls.checkpoint_status()
        cls._error = status.get("error")
        return bool(status.get("available"))

    @classmethod
    def _ensure(cls) -> bool:
        if cls._failed:
            return False
        if cls._model is None:
            status = cls.checkpoint_status()
            if not status.get("available"):
                cls._failed = True
                cls._error = status.get("error")
                return False
            try:
                # Disable update checks and force PyTorch's restricted state-dict
                # loader before pix2tex imports torch/albumentations.
                os.environ["NO_ALBUMENTATIONS_UPDATE"] = "1"
                os.environ["TORCH_FORCE_WEIGHTS_ONLY_LOAD"] = "1"
                from pix2tex.cli import LatexOCR  # noqa: PLC0415

                cls._model = LatexOCR(SimpleNamespace(**cls.arguments()))
            except Exception as exc:
                cls._failed = True
                cls._error = f"model_load:pix2tex:{type(exc).__name__}"
                return False
        return True

    @classmethod
    def recognize(cls, png_bytes: bytes) -> str | None:
        """返回 pix2tex LaTeX; 失败返回 None (调用方回退 RapidOCR)."""
        if not cls._ensure():
            return None
        try:
            import io  # noqa: PLC0415
            import random  # noqa: PLC0415

            import numpy as np  # noqa: PLC0415
            import torch  # noqa: PLC0415
            from PIL import Image  # noqa: PLC0415

            img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
            # The pix2tex preprocessing stack samples random transforms during
            # inference. Seed every participating RNG for this call and then
            # restore the caller's state, making identical crops reproducible.
            python_state = random.getstate()
            numpy_state = np.random.get_state()
            try:
                random.seed(0)
                np.random.seed(0)
                with torch.random.fork_rng(devices=[]):
                    torch.manual_seed(0)
                    latex = cls._model(img)
            finally:
                random.setstate(python_state)
                np.random.set_state(numpy_state)
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


_NATIVE_GREEK = {
    "α": r"\alpha", "β": r"\beta", "γ": r"\gamma", "δ": r"\delta",
    "ε": r"\varepsilon", "θ": r"\theta", "λ": r"\lambda", "μ": r"\mu",
    "ρ": r"\rho", "σ": r"\sigma", "φ": r"\phi", "ω": r"\omega",
    "Δ": r"\Delta", "∑": r"\sum", "π": r"\pi",
}


def native_formula_latex(raw_text: str) -> str | None:
    """Recover conservative LaTeX from a born-digital equation text layer.

    Some journal PDFs contain a reliable text layer for equations while the
    visual glyphs are split across lines (bars, sum bounds, and subscripts).
    In that case pix2tex can hallucinate the glyph structure.  This helper is
    deliberately narrow: it only activates for equations containing the
    characteristic Unicode math glyphs and leaves all other regions to the
    existing image recognizer.
    """
    text = unicodedata.normalize("NFKC", str(raw_text or ""))
    text = text.replace("\\n", " ").replace("珔", "@BAR@")
    text = re.sub(r"\s+", " ", text).strip()
    if "=" not in text or "Δ" not in text:
        return None
    text = text.replace("，", ",").replace("－", "-").replace("−", "-")

    # Protect the overbar glyph and the X it belongs to before indexing the
    # ordinary X tokens below.
    text = re.sub(r"@BAR@\s*X\s*([A-Za-z])\s*-\s*([0-9a-z]+)", r"@BARSUB@:\1-\2", text)
    text = re.sub(r"@BAR@\s*X\s*([A-Za-z])", r"@BARSUB@:\1", text)

    # Sum bounds and coefficient arrive as one stacked text run in PyMuPDF.
    text = re.sub(
        r"∑\s*k\s*j\s*=\s*1\s*θ\s*([0-9A-Za-z]+)\s*,\s*([A-Za-z])",
        r"\\sum_{j=1}^{k}\\theta_{\1,\2}", text,
    )

    # Indexed X tokens: X1,t-1, X2,j, Xt-1, etc.
    text = re.sub(
        r"X\s*([0-9A-Za-z]+)\s*,\s*([A-Za-z])\s*-\s*([0-9a-z]+)",
        r"X_{\1,\2-\3}", text,
    )
    text = re.sub(
        r"X\s*([0-9A-Za-z]+)\s*,\s*([A-Za-z])",
        r"X_{\1,\2}", text,
    )
    text = re.sub(
        r"X\s*([A-Za-z])\s*-\s*([0-9a-z]+)",
        r"X_{\1-\2}", text,
    )
    text = re.sub(r"X\s*([A-Za-z])", r"X_{\1}", text)

    # Overbar glyphs are emitted separately from their X and subscript.
    text = re.sub(
        r"@BARSUB@:([A-Za-z])(?:-([0-9a-z]+))?",
        lambda m: rf"\bar{{X}}_{{{m.group(1)}{('-' + m.group(2)) if m.group(2) else ''}}}",
        text,
    )
    text = text.replace("@BAR@", r"\bar{X}")

    text = re.sub(
        r"([cd])([0-9N])\s*(sin|cos)\s*2πkt\s*\(\s*\)\s*T",
        lambda m: rf"{m.group(1)}_{{{m.group(2)}}}\{m.group(3)}\left(\frac{{2\pi k t}}{{T}}\right)",
        text,
    )

    for symbol, latex in _NATIVE_GREEK.items():
        text = text.replace(symbol, latex)
    greek_commands = r"(?:alpha|beta|gamma|delta|varepsilon|theta|lambda|mu|rho|sigma|phi|omega)"
    text = re.sub(
        rf"(\\{greek_commands})\s*([0-9A-Za-z])\s*,\s*([A-Za-z])",
        r"\1_{\2,\3}", text,
    )
    text = re.sub(rf"(\\{greek_commands})\s*([0-9A-Za-z])", r"\1_{\2}", text)
    text = re.sub(r"\s*([=+\-(),])\s*", r" \1 ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    text = re.sub(r"\\(left|right)\s+([()])", r"\\\1\2", text)
    text = re.sub(r"(\\left\()\s+", r"\1", text)
    text = re.sub(r"\s+(\\right\))", r"\1", text)
    text = re.sub(r"(?:\s*[,;])*(?:\s*\(\s*\))+\s*$", "", text).strip()
    for _ in range(2):
        text = re.sub(
            r"\{([^{}]*)\}",
            lambda m: "{" + re.sub(r"\s*([,=-])\s*", r"\1", m.group(1)) + "}",
            text,
        )
    return text if is_real_formula(text) else None


def ocr_formula_latex(
    page,
    rect,
    dpi: int = 300,
    use_model: bool = True,
) -> tuple[str, float | None, str]:
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
            # pix2tex does not expose a calibrated sequence confidence.  A
            # fabricated 0.99 would mislead report consumers.
            return latex.strip(), None, "pix2tex"

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
    # pix2tex occasionally emits a mathematically-looking prefix and then
    # truncates the final group (for example ``\\mu_{2 ,``).  Such output is
    # not safe to publish as LaTeX; callers will retain the source crop as an
    # image fallback instead.
    if latex.count("{") != latex.count("}"):
        return False
    if len(re.findall(r"\\begin\s*\{", latex)) != len(re.findall(r"\\end\s*\{", latex)):
        return False
    if re.search(r"(?:[_^])\s*\{[^{}]*$", latex):
        return False
    m = re.search(r"\\begin\{array\}\{([^}]*)\}", latex)
    if m and len(m.group(1)) > 12:
        return False
    if m and not re.search(
        r"[=+<>]|\\(?:frac|int|sum|prod|sqrt|partial|nabla)\b",
        latex,
    ):
        return False
    if _MATH_CMDS.search(latex):
        return True
    return any(c in latex for c in _MATH_HINTS)


_CAPTION_PREFIX = re.compile(
    r"^\s*(?:(fig(?:ure)?|scheme)|(table|tab)|([图圖])|([表]))\.??"
    r"\s*[^0-9A-Za-z\u4e00-\u9fff]{0,4}\s*(\d+|[IVX]+)",
    re.IGNORECASE,
)


def normalize_caption_text(text: str) -> str:
    """Normalize Unicode and common PDF extraction noise around caption numbers."""
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    normalized = normalized.replace("\u00a0", " ").replace("\u200b", "")
    return re.sub(r"\s+", " ", normalized).strip()


def caption_kind(text: str) -> str | None:
    """Return ``figure``/``table`` for tolerant multilingual caption prefixes."""
    match = _CAPTION_PREFIX.match(normalize_caption_text(text))
    if not match:
        return None
    return "table" if match.group(2) or match.group(4) else "figure"


def looks_like_caption(text: str) -> bool:
    """Detect captions before a formula candidate reaches OCR or pix2tex."""
    return caption_kind(text) is not None


def is_formula_candidate(raw_text: str) -> bool:
    """Cheap semantic gate used before invoking an expensive formula recognizer."""
    text = normalize_caption_text(raw_text)
    if not text or looks_like_caption(text) or len(text) > 300:
        return False
    if re.fullmatch(
        r"(?i)(intensity|wavelength|frequency|binding energy|raman shift|"
        r"temperature|time|voltage|current|counts?)(?:\s*\([^)]{1,12}\))?",
        text,
    ):
        return False
    return bool(
        re.search(r"[=^_±×÷∑∫√<>]|\\(?:frac|sum|int|sqrt|begin|alpha|beta|mu)\b", text)
        or looks_formula_text(text)
    )


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


def split_ink_lines(
    page,
    rect,
    dpi: int = 100,
    merge_gap: int = 6,
    vertical_pad_points: float = 5.0,
) -> list[list[float]]:
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
    pad_y = max(0, int(round(vertical_pad_points / scale_y)))
    for y0, y1 in merged:
        xs = [x for x in range(w) if any(samples[row * w + x] < 128 for row in range(y0, y1))]
        if not xs:
            continue
        pad = max(2, int(0.02 * w))
        out.append([
            rect.x0 + max(0, min(xs) - pad) * scale_x,
            rect.y0 + max(0, y0 - pad_y) * scale_y,
            rect.x0 + min(w, max(xs) + pad) * scale_x,
            rect.y0 + min(h, y1 + pad_y) * scale_y,
        ])
    return out


def formula_region_parts(page, rect, raw_text: str) -> list[list[float]]:
    """Split a detector box only when it contains multiple displayed equations."""
    text = normalize_caption_text(raw_text)
    if looks_like_caption(text) or text.count("=") < 2:
        return [list(rect)]
    parts = split_ink_lines(page, rect, dpi=150)
    return parts if len(parts) >= 2 else [list(rect)]


_INLINE_EQUALITY = re.compile(
    r"(?<![A-Za-z0-9\u0370-\u03ff])"
    r"((?:\d+(?:\s*\.\s*\d+)?)?[A-Za-z\u0370-\u03ff]+"
    r"(?:\s*,\s*[A-Za-z0-9\u0370-\u03ff]+)?"
    r"(?:\s*[+\-−－*/·×]\s*[A-Za-z0-9\u0370-\u03ff]+)*"
    r"\s*=\s*"
    r"(?:\d+(?:\s*\.\s*\d+)?[A-Za-z\u0370-\u03ff]*|"
    r"[A-Za-z\u0370-\u03ff][A-Za-z0-9\u0370-\u03ff]*)"
    r"(?:\s*[+\-−－]\s*(?:\d+(?:\s*\.\s*\d+)?[A-Za-z\u0370-\u03ff]*|"
    r"[A-Za-z\u0370-\u03ff][A-Za-z0-9\u0370-\u03ff]*))?"
    r"(?:\s*(?:m\s*(?:/\s*s(?:²|\^?2)?|[●·⋅]\s*s\s*(?:[-−－]?\s*2|²))|"
    r"nm|cm|mm|mA|kV|mV|Hz))?)(?!\s*[/●·⋅])"
)

_INLINE_GREEK = {
    "α": r"\alpha", "β": r"\beta", "γ": r"\gamma", "δ": r"\delta",
    "ε": r"\varepsilon", "θ": r"\theta", "λ": r"\lambda", "μ": r"\mu",
    "π": r"\pi", "ρ": r"\rho", "σ": r"\sigma", "φ": r"\phi",
    "ω": r"\omega", "Δ": r"\Delta", "Σ": r"\Sigma",
}


def _inline_formula_latex(expression: str) -> str:
    value = unicodedata.normalize("NFKC", expression)
    value = re.sub(r"(?<=\d)\s*\.\s*(?=\d)", ".", value)
    value = value.replace("−", "-").replace("－", "-").replace("，", ",")
    value = re.sub(r"sin(?=[\u0370-\u03ff])", r"\\sin", value)
    value = re.sub(r"sin(?=[A-Za-z])", r"\\sin ", value)
    value = re.sub(r"cos(?=[\u0370-\u03ff])", r"\\cos", value)
    value = re.sub(r"cos(?=[A-Za-z])", r"\\cos ", value)
    indexed_greek = {"α", "β", "γ", "δ", "ε", "θ", "μ", "ρ", "σ", "φ", "ω"}
    for symbol, latex in _INLINE_GREEK.items():
        if symbol in indexed_greek:
            value = re.sub(
                re.escape(symbol) + r"([A-Za-z0-9])",
                lambda match, command=latex: rf"{command}_{{{match.group(1)}}}",
                value,
            )
        value = value.replace(symbol, latex)
    value = re.sub(r"\s*=\s*", " = ", value)
    unit_match = re.search(
        r"\s*(m\s*(?:/\s*s(?:\^?2)?|[●·⋅]\s*s\s*(?:-?\s*2))|"
        r"nm|cm|mm|mA|kV|mV|Hz)\s*$",
        value,
    )
    if unit_match:
        unit = re.sub(r"\s+", "", unit_match.group(1))
        if re.search(r"[●·⋅]", unit):
            rendered_unit = r"\,\mathrm{m}\cdot\mathrm{s}^{-2}"
        else:
            unit = re.sub(r"s2$", "s^2", unit)
            rendered_unit = rf"\,\mathrm{{{unit}}}"
        value = value[:unit_match.start()] + rendered_unit
    return re.sub(r"\s{2,}", " ", value).strip()


def format_inline_formulas(text: str) -> tuple[str, int]:
    """Wrap conservative native-text equalities in inline LaTeX delimiters."""
    raw = str(text)
    if raw.count("=") >= 2 and re.search(r"[\u0394\u2211]", raw):
        return raw, 0
    count = 0

    def replace(match: re.Match) -> str:
        nonlocal count
        count += 1
        return f"${_inline_formula_latex(match.group(1))}$"

    return _INLINE_EQUALITY.sub(replace, raw), count


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
