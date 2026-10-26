# -*- coding: utf-8 -*-
"""文档工厂：把定稿产物渲染为 docx / HTML / Markdown / zip（v2）。

三层格式保证（对应方案书「横版表格三层防线」的第二层）：
  1. 教案整篇 A4 横向（29.7×21cm），页眉「阳泉师范高等专科学校教案」；
  2. 表一 2 列（4.2 / 22.5cm），表二 5 列（3.6 / 7.6 / 5.6 / 5.4 / 4.5cm），固定列宽；
  3. 表头加粗、跨页重复、单元格不跨页，正文宋体，表格 9pt，打印可直接使用。

Markdown → docx/HTML 均为本地渲染，不依赖外部服务。
"""
import html as _html
import io
import json
import re
import zipfile
from datetime import datetime

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

from . import config, store, courseware

FILE_CN = {
    "lesson_plan": "教案",
    "handout": "讲义",
    "courseware": "课件",
    "script": "理论讲解逐字稿",
    "week_plan": "课程地图",
}

A4_LAND_W, A4_LAND_H = Cm(29.7), Cm(21.0)
A4_PORT_W, A4_PORT_H = Cm(21.0), Cm(29.7)
_TABLE_WIDTHS = {
    2: [Cm(4.2), Cm(22.5)],
    5: [Cm(3.6), Cm(7.6), Cm(5.6), Cm(5.4), Cm(4.5)],
}


# ================= docx 基础工具 =================
def _set_run_font(run, name="宋体", size=None, bold=None):
    run.font.name = name
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:ascii"), name)
    rfonts.set(qn("w:hAnsi"), name)
    rfonts.set(qn("w:eastAsia"), name)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold


def _shade(cell, fill="F2F2F2"):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tcPr.append(shd)


def _repeat_header(row):
    trPr = row._tr.get_or_add_trPr()
    tblHeader = OxmlElement("w:tblHeader")
    tblHeader.set(qn("w:val"), "true")
    trPr.append(tblHeader)
    cantSplit = OxmlElement("w:cantSplit")
    cantSplit.set(qn("w:val"), "true")
    trPr.append(cantSplit)


def _cell_margins(table, top=40, bottom=40, left=70, right=70):
    tblPr = table._tbl.tblPr
    mar = OxmlElement("w:tblCellMar")
    for name, val in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        el = OxmlElement(f"w:{name}")
        el.set(qn("w:w"), str(val))
        el.set(qn("w:type"), "dxa")
        mar.append(el)
    tblPr.append(mar)


def _add_rich_text(paragraph, text, size=None, bold=False):
    """解析 **加粗**，写入一个段落。"""
    for i, seg in enumerate(re.split(r"\*\*(.+?)\*\*", text or "")):
        if not seg:
            continue
        run = paragraph.add_run(seg)
        _set_run_font(run, size=size, bold=(bold or i % 2 == 1))


def _add_md_paragraph(doc, text: str):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.line_spacing = 1.35
    _add_rich_text(p, text)
    return p


def _add_md_table(doc, rows: list, landscape: bool = False):
    if not rows:
        return
    n_col = max(len(r) for r in rows)
    rows = [r + [""] * (n_col - len(r)) for r in rows]
    table = doc.add_table(rows=len(rows), cols=n_col)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    _cell_margins(table)
    widths = _TABLE_WIDTHS.get(n_col) if landscape else None
    if not widths:
        total = Cm(18.0 if not landscape else 26.7)
        widths = [Cm(total.cm / n_col)] * n_col
    font_size = 9 if landscape and n_col == 5 else 10
    for ri, r in enumerate(rows):
        row = table.rows[ri]
        row.allow_break_across_pages = False
        label = "".join(str(c) for c in r).strip()
        is_info_label = (n_col == 2 and ri > 0 and len(str(r[0]).strip()) <= 8
                         and str(r[1]).strip())
        for ci in range(n_col):
            cell = table.cell(ri, ci)
            cell.width = widths[ci]
            text = str(r[ci]).replace("<br>", "\n").replace("\\n", "\n")
            cell.text = ""
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.1
            if ri == 0 or (n_col == 2 and ci == 0 and label):
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER if ri == 0 else WD_ALIGN_PARAGRAPH.LEFT
            _add_rich_text(p, text, size=font_size, bold=(ri == 0 or (n_col == 2 and ci == 0)))
            if ri == 0:
                _shade(cell, "F2F2F2")
            elif n_col == 2 and ci == 0:
                _shade(cell, "FAFAFA")
        if ri == 0:
            _repeat_header(row)
    if widths:
        for ci, w in enumerate(widths):
            table.columns[ci].width = w
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def _set_landscape(doc):
    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = A4_LAND_W, A4_LAND_H
    sec.left_margin = sec.right_margin = Cm(1.5)
    sec.top_margin = Cm(1.4)
    sec.bottom_margin = Cm(1.3)


