from pathlib import Path
import re, sys
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, LongTable, TableStyle, Preformatted, PageBreak, KeepTogether, HRFlowable

ROOT=Path(__file__).resolve().parents[1]
MD=ROOT/'DESIGN_SPEC.md'
OUT=ROOT/'DESIGN_SPEC.pdf'
FONT='STSong-Light'
pdfmetrics.registerFont(UnicodeCIDFont(FONT))

styles=getSampleStyleSheet()
styles.add(ParagraphStyle(name='BodyCN',fontName=FONT,fontSize=8.7,leading=13.2,textColor=colors.HexColor('#243447'),spaceAfter=5,wordWrap='CJK'))
styles.add(ParagraphStyle(name='H1CN',fontName=FONT,fontSize=19,leading=24,textColor=colors.HexColor('#16324F'),spaceBefore=11,spaceAfter=9,keepWithNext=True,wordWrap='CJK'))
styles.add(ParagraphStyle(name='H2CN',fontName=FONT,fontSize=13.2,leading=18,textColor=colors.HexColor('#087F8C'),spaceBefore=9,spaceAfter=5,keepWithNext=True,wordWrap='CJK'))
styles.add(ParagraphStyle(name='H3CN',fontName=FONT,fontSize=10.5,leading=15,textColor=colors.HexColor('#16324F'),spaceBefore=7,spaceAfter=4,keepWithNext=True,wordWrap='CJK'))
styles.add(ParagraphStyle(name='SmallCN',fontName=FONT,fontSize=7.4,leading=10,textColor=colors.HexColor('#526170'),spaceAfter=3,wordWrap='CJK'))
styles.add(ParagraphStyle(name='CodeCN',fontName=FONT,fontSize=7.1,leading=9.6,textColor=colors.HexColor('#1E3448'),backColor=colors.HexColor('#F2F6F8'),borderColor=colors.HexColor('#D9E4EA'),borderWidth=.4,borderPadding=5,spaceBefore=3,spaceAfter=6,wordWrap='CJK'))
styles.add(ParagraphStyle(name='TableCN',fontName=FONT,fontSize=7.1,leading=9.5,textColor=colors.HexColor('#243447'),wordWrap='CJK'))
styles.add(ParagraphStyle(name='TableHeadCN',fontName=FONT,fontSize=7.2,leading=9.5,textColor=colors.white,wordWrap='CJK'))
styles.add(ParagraphStyle(name='TitleCN',fontName=FONT,fontSize=25,leading=33,textColor=colors.HexColor('#16324F'),alignment=TA_CENTER,spaceAfter=12,wordWrap='CJK'))


def inline_md(s):
    s=s.replace('VO₂','VO2').replace('vo₂','vo2').replace('kg·min','kg*min').replace('·','*').replace('°C','deg C').replace('°',' deg ').replace('×','x')
    s=escape(s)
    # restore inline code and bold in a deliberately small markdown subset
    s=re.sub(r'`([^`]+)`',r'<font name="STSong-Light" backColor="#EEF3F6">\1</font>',s)
    s=re.sub(r'\*\*(.+?)\*\*',r'<b>\1</b>',s)
    s=re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)',r'<i>\1</i>',s)
    return s

def split_table_row(line):
    s=line.strip()
    if s.startswith('|'): s=s[1:]
    if s.endswith('|'): s=s[:-1]
    return [c.strip() for c in s.split('|')]

def footer(canvas, doc):
    canvas.saveState()
    w,h=A4
    canvas.setStrokeColor(colors.HexColor('#D7E1E8'))
    canvas.setLineWidth(.4)
    canvas.line(17*mm,15*mm,w-17*mm,15*mm)
    canvas.setFont(FONT,7)
    canvas.setFillColor(colors.HexColor('#647482'))
    canvas.drawString(17*mm,9*mm,'Health ZIP Workbench · 开发设计说明书 v1.0')
    canvas.drawRightString(w-17*mm,9*mm,f'{doc.page}')
    canvas.restoreState()

