"""pdf2md 命令行入口.

用法:
    python -m pdf2md.cli <input.pdf> [--output DIR] [--lang en|zh]
        [--drop-margins] [--no-ocr] [--dpi 220] [--max-pages N]
        [--formula-dpi 300] [--image-dpi 200]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pdf2md.pipeline import convert_pdf  # noqa: E402


def _print_report(report: dict) -> None:
    s = report["stats"]
    print("\n" + "=" * 60)
    print(f"转换完成: {report['elapsed_s']}s")
    print(f"输出: {report['markdown_path']}")
    print(f"元数据: 标题={report['meta'].get('title','')[:50]!r} "
          f"年份={report['meta'].get('year') or '-'} 作者={report['meta'].get('authors','')[:40]!r}")
    prof = report.get("pdf_profile")
    if prof:
        print(f"PDF 预检: 模式={prof.get('mode')} 瓶颈={prof.get('bottleneck')} "
              f"(文字页比 {prof.get('text_pages_ratio')} 图比 {prof.get('image_pages_ratio')} "
              f"公式密度 {prof.get('formula_density')})")
    print(f"元素统计: 文本块={s['text_regions']} 图片={s['images']} 表格MD={s['tables']} "
          f"视觉降级={s.get('visual_fallbacks', s['table_images'])} 公式={s['formulas']} "
          f"(不确定={s['formula_uncertain']} 降级图={s['formula_fallback_images']}) OCR页={s['ocr_pages']}")
    if not report["formula_detected"]:
        print("警告: YOLO 未检测到任何 formula 区域 — 公式覆盖率存疑, 请核对 layout.json")
    print("-" * 60)
    print(f"{'页':>3} {'原生':>7} {'MD':>7} {'比例':>6}  状态")
    for c in report["coverage"]:
        mark = "OK" if c["flag"] == "ok" else "!!! suspect"
        print(f"{c['page']:>3} {c['native_chars']:>7} {c['md_chars']:>7} {c['ratio']:>6.2f}  {mark}")
    quality = report.get("quality", {})
    if quality:
        print("-" * 60)
        print(
            f"质量状态={quality.get('status')} 重复文本={quality.get('duplicate_text_count', 0)} "
            f"视觉重分类={quality.get('visual_reclassified', 0)} "
            f"伪公式拒绝={quality.get('formula_rejected', 0)} "
            f"边缘伪图抑制={quality.get('artifacts_suppressed', 0)}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="零 token 离线 PDF→Markdown 转换")
    parser.add_argument("pdf", help="输入 PDF 路径")
    parser.add_argument("--output", "-o", default=None, help="输出目录 (默认: 输入同目录下 <name>_pdf2md)")
    parser.add_argument("--lang", default="en", choices=["en", "zh"], help="语言提示 (当前主要影响 OCR 方向)")
    parser.add_argument("--drop-margins", action="store_true", help="删除页眉页脚 (默认标注保留)")
    parser.add_argument("--no-ocr", action="store_true", help="跳过 OCR 兜底")
    parser.add_argument("--dpi", type=int, default=220, help="页面 OCR DPI")
    parser.add_argument("--formula-dpi", type=int, default=300, help="公式区域 OCR DPI")
    parser.add_argument("--image-dpi", type=int, default=200, help="图片导出 DPI")
    parser.add_argument("--max-pages", type=int, default=None, help="只处理前 N 页")
    parser.add_argument("--formula-engine", default="auto",
                        choices=["auto", "pix2tex", "rapidocr"],
                        help="公式识别引擎: auto=pix2tex优先, rapidocr=符号映射兜底")
    parser.add_argument("--table-merge", default="expand", choices=["expand", "blank"],
                        help="复杂表合并单元格在 MD 中的表达: expand=展开复制(默认, 数据零丢失), blank=空白占位")
    parser.add_argument("--no-table-model", action="store_true",
                        help="跳过 SLANet 表格结构模型 (复杂表回退几何重建/图片)")
    parser.add_argument("--layout-model", default=None,
                        help="doclayout_yolo 权重文件；也可通过 PDF2MD_LAYOUT_MODEL 设置")
    parser.add_argument(
        "--layout-model-sha256", default=None,
        help="外部 .pt 权重的可信 SHA-256；也可通过 PDF2MD_LAYOUT_MODEL_SHA256 设置",
    )
    parser.add_argument("--offline", action="store_true", default=True,
                        help="兼容选项；PDF 转换始终使用本地模型且不主动联网")
    args = parser.parse_args()

    if not Path(args.pdf).exists():
        print(f"错误: 文件不存在: {args.pdf}", file=sys.stderr)
        return 1

    out = args.output or os.path.join(
        os.path.dirname(os.path.abspath(args.pdf)),
        os.path.splitext(os.path.basename(args.pdf))[0] + "_pdf2md",
    )
    try:
        report = convert_pdf(
            args.pdf, out,
            lang=args.lang, dpi=args.dpi, image_dpi=args.image_dpi,
            formula_dpi=args.formula_dpi, do_ocr=not args.no_ocr,
            keep_margins=not args.drop_margins, max_pages=args.max_pages,
            formula_engine=args.formula_engine,
            use_table_model=not args.no_table_model, merge_policy=args.table_merge,
            layout_model_path=args.layout_model,
            layout_model_sha256=args.layout_model_sha256,
            offline=args.offline,
        )
    except Exception as exc:
        print(f"转换失败: {exc}", file=sys.stderr)
        return 1

    _print_report(report)
    os.makedirs(out, exist_ok=True)
    report_path = os.path.join(out, "report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in report.items() if k != "markdown"}, f, ensure_ascii=False, indent=2)
    print(f"报告: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