def _set_portrait(doc):
    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.PORTRAIT
    sec.page_width, sec.page_height = A4_PORT_W, A4_PORT_H
    sec.left_margin = sec.right_margin = Cm(2.2)
    sec.top_margin = Cm(2.0)
    sec.bottom_margin = Cm(2.0)


def _add_page_number(doc):
    footer = doc.sections[0].footer
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = "1"
    run.append(text)
    fld.append(run)
    p._p.append(fld)


def _header_text(doc, text, size=15):
    header = doc.sections[0].header
    p = header.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(text)
    _set_run_font(run, size=size, bold=True)
    # 页眉下边框
    pPr = p._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "999999")
    pbdr.append(bottom)
    pPr.append(pbdr)


def _new_doc(landscape: bool, header: str = ""):
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "宋体"
    style.font.size = Pt(11)
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), "宋体")
    rfonts.set(qn("w:ascii"), "宋体")
    rfonts.set(qn("w:hAnsi"), "宋体")
    if landscape:
        _set_landscape(doc)
    else:
        _set_portrait(doc)
    if header:
        _header_text(doc, header)
        _add_page_number(doc)
    return doc


# ================= Markdown → docx =================
def md_to_docx(md_text: str, landscape: bool = False, header: str = "",
               title: str = "") -> Document:
    doc = _new_doc(landscape, header)
    if title and not header:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _set_run_font(p.add_run(title), size=16, bold=True)
    lines = (md_text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()
        if not line.strip():
            i += 1
            continue
        # 代码块：原样输出
        if line.strip().startswith("```"):
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                p = doc.add_paragraph()
                _set_run_font(p.add_run(lines[i]), name="Consolas", size=9)
                i += 1
            i += 1
            continue
        if line.startswith("### "):
            p = doc.add_heading(line[4:], level=3)
            _style_heading(p, 13)
            i += 1
            continue
        if line.startswith("## "):
            p = doc.add_heading(line[3:], level=2)
            _style_heading(p, 14)
            i += 1
            continue
        if line.startswith("# "):
            p = doc.add_heading(line[2:], level=1)
            _style_heading(p, 16)
            i += 1
            continue
        if re.match(r"^\s*>\s?", line):
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.6)
            _add_rich_text(p, re.sub(r"^\s*>\s?", "", line))
            i += 1
            continue
        if re.match(r"^\s*(---+|\*\*\*+|___+)\s*$", line):
            p = doc.add_paragraph()
            pPr = p._p.get_or_add_pPr()
            pbdr = OxmlElement("w:pBdr")
            bottom = OxmlElement("w:bottom")
            bottom.set(qn("w:val"), "single")
            bottom.set(qn("w:sz"), "4")
            bottom.set(qn("w:color"), "BBBBBB")
            pbdr.append(bottom)
            pPr.append(pbdr)
            i += 1
            continue
        # 表格
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        sep = bool(re.match(r"^\|[\s\-:|]+\|?$", nxt))
        if line.strip().startswith("|") and (sep or nxt.startswith("|")):
            rows = [[c.strip() for c in line.strip().strip("|").split("|")]]
            i += 2 if sep else 1
            while i < len(lines) and lines[i].strip().startswith("|"):
                if not re.match(r"^\|[\s\-:|]+\|?$", lines[i].strip()):
                    rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            if len(rows) >= 2:
                _add_md_table(doc, rows, landscape)
            continue
        if re.match(r"^\s*[-*•]\s+", line):
            p = doc.add_paragraph(style="List Bullet")
            _add_rich_text(p, re.sub(r"^\s*[-*•]\s+", "", line))
            i += 1
            continue
        if re.match(r"^\s*\d+[.、]\s+", line):
            p = doc.add_paragraph(style="List Number")
            _add_rich_text(p, re.sub(r"^\s*\d+[.、]\s+", "", line))
            i += 1
            continue
        _add_md_paragraph(doc, line)
        i += 1
    return doc