story=[]
lines=MD.read_text(encoding='utf-8').splitlines()
i=0
in_code=False
code=[]
while i<len(lines):
    line=lines[i]
    if line.strip().startswith('```'):
        if not in_code:
            in_code=True; code=[]
        else:
            txt='\n'.join(code)
            story.append(Preformatted(txt,styles['CodeCN'],maxLineLength=105))
            in_code=False;code=[]
        i+=1;continue
    if in_code:
        code.append(line);i+=1;continue
    if not line.strip():
        i+=1;continue
    if line.strip()=='---':
        story.append(Spacer(1,3));story.append(HRFlowable(width='100%',thickness=.45,color=colors.HexColor('#D7E1E8')));story.append(Spacer(1,5));i+=1;continue
    # Markdown table: header + separator + body
    if line.lstrip().startswith('|') and i+1<len(lines) and re.match(r'^\s*\|?\s*:?-{2,}',lines[i+1]):
        raw=[]
        raw.append(split_table_row(line));i+=2
        while i<len(lines) and lines[i].strip().startswith('|'):
            raw.append(split_table_row(lines[i]));i+=1
        n=max(len(r) for r in raw)
        data=[]
        for ri,row in enumerate(raw):
            row=row+['']*(n-len(row))
            sty='TableHeadCN' if ri==0 else 'TableCN'
            data.append([Paragraph(inline_md(c),styles[sty]) for c in row])
        avail=A4[0]-34*mm
        # Equal widths, slightly favour first/last columns for readability
        widths=[avail/n]*n
        if n==2: widths=[avail*.27,avail*.73]
        elif n==3: widths=[avail*.22,avail*.39,avail*.39]
        elif n==4: widths=[avail*.22,avail*.25,avail*.27,avail*.26]
        elif n>=5: widths=[avail/n]*n
        tbl=LongTable(data,colWidths=widths,repeatRows=1,hAlign='LEFT',splitByRow=1)
        tbl.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#16324F')),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#F2F6F8')]),
            ('GRID',(0,0),(-1,-1),.35,colors.HexColor('#D7E1E8')),
            ('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LEFTPADDING',(0,0),(-1,-1),4),('RIGHTPADDING',(0,0),(-1,-1),4),
            ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4),
        ]))
        story.append(Spacer(1,3));story.append(tbl);story.append(Spacer(1,6));continue
    if line.startswith('# '):
        story.append(Paragraph(inline_md(line[2:]),styles['TitleCN']));i+=1;continue
    if line.startswith('## '):
        story.append(Paragraph(inline_md(line[3:]),styles['H1CN']));i+=1;continue
    if line.startswith('### '):
        story.append(Paragraph(inline_md(line[4:]),styles['H2CN']));i+=1;continue
    if line.startswith('#### '):
        story.append(Paragraph(inline_md(line[5:]),styles['H3CN']));i+=1;continue
    if line.startswith('> '):
        story.append(Paragraph('<i>'+inline_md(line[2:])+'</i>',styles['SmallCN']));i+=1;continue
    if re.match(r'^\s*- \[ \] ',line):
        line=re.sub(r'^\s*- \[ \] ','- ',line)
    if re.match(r'^\s*- ',line):
        story.append(Paragraph('- '+inline_md(line.strip()[2:]),styles['BodyCN']));i+=1;continue
    if re.match(r'^\s*\d+\. ',line):
        m=re.match(r'^\s*(\d+)\. (.*)',line)
        story.append(Paragraph(m.group(1)+'. '+inline_md(m.group(2)),styles['BodyCN']));i+=1;continue
    # merge wrapped paragraph lines until blank / block start
    para=[line.strip()];i+=1
    while i<len(lines):
        nxt=lines[i]
        if (not nxt.strip() or nxt.strip()=='---' or nxt.startswith('#') or nxt.strip().startswith('|') or nxt.strip().startswith('```') or re.match(r'^\s*(- |\d+\. |\> )',nxt)):
            break
        para.append(nxt.strip());i+=1
    story.append(Paragraph(inline_md(' '.join(para)),styles['BodyCN']))

# Cover page inserted at front
cover=[Spacer(1,45*mm),Paragraph('Apple Health ZIP<br/>离线整理与分析工具',styles['TitleCN']),Paragraph('开发设计说明书 · Codex 实施版',ParagraphStyle('Sub',parent=styles['H2CN'],alignment=TA_CENTER,fontSize=13,leading=20)),Spacer(1,12*mm),Paragraph('先把 Apple Health 导出 ZIP 的数据解析、质量检查、整理、分析和解释跑通。<br/>暂不接入 HealthKit，不开发 iPhone / Watch App，不做精美前端。',ParagraphStyle('Lead',parent=styles['BodyCN'],alignment=TA_CENTER,fontSize=11,leading=18)),Spacer(1,35*mm),Paragraph('版本 1.0　|　2026-11-04',ParagraphStyle('Meta',parent=styles['SmallCN'],alignment=TA_CENTER,fontSize=9)),PageBreak()]
story=cover+story

doc=SimpleDocTemplate(str(OUT),pagesize=A4,rightMargin=17*mm,leftMargin=17*mm,topMargin=16*mm,bottomMargin=21*mm,title='Apple Health ZIP 离线整理与分析工具 — 开发设计说明书',author='')
doc.build(story,onFirstPage=footer,onLaterPages=footer)
print(OUT,OUT.stat().st_size)
