"""表格识别共享常量/阈值 (集中定义, 供各子模块引用, 避免散落魔法数字).

拆分 self: 常量放这里, 各表格子模块 (table_geometry/table_detect/table_merge/tables)
从本模块 import, 不互相依赖, 消除循环导入。
"""

# ---- 质量门/权重 ----
QUALITY_GATE = 0.6          # 几何重建质量门
MODEL_GATE = 0.5            # 结构模型质量门
QUALITY_COV_W = 0.6         # 质量分: 列支撑覆盖率权重
QUALITY_FILL_W = 0.4        # 质量分: 填充率权重

# ---- 文本/几何阈值 ----
MIN_MD_LEN = 8              # PyMuPDF MD 最短接受长度
PROSE_LINE_AVG = 30         # looks_like_table_data: 平均行长短于该值才像表数据
MIN_TABLE_WORDS = 4         # 几何重建最少词数
MIN_TEXT_TABLE_WORDS = 6    # pymupdf_text 路径最少词数
ROW_TOL_FRAC = 0.6          # 聚行容差 = frac × 中位字高
COL_GAP_FRAC = 0.25         # 聚列容差 = max(4, frac × 中位字宽)
WRAP_GAP_FRAC = 0.25        # 多行格合并间隙 = frac × 中位行高

# ---- 守卫/启发式 ----
MATH_LINE_FRAC = 0.5        # _is_math_region: 数学行占比超该值判公式区
GRAPH_LINE_THRESHOLD = 50   # _is_graph_region: 矢量线超该值判图表
CELL_LONG_LEN = 14          # _prose_like_table: 单元格长于该值算"长"
CELL_LONG_FRAC = 0.3        # _prose_like_table: 长细胞占比超该值判散文

# ---- 跨页合并 ----
COL_SIG_TOL = 0.5           # 列类型签名最大允许差
HEADER_NUMERIC_FRAC = 0.3   # _row_header_like: 行内数字占比低于该值才算表头样
HEADER_CELL_LEN = 25        # _row_header_like: 表头细胞最大长度
HEADER_SIM_TOL = 0.5        # 表头字符重合度门槛

# ---- 输出标记 ----
TABLE_MARKER = "<!-- table: full structure in layout.json -->"
IMG_MARKER = "<!-- table: unrecognized, image fallback -->"