def _style_heading(p, size):
    for run in p.runs:
        _set_run_font(run, name="黑体", size=size, bold=True)
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(3)


# ================= Markdown → HTML =================
def _esc(s: str) -> str:
    return _html.escape(s or "", quote=True)


def _inline(text: str) -> str:
    t = _esc(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"`(.+?)`", r"<code>\1</code>", t)
    return t


def md_to_html(md_text: str) -> str:
    lines = (md_text or "").replace("\r\n", "\n").split("\n")
    out, i, in_code = [], 0, False
    list_open = None
    while i < len(lines):
        line = lines[i].rstrip()
        if line.strip().startswith("```"):
            if in_code:
                out.append("</code></pre>")
                in_code = False
            else:
                out.append("<pre><code>")
                in_code = True
            i += 1
            continue
        if in_code:
            out.append(_esc(lines[i]) + "\n")
            i += 1
            continue
        if not line.strip():
            if list_open:
                out.append(f"</{list_open}>")
                list_open = None
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            if list_open:
                out.append(f"</{list_open}>")
                list_open = None
            lv = len(m.group(1))
            out.append(f"<h{lv}>{_inline(m.group(2))}</h{lv}>")
            i += 1
            continue
        if re.match(r"^\s*(---+|\*\*\*+|___+)\s*$", line):
            out.append("<hr>")
            i += 1
            continue
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        sep = bool(re.match(r"^\|[\s\-:|]+\|?$", nxt))
        if line.strip().startswith("|") and (sep or nxt.startswith("|")):
            if list_open:
                out.append(f"</{list_open}>")
                list_open = None
            head = [c.strip() for c in line.strip().strip("|").split("|")]
            i += 2 if sep else 1
            body = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                if not re.match(r"^\|[\s\-:|]+\|?$", lines[i].strip()):
                    body.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            out.append("<table><thead><tr>" +
                       "".join(f"<th>{_inline(c)}</th>" for c in head) +
                       "</tr></thead><tbody>" +
                       "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>"
                               for r in body) +
                       "</tbody></table>")
            continue
        if re.match(r"^\s*[-*•]\s+", line):
            if list_open != "ul":
                if list_open:
                    out.append(f"</{list_open}>")
                out.append("<ul>")
                list_open = "ul"
            item = re.sub(r"^\s*[-*•]\s+", "", line)
            out.append(f"<li>{_inline(item)}</li>")
            i += 1
            continue
        if re.match(r"^\s*\d+[.、]\s+", line):
            if list_open != "ol":
                if list_open:
                    out.append(f"</{list_open}>")
                out.append("<ol>")
                list_open = "ol"
            item = re.sub(r"^\s*\d+[.、]\s+", "", line)
            out.append(f"<li>{_inline(item)}</li>")
            i += 1
            continue
        if re.match(r"^\s*>\s?", line):
            quote_text = re.sub(r"^\s*>\s?", "", line)
            out.append("<blockquote>" + _inline(quote_text) + "</blockquote>")
            i += 1
            continue
        if list_open:
            out.append(f"</{list_open}>")
            list_open = None
        out.append(f"<p>{_inline(line)}</p>")
        i += 1
    if list_open:
        out.append(f"</{list_open}>")
    if in_code:
        out.append("</code></pre>")
    return "\n".join(out)


_HTML_CSS = """
*{box-sizing:border-box}
body{margin:0;background:#f3f1ea;color:#22302b;font-family:"Noto Serif SC","Songti SC",SimSun,serif;line-height:1.75}
.page{max-width:860px;margin:24px auto;background:#fff;padding:38px 44px;box-shadow:0 2px 18px rgba(0,0,0,.08);border-radius:6px}
.header{text-align:center;font-size:21px;font-weight:700;letter-spacing:2px;border-bottom:2px solid #143f35;padding-bottom:10px;margin-bottom:20px}
h1{font-size:24px;text-align:center;margin:6px 0 18px}
h2{font-size:18px;color:#143f35;border-left:5px solid #c9a961;padding-left:10px;margin:22px 0 8px}
h3{font-size:16px;color:#143f35;margin:16px 0 6px}
p{margin:8px 0}
table{border-collapse:collapse;width:100%;margin:12px 0;font-size:13px}
th,td{border:1px solid #9aa39f;padding:6px 8px;vertical-align:top;text-align:left}
th{background:#f2f2f2;font-weight:700}
ul,ol{padding-left:24px}
li{margin:4px 0}
blockquote{margin:10px 0;padding:8px 14px;border-left:4px solid #c9a961;background:#faf7ee;color:#5c6b65}
code{background:#f0ece0;padding:1px 5px;border-radius:3px;font-size:12px}
pre{background:#1d2b26;color:#dce8e1;padding:14px;overflow:auto;border-radius:6px}
hr{border:none;border-top:1px solid #ddd;margin:16px 0}
.meta{color:#7a8781;font-size:12px;text-align:center;margin-bottom:18px}
@media print{body{background:#fff}.page{box-shadow:none;margin:0;max-width:none;padding:0}@page{size:A4 portrait;margin:18mm}}
"""


