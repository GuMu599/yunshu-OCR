"""pdf2md — 零 token 离线 PDF→Markdown 转换工具。

复用 litwise 家族既有资产：
- doclayout_yolo 版面检测 (layout.py)
- PyMuPDF 文字/图片/表格提取 (text.py / tables.py)
- layout_converter 内容分类规则 (classify.py)
- reading_order 阅读顺序 + 页眉页脚 (order.py)
- RapidOCR 兜底 (ocr.py, vendored 适配器)

输出契约见 docs/PDF转Markdown零token工具实现计划.md §1。
"""

__version__ = "0.1.0"
