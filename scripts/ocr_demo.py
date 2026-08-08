"""litwise-ocr 真实输出检测脚本。

用法:
    python scripts/ocr_demo.py <pdf路径> [页码...] [--output 目录]

不带页码: 对全文每页做页面诊断, 汇总状态分布。
带页码:   额外对指定页跑真实 RapidOCR, 输出识别文本、置信度、
           耗时与峰值内存。

结果文件默认写到输入 PDF 同目录:
    <pdf名>.ocr.json      # 完整结果(诊断 + OCR 候选 + 性能)
    <pdf名>.ocr.md        # 人类可读摘要
可用 --output 指定其他目录。

示例:
    python scripts/ocr_demo.py "E:/papers/scan.pdf"
    python scripts/ocr_demo.py "E:/papers/scan.pdf" 1 2 3
    python scripts/ocr_demo.py "E:/papers/scan.pdf" 1 2 3 --output "E:/out"
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# 统一 UTF-8 输出, 避免 Windows 控制台 GBK 代码页导致中文乱码.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from ocr_contracts import OCRRegionRequest
from ocr_worker import run_ocr_job
from page_diagnostics import extract_page_signals, diagnose_page


def diagnose_all(pdf_path: str) -> list[dict]:
    """逐页诊断, 返回每页诊断字典."""
    print(f"PDF: {pdf_path}\n")
    signals = extract_page_signals(pdf_path)
    results = []
    for signal in signals:
        result = diagnose_page(signal)
        results.append({
            "page": signal.page,
            "status": result.status,
            "reasons": result.reasons,
            "repair_regions": result.repair_regions,
            "metrics": result.metrics,
        })
        status = result.status.ljust(14)
        chars = signal.native_characters
        regions = len(result.repair_regions)
        reasons = ",".join(result.reasons) if result.reasons else "-"
        print(
            f"  第{signal.page:>3}页  {status}  原生字符={chars:>6}  "
            f"修复区域={regions:>2}  原因=[{reasons}]"
        )
    return results


def ocr_page(pdf_path: str, page: int) -> dict:
    """对指定页跑真实 RapidOCR, 返回结果字典."""
    signals = extract_page_signals(pdf_path)
    if page < 1 or page > len(signals):
        return {"page": page, "error": f"page_out_of_range (1..{len(signals)})"}
    signal = next(s for s in signals if s.page == page)
    result = diagnose_page(signal)

    # 没有可修复区域时, 兜底用整页 bbox
    regions = result.repair_regions or [[0.0, 0.0, signal.width, signal.height]]

    request = OCRRegionRequest(
        job_id=f"demo-p{page}",
        pdf_path=str(Path(pdf_path).resolve()),
        page=page,
        regions=regions,
        engine="production",
        language="zh",
        dpi=220,
        max_ram_bytes=8 * 1024**3,
    )
    print(f"\n>>> 对第{page}页 OCR ({len(regions)} 个区域, 引擎=rapidocr, dpi=220)")
    started = time.perf_counter()
    job = run_ocr_job(request, timeout_seconds=300)
    elapsed = time.perf_counter() - started

    candidates = [
        {
            "bbox_pdf": item.bbox_pdf,
            "text": item.text,
            "confidence": item.confidence,
            "engine": item.engine,
        }
        for item in job.regions
    ]
    result_dict = {
        "page": page,
        "status": result.status,
        "regions_requested": len(regions),
        "candidates": candidates,
        "error": job.error,
        "worker_exit_code": job.worker_exit_code,
        "worker_alive_after_join": job.worker_alive_after_join,
        "peak_rss_bytes": job.peak_rss_bytes,
        "duration_ms": job.duration_ms,
        "elapsed_s": round(elapsed, 1),
    }

    # 控制台摘要
    if job.error:
        print(f"  [失败] error={job.error}")
    if not job.regions:
        print("  [无结果] 该页没有识别出非空文本")
    for item in job.regions:
        text_preview = item.text.replace("\n", "␤")
        if len(text_preview) > 40:
            text_preview = text_preview[:40] + "…"
        print(f"  [p{page} conf={item.confidence:<6}] {text_preview}")
    print(
        f"\n  耗时={job.duration_ms}ms (总 {elapsed:.1f}s)  "
        f"峰值内存={job.peak_rss_bytes/1024/1024:.1f}MB  "
        f"worker退出码={job.worker_exit_code}  残留进程={job.worker_alive_after_join}"
    )
    return result_dict


def write_outputs(pdf_path: str, diagnostics: list[dict], ocr_results: list[dict], output_dir: str | None) -> Path:
    """把结果写入文件, 返回输出目录."""
    pdf = Path(pdf_path).resolve()
    out_dir = Path(output_dir).resolve() if output_dir else pdf.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "pdf": str(pdf),
        "pages": len(diagnostics),
        "diagnostics": diagnostics,
        "ocr": ocr_results,
        "meta": {
            "engine": "rapidocr",
            "dpi": 220,
            "max_ram_bytes": 8 * 1024**3,
            "generated_at_local": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
    }
    json_path = out_dir / f"{pdf.stem}.ocr.json"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 人类可读 Markdown 摘要
    md_lines = [f"# OCR 检测报告: {pdf.name}", ""]
    md_lines.append(f"- 页数: {len(diagnostics)}")
    md_lines.append(f"- 生成: {payload['meta']['generated_at_local']}")
    md_lines.append("")
    md_lines.append("## 页面诊断")
    md_lines.append("")
    md_lines.append("| 页 | 状态 | 原生字符 | 修复区域 | 原因 |")
    md_lines.append("|---|---|---:|---:|---|")
    for d in diagnostics:
        md_lines.append(
            f"| {d['page']} | {d['status']} | "
            f"{int(d['metrics'].get('native_characters', 0))} | "
            f"{len(d['repair_regions'])} | {','.join(d['reasons']) or '-'} |"
        )
    if ocr_results:
        md_lines.append("")
        md_lines.append("## OCR 候选")
        md_lines.append("")
        for o in ocr_results:
            if "error" in o and o.get("error") and not o.get("candidates"):
                md_lines.append(f"### 第{o['page']}页 — 失败: {o['error']}")
                continue
            md_lines.append(f"### 第{o['page']}页 ({len(o['candidates'])} 候选, "
                            f"{o['duration_ms']}ms, {o['peak_rss_bytes']/1024/1024:.1f}MB)")
            md_lines.append("")
            md_lines.append("| 置信度 | 文本 |")
            md_lines.append("|---|---|")
            for c in o["candidates"]:
                text_flat = c["text"].replace("\n", " / ")
                md_lines.append(f"| {c['confidence']:.4f} | {text_flat} |")
            md_lines.append("")
    md_path = out_dir / f"{pdf.stem}.ocr.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"\n结果已写入:\n  {json_path}\n  {md_path}")
    return out_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="litwise-ocr 输出检测")
    parser.add_argument("pdf", help="PDF 路径")
    parser.add_argument("pages", nargs="*", type=int, help="要跑真实 OCR 的页码")
    parser.add_argument("--output", default=None, help="结果输出目录(默认输入 PDF 同目录)")
    args = parser.parse_args()

    if not Path(args.pdf).exists():
        print(f"错误: 文件不存在: {args.pdf}")
        sys.exit(1)

    diagnostics = diagnose_all(args.pdf)
    counts: dict[str, int] = {}
    for d in diagnostics:
        counts[d["status"]] = counts.get(d["status"], 0) + 1
    print("\n  状态汇总: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))

    ocr_results = [ocr_page(args.pdf, page) for page in args.pages]

    if args.pages:
        write_outputs(args.pdf, diagnostics, ocr_results, args.output)
    else:
        # 只做诊断也写出报告
        write_outputs(args.pdf, diagnostics, ocr_results, args.output)


if __name__ == "__main__":
    main()
