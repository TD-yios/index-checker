from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

SUMMARY_COLS = ["时间", "品牌", "关键词", "目标URL", "搜索引擎", "是否命中", "品牌专区数", "品牌首现页",
                "聚合卡片数", "卡片首现页", "竞价广告数", "广告首现页", "自然排名数",
                "自然首现页", "自然首现页内位", "自然首现全局位", "命中URL", "命中总数", "检查页数", "状态"]
DETAIL_COLS = ["时间", "品牌", "关键词", "目标URL", "搜索引擎", "页码", "状态", "命中数", "命中类型", "命中排位",
               "命中URL", "命中标题", "截图", "搜索URL", "备注"]
HIT_COLS = ["时间", "品牌", "关键词", "目标URL", "搜索引擎", "页码", "页内位次", "全局排名", "类型", "标题", "URL", "截图"]

KIND_FILL = {
    "自然结果": "DCFCE7",
    "品牌专区": "FEF3C7",
    "竞价广告": "FEE2E2",
    "聚合卡片": "DBEAFE",
}


def _safe_cell(value: Any) -> Any:
    """避免导入的品牌/标题以 = + - @ 开头时被 Excel 当公式执行。"""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        return "'" + value
    return value


def _write_csv(path: Path, cols: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: _safe_cell(row.get(c, "")) for c in cols})


def _write_xlsx(path: Path, summary_rows, detail_rows, hit_rows, meta: dict[str, Any]) -> bool:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter
    except Exception:
        return False

    wb = Workbook()
    title_font = Font(name="微软雅黑", size=14, bold=True, color="1F2937")
    head_font = Font(name="微软雅黑", size=10, bold=True, color="FFFFFF")
    body_font = Font(name="微软雅黑", size=10)
    head_fill = PatternFill("solid", fgColor="2563EB")
    miss_fill = PatternFill("solid", fgColor="F3F4F6")
    thin = Side(style="thin", color="D1D5DB")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    def write_table(ws, cols, rows, widths, start_row=1, title=None):
        r = start_row
        if title:
            ws.cell(row=r, column=1, value=title).font = title_font
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=len(cols))
            r += 2
        for i, name in enumerate(cols, start=1):
            c = ws.cell(row=r, column=i, value=name)
            c.font = head_font
            c.fill = head_fill
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.border = border
        header_row = r
        for data in rows:
            r += 1
            for i, name in enumerate(cols, start=1):
                c = ws.cell(row=r, column=i, value=_safe_cell(data.get(name, "")))
                c.font = body_font
                c.border = border
                c.alignment = Alignment(vertical="center", wrap_text=True)
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
        ws.auto_filter.ref = f"A{header_row}:{get_column_letter(len(cols))}{max(header_row, r)}"
        return header_row

    # ---------- 汇总 ----------
    ws = wb.active
    ws.title = "汇总"
    ws["A1"] = "搜索收录查询报告"
    ws["A1"].font = title_font
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(SUMMARY_COLS))
    row = 2
    for key in ("目标域名", "品牌数", "开始时间", "结束时间", "关键词数", "引擎数", "翻页上限",
                "任务数", "命中任务数", "命中记录数", "检查页数"):
        ws.cell(row=row, column=1, value=key).font = Font(name="微软雅黑", size=10, bold=True)
        ws.cell(row=row, column=2, value=_safe_cell(meta.get(key, "")))
        row += 1
    header_row = write_table(
        ws, SUMMARY_COLS, summary_rows,
        [19, 18, 24, 40, 10, 9, 11, 11, 11, 11, 11, 11, 11, 11, 11, 12, 46, 9, 9, 12],
        start_row=row + 1,
    )
    # 命中=是有底色
    for r_idx, data in enumerate(summary_rows, start=header_row + 1):
        fill = PatternFill("solid", fgColor="DCFCE7") if data.get("是否命中") == "是" else miss_fill
        ws.cell(row=r_idx, column=6).fill = fill

    # ---------- 命中明细（按类型） ----------
    ws2 = wb.create_sheet("命中明细")
    h2 = write_table(ws2, HIT_COLS, hit_rows, [19, 18, 22, 42, 10, 7, 9, 9, 13, 48, 46, 48],
                     title="命中明细（按类型筛选：类型列）")
    type_col = HIT_COLS.index("类型") + 1
    for r_idx, data in enumerate(hit_rows, start=h2 + 1):
        color = KIND_FILL.get(data.get("类型", ""), "FFFFFF")
        ws2.cell(row=r_idx, column=type_col).fill = PatternFill("solid", fgColor=color)

    # ---------- 分页明细 ----------
    ws3 = wb.create_sheet("分页明细")
    h3 = write_table(ws3, DETAIL_COLS, detail_rows,
                     [19, 18, 24, 40, 10, 7, 12, 8, 16, 18, 46, 46, 48, 60, 30])
    for r_idx, data in enumerate(detail_rows, start=h3 + 1):
        if int(data.get("命中数") or 0) > 0:
            ws3.cell(row=r_idx, column=8).fill = PatternFill("solid", fgColor="DCFCE7")

    wb.save(path)
    return True


def write_reports(outdir: Path, summary_rows, detail_rows, hit_rows, meta: dict[str, Any]) -> dict[str, str]:
    paths: dict[str, str] = {}
    csv_path = outdir / "查询汇总.csv"
    _write_csv(csv_path, SUMMARY_COLS, summary_rows)
    paths["csv"] = str(csv_path)

    detail_csv = outdir / "分页明细.csv"
    _write_csv(detail_csv, DETAIL_COLS, detail_rows)
    paths["detail_csv"] = str(detail_csv)

    hit_csv = outdir / "命中明细.csv"
    _write_csv(hit_csv, HIT_COLS, hit_rows)
    paths["hit_csv"] = str(hit_csv)

    xlsx_path = outdir / "收录查询报告.xlsx"
    if _write_xlsx(xlsx_path, summary_rows, detail_rows, hit_rows, meta):
        paths["xlsx"] = str(xlsx_path)
    return paths
