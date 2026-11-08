"""Build the Chinese HealthZIP user manual PDF from Markdown."""

from __future__ import annotations

import re
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import cidfonts, pdfmetrics
from reportlab.platypus import (
    HRFlowable,
    LongTable,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "HealthZIP_使用手册.md"
OUTPUT = ROOT / "output" / "pdf" / "HealthZIP_使用手册.pdf"
FONT = "STSong-Light"

pdfmetrics.registerFont(cidfonts.UnicodeCIDFont(FONT))
styles = getSampleStyleSheet()
styles.add(
    ParagraphStyle(
        name="ManualTitle",
        fontName=FONT,
        fontSize=25,
        leading=33,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#16324F"),
        spaceAfter=12,
        wordWrap="CJK",
    )
)
styles.add(
    ParagraphStyle(
        name="ManualSubtitle",
        fontName=FONT,
        fontSize=12,
        leading=19,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#087F8C"),
        spaceAfter=10,
        wordWrap="CJK",
    )
)
styles.add(
    ParagraphStyle(
        name="ManualBody",
        fontName=FONT,
        fontSize=9,
        leading=14,
        textColor=colors.HexColor("#243447"),
        spaceAfter=5,
        wordWrap="CJK",
    )
)
styles.add(
    ParagraphStyle(
        name="ManualH1",
        fontName=FONT,
        fontSize=18,
        leading=24,
        textColor=colors.HexColor("#16324F"),
        spaceBefore=12,
        spaceAfter=8,
        keepWithNext=True,
        wordWrap="CJK",
    )
)
styles.add(
    ParagraphStyle(
        name="ManualH2",
        fontName=FONT,
        fontSize=13,
        leading=18,
        textColor=colors.HexColor("#087F8C"),
        spaceBefore=9,
        spaceAfter=5,
        keepWithNext=True,
        wordWrap="CJK",
    )
)
styles.add(
    ParagraphStyle(
        name="ManualSmall",
        fontName=FONT,
        fontSize=7.5,
        leading=11,
        textColor=colors.HexColor("#526170"),
        spaceAfter=4,
        wordWrap="CJK",
    )
)
styles.add(
    ParagraphStyle(
        name="ManualCode",
        fontName=FONT,
        fontSize=7.2,
        leading=10,
        textColor=colors.HexColor("#1E3448"),
        backColor=colors.HexColor("#F2F6F8"),
        borderColor=colors.HexColor("#D9E4EA"),
        borderWidth=0.4,
        borderPadding=5,
        spaceBefore=3,
        spaceAfter=7,
    )
)
styles.add(
    ParagraphStyle(
        name="ManualTable",
        fontName=FONT,
        fontSize=7.4,
        leading=10,
        textColor=colors.HexColor("#243447"),
        wordWrap="CJK",
    )
)
styles.add(
    ParagraphStyle(
        name="ManualTableHead",
        fontName=FONT,
        fontSize=7.4,
        leading=10,
        textColor=colors.white,
        wordWrap="CJK",
    )
)


def inline_markdown(value: str) -> str:
    value = value.replace("VO₂", "VO2").replace("HRV-SDNN", "HRV-SDNN").replace("·", "-")
    value = escape(value)
    value = re.sub(r"`([^`]+)`", r'<font name="STSong-Light" backColor="#EEF3F6">\1</font>', value)
    value = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", value)
    value = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", value)
    return value


def split_table_row(line: str) -> list[str]:
    value = line.strip()
    if value.startswith("|"):
        value = value[1:]
    if value.endswith("|"):
        value = value[:-1]
    return [cell.strip() for cell in value.split("|")]


def table_flowable(rows: list[list[str]]) -> LongTable:
    count = max(len(row) for row in rows)
    available = A4[0] - 34 * mm
    widths = [available / count] * count
    if count == 2:
        widths = [available * 0.30, available * 0.70]
    elif count == 3:
        widths = [available * 0.22, available * 0.39, available * 0.39]
    data = []
    for index, row in enumerate(rows):
        row = row + [""] * (count - len(row))
        style = styles["ManualTableHead"] if index == 0 else styles["ManualTable"]
        data.append([Paragraph(inline_markdown(cell), style) for cell in row])
    table = LongTable(data, colWidths=widths, repeatRows=1, hAlign="LEFT", splitByRow=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#16324F")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F6F8")]),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D7E1E8")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def footer(canvas, document) -> None:
    canvas.saveState()
    width, _ = A4
    canvas.setStrokeColor(colors.HexColor("#D7E1E8"))
    canvas.setLineWidth(0.4)
    canvas.line(17 * mm, 15 * mm, width - 17 * mm, 15 * mm)
    canvas.setFont(FONT, 7)
    canvas.setFillColor(colors.HexColor("#647482"))
    canvas.drawString(17 * mm, 9 * mm, "HealthZIP - 本地使用手册")
    canvas.drawRightString(width - 17 * mm, 9 * mm, str(document.page))
    canvas.restoreState()


def build_story() -> list[object]:
    lines = SOURCE.read_text(encoding="utf-8").splitlines()
    story: list[object] = []
    in_code = False
    code: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.strip().startswith("```"):
            if in_code:
                story.append(Preformatted("\n".join(code), styles["ManualCode"], maxLineLength=110))
                code = []
                in_code = False
            else:
                in_code = True
            index += 1
            continue
        if in_code:
            code.append(line)
            index += 1
            continue
        if not line.strip():
            index += 1
            continue
        if line.strip() == "---":
            story.extend(
                [
                    Spacer(1, 3),
                    HRFlowable(width="100%", thickness=0.45, color=colors.HexColor("#D7E1E8")),
                    Spacer(1, 5),
                ]
            )
            index += 1
            continue
        if line.lstrip().startswith("|") and index + 1 < len(lines):
            if re.match(r"^\s*\|?\s*:?-{2,}", lines[index + 1]):
                rows = [split_table_row(line)]
                index += 2
                while index < len(lines) and lines[index].strip().startswith("|"):
                    rows.append(split_table_row(lines[index]))
                    index += 1
                story.extend([Spacer(1, 3), table_flowable(rows), Spacer(1, 6)])
                continue
        if line.startswith("# "):
            story.append(Paragraph(inline_markdown(line[2:]), styles["ManualTitle"]))
            index += 1
            continue
        if line.startswith("## "):
            story.append(Paragraph(inline_markdown(line[3:]), styles["ManualH1"]))
            index += 1
            continue
        if line.startswith("### "):
            story.append(Paragraph(inline_markdown(line[4:]), styles["ManualH2"]))
            index += 1
            continue
        if line.startswith("> "):
            story.append(Paragraph("<i>" + inline_markdown(line[2:]) + "</i>", styles["ManualSmall"]))
            index += 1
            continue
        if re.match(r"^\s*- ", line):
            story.append(Paragraph("- " + inline_markdown(line.strip()[2:]), styles["ManualBody"]))
            index += 1
            continue
        if re.match(r"^\s*\d+\. ", line):
            match = re.match(r"^\s*(\d+)\. (.*)", line)
            assert match
            story.append(Paragraph(match.group(1) + ". " + inline_markdown(match.group(2)), styles["ManualBody"]))
            index += 1
            continue
        paragraph = [line.strip()]
        index += 1
        while index < len(lines):
            next_line = lines[index]
            if (
                not next_line.strip()
                or next_line.strip() == "---"
                or next_line.startswith("#")
                or next_line.strip().startswith("|")
                or next_line.strip().startswith("```")
                or re.match(r"^\s*(- |\d+\. |> )", next_line)
            ):
                break
            paragraph.append(next_line.strip())
            index += 1
        story.append(Paragraph(inline_markdown(" ".join(paragraph)), styles["ManualBody"]))

    cover = [
        Spacer(1, 43 * mm),
        Paragraph("HealthZIP<br/>使用手册", styles["ManualTitle"]),
        Paragraph("Apple Health 本地整理、每日增量同步与力量记录", styles["ManualSubtitle"]),
        Spacer(1, 13 * mm),
        Paragraph(
            "从一次性 ZIP 导入开始，让 iPhone 通过 Health Auto Export 每日把新增数据送到本机，再在网页中查看质量、趋势和训练记录。",
            ParagraphStyle(
                "ManualLead",
                parent=styles["ManualBody"],
                alignment=TA_CENTER,
                fontSize=11,
                leading=18,
            ),
        ),
        Spacer(1, 35 * mm),
        Paragraph("本地优先 - 版本 1.0 - 2026-11-08", styles["ManualSmall"]),
        PageBreak(),
    ]
    return cover + story


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        rightMargin=17 * mm,
        leftMargin=17 * mm,
        topMargin=16 * mm,
        bottomMargin=21 * mm,
        title="HealthZIP 使用手册",
        author="HealthZIP",
    )
    document.build(build_story(), onFirstPage=footer, onLaterPages=footer)
    print(f"{OUTPUT} ({OUTPUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