def artifact_html(a: dict) -> str:
    header = config.DOC_HEADER if a.get("file_type") == "lesson_plan" else ""
    landscape = a.get("file_type") == "lesson_plan"
    css = _HTML_CSS
    if landscape:
        css += "@media print{@page{size:A4 landscape;margin:12mm}}"
    course = store.get_course(a["course_id"]) or {}
    cn = FILE_CN.get(a["file_type"], a["file_type"])
    body = md_to_html(a.get("content") or "")
    meta = (f"{_esc(course.get('name',''))} · 第 {a.get('week_no')} 周 · {cn} · "
            f"{_esc(a.get('model') or '')} · 更新于 {_esc(a.get('updated_at') or '')}")
    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(course.get('name',''))} · 第{a.get('week_no')}周 {cn}</title>
<style>{css}</style></head><body><div class="page">
{f'<div class="header">{_esc(header)}</div>' if header else ''}
{body}
<div class="meta">{meta}</div></div></body></html>"""


# ================= 产物导出 =================
def render_artifact_docx(artifact_id: int) -> bytes:
    a = store.get_artifact(artifact_id)
    if not a:
        raise ValueError("产物不存在")
    landscape = a.get("file_type") == "lesson_plan"
    header = config.DOC_HEADER if landscape else ""
    title = "" if header else f"{FILE_CN.get(a.get('file_type'), '')}：第{a.get('week_no')}周"
    doc = md_to_docx(a.get("content") or "", landscape=landscape, header=header, title=title)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def courseware_html(a: dict) -> str:
    course = store.get_course(a["course_id"]) or {}
    return courseware.build_html(a, course, a.get("week_no"))


def courseware_pptx(a: dict) -> bytes:
    course = store.get_course(a["course_id"]) or {}
    return courseware.build_pptx(a, course, a.get("week_no"))


def export_bytes(artifact_id: int, fmt: str) -> tuple:
    """返回 (bytes, media_type, filename)。"""
    a = store.get_artifact(artifact_id)
    if not a:
        raise ValueError("产物不存在")
    cn = FILE_CN.get(a.get("file_type"), a.get("file_type"))
    base = f"第{a['week_no']}周-{cn}"
    fmt = (fmt or "docx").lower()
    if a.get("file_type") == "courseware":
        if fmt == "pptx":
            return (courseware_pptx(a),
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    base + ".pptx")
        if fmt == "html":
            return (courseware_html(a).encode("utf-8"),
                    "text/html; charset=utf-8", base + "-互动版.html")
        raise ValueError("课件仅支持 pptx/html")
    if fmt == "md":
        return (a.get("content") or "").encode("utf-8"), "text/markdown; charset=utf-8", base + ".md"
    if fmt == "html":
        return artifact_html(a).encode("utf-8"), "text/html; charset=utf-8", base + ".html"
    return (render_artifact_docx(artifact_id),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            base + ".docx")


# ================= 索引 + 打包 =================
_STATUS_CN = {"pending": "待生成", "drafting": "生成中", "review": "待确认",
              "revising": "修订中", "approved": "已定稿", "failed": "失败"}


def render_index_docx(course_id: int) -> bytes:
    course = store.get_course(course_id) or {}
    arts = store.list_artifacts(course_id)
    usage = store.usage_summary(course_id)
    doc = _new_doc(False)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_run_font(p.add_run(f"《{course.get('name','')}》课程文件夹索引与使用说明"),
                  name="黑体", size=18, bold=True)
    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_run_font(sub.add_run(f"{course.get('semester','')} · 生成时间 "
                              f"{datetime.now().strftime('%Y-%m-%d %H:%M')}"), size=10)
    if course.get("class_name") or course.get("textbook"):
        p = doc.add_paragraph()
        _set_run_font(p.add_run(f"班级：{course.get('class_name') or '—'}　教材："
                                f"{course.get('textbook') or '—'}"), size=10)

    doc.add_heading("一、目录结构", level=2)
    doc.add_paragraph("课程教学包/\n├── 《课程文件夹索引与使用说明》.docx\n"
                      "├── 第N周/教案.docx、讲义.docx、课件.pptx、课件-互动版.html、理论讲解逐字稿.docx\n"
                      "└── manifest.json（文件清单与用量）")

    doc.add_heading("二、文件清单", level=2)
    rows = [["周次", "文件类型", "状态", "字数", "模型"]]
    for a in arts:
        rows.append([str(a.get("week_no") or ""), FILE_CN.get(a.get("file_type"), a.get("file_type")),
                     _STATUS_CN.get(a.get("status"), a.get("status")),
                     str(a.get("word_count") or len(a.get("content") or "")),
                     a.get("model") or ""])
    if len(rows) == 1:
        rows.append(["—", "暂无产物", "—", "—", "—"])
    _add_md_table(doc, rows, False)

    doc.add_heading("三、使用流程", level=2)
    for line in [
        "备课：按「教案 → 讲义 → 逐字稿」顺序核阅；教案为横版双表，可直接打印。",
        "授课：课件与逐字稿配合；逐字稿含舞台指示，可直接照读。",
        "自学：学生使用讲义与练习材料。",
        "归档：本包内文件均为门 B 已定稿版本；未定稿文件不会打包。",
    ]:
        p = doc.add_paragraph(style="List Bullet")
        _add_rich_text(p, line, size=11)

    doc.add_heading("四、本次用量", level=2)
    doc.add_paragraph(f"模型调用 {usage['calls']} 次；输入 {usage['in_tokens']} tokens，"
                      f"输出 {usage['out_tokens']} tokens；估算费用 ¥{usage['cost']:.4f}。")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _safe_name(name: str) -> str:
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name or "课程").strip(" ._")
    return s[:60] or "课程"


def package_course(course_id: int) -> str:
    """打包定稿产物为 zip（含索引、manifest 与用量），返回 zip 路径。"""
    course = store.get_course(course_id)
    if not course:
        raise ValueError("课程不存在")
    arts = [a for a in store.list_artifacts(course_id) if a["status"] == "approved"
            and (a.get("content") or "").strip()]
    if not arts:
        raise ValueError("没有已定稿的产物，请先在确认中心批准（门 B）")
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe = _safe_name(course["name"])
    zip_path = config.OUTPUT_DIR / f"{safe}_教学包_{datetime.now():%Y%m%d%H%M%S}.zip"
    manifest = {
        "course": course["name"],
        "semester": course.get("semester"),
        "class_name": course.get("class_name"),
        "packaged_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "files": [{"week": a["week_no"], "type": a["file_type"],
                   "status": a["status"], "model": a.get("model"),
                   "chars": len(a.get("content") or "")} for a in arts],
        "usage": store.usage_summary(course_id),
    }
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("《课程文件夹索引与使用说明》.docx", render_index_docx(course_id))
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for a in arts:
            cn = FILE_CN.get(a["file_type"], a["file_type"])
            week_dir = f"第{a['week_no']}周"
            if a["file_type"] == "courseware":
                zf.writestr(f"{week_dir}/{cn}.pptx", courseware_pptx(a))
                zf.writestr(f"{week_dir}/{cn}-互动版.html", courseware_html(a))
            else:
                zf.writestr(f"{week_dir}/{cn}.docx", render_artifact_docx(a["id"]))
                zf.writestr(f"{week_dir}/{cn}.md", a.get("content") or "")
    store.add_confirm_log(course_id, None, "package", str(zip_path))
    return str(zip_path)


def latest_package(course_id: int) -> str:
    with store._db() as conn:  # 复用数据层连接
        rows = conn.execute(
            "SELECT reason FROM confirm_log WHERE course_id=? AND action='package' "
            "ORDER BY id DESC LIMIT 20", (course_id,)).fetchall()
    import os
    for r in rows:
        path = r["reason"] or ""
        if path and os.path.isfile(path):
            return path
    return ""
