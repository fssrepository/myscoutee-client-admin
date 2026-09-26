#!/usr/bin/env python3
"""Documentation build only; reportlab is not an installed-app dependency."""
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
root = Path(__file__).resolve().parents[1]
styles = getSampleStyleSheet()
styles['BodyText'].fontSize = 9
styles['BodyText'].leading = 13
styles['Title'].textColor = colors.HexColor('#244e92')
flow, rows = [], []
def paragraph(text, style='BodyText'):
    return Paragraph(escape(text.replace('`', '').replace('**', '')), styles[style])
def flush_table():
    if not rows: return
    table = Table([[paragraph(cell) for cell in row] for row in rows], colWidths=[176, 332], repeatRows=1, hAlign='LEFT')
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e1ebfa')),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f5f8fc')]),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
    flow.extend([table, Spacer(1,8)]);rows.clear()
for line in (root/'docs/admin-client-api.md').read_text().splitlines():
    if line.startswith('|'):
        if not line.startswith('| ---'): rows.append([part.strip() for part in line.strip('|').split('|')])
        continue
    flush_table()
    if not line.strip(): flow.append(Spacer(1,6));continue
    style='Title' if line.startswith('# ') else 'Heading2' if line.startswith('## ') else 'BodyText'
    flow.append(paragraph(line.lstrip('# '),style))
flush_table()
def footer(canvas, document):
    canvas.setFont('Helvetica',8);canvas.setFillColor(colors.HexColor('#637087'))
    canvas.drawString(44,25,'MyScoutee Admin Client 1.3.0 · Private API')
    canvas.drawRightString(552,25,str(document.page))
SimpleDocTemplate(str(root/'docs/admin-client-api.pdf'),rightMargin=44,leftMargin=44,topMargin=38,bottomMargin=42,
                  title='MyScoutee Admin Client API 1.3.0',author='MyScoutee').build(flow,onFirstPage=footer,onLaterPages=footer)
