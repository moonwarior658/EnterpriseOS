"""Excel/PDF presentation of already-authorized EOS analytics; no provider calls."""
from decimal import Decimal
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, TableStyle
from app.supply.iiko_document_pdf import _register_fonts

LABELS = {'revenue': 'Выручка', 'check_count': 'Чеки', 'average_check': 'Средний чек', 'fullness': 'Наполняемость'}
STATUS = {'green': 'Цель выполнена', 'warning': 'Небольшое отставание', 'red': 'Ниже 85% цели', 'no_target': 'Нет цели', 'no_data': 'Нет чеков', 'mixed_targets': 'Разные цели'}


def metric_rows(objects, name_key):
    result = [['Объект', 'Показатель', 'Факт', 'Цель', 'Выполнение %', 'Пред. период', 'Изменение', 'Изменение %', 'Оценка']]
    for obj in objects:
        for key, label in LABELS.items():
            m = obj['metrics'][key]
            result.append([obj.get(name_key, 'Сеть'), label, *[Decimal(m[n]) if m.get(n) is not None else None
                for n in ('fact', 'target', 'completion_percent', 'previous', 'change', 'change_percent')], STATUS[m['status']]])
        for seg in obj.get('target_segments', []) if len(obj.get('target_segments', [])) > 1 else []:
            for key in ('average_check', 'fullness'):
                m = seg['metrics'][key]
                result.append([obj.get(name_key, 'Сеть'), f"{LABELS[key]} {seg['start']}–{seg['end']}",
                    *[Decimal(m[n]) if m.get(n) is not None else None for n in ('fact', 'target', 'completion_percent', 'previous', 'change', 'change_percent')], STATUS[m['status']]])
    return result


def export_tables(data, *, view, metadata):
    tables = [('Период и фильтры', [['Параметр', 'Значение'], *[[k, str(v)] for k, v in metadata.items()]])]
    coverage = data['completeness']
    tables[0][1].extend([['Полнота', 'Неполные данные; сравнение предварительное' if coverage['warning'] else 'Полные данные'],
                         ['Не загружено дней', len(coverage['current']['missing_dates'] + coverage['previous']['missing_dates'])]])
    missing = coverage['current']['missing_dates'] + coverage['previous']['missing_dates']
    tables[0][1].extend(['Не загруженные даты', ', '.join(missing[i:i+10])] for i in range(0, len(missing), 10))
    if data.get('status'):
        tables[0][1].extend([['Обновлено', str(data['status'].get('last_success_at') or 'Ещё нет обновления')],
                            ['Устарели', 'Да' if data['status']['stale'] else 'Нет'], ['Ошибка обновления', 'Да' if data['status']['update_failed'] else 'Нет']])
    if view in ('overview', 'points', 'sellers', 'report') and data.get('analytics'):
        tables.append(('Итоги', metric_rows([data['analytics']], 'name')))
    if view in ('overview', 'points', 'report') and data.get('points') is not None:
        tables.append(('Точки', metric_rows(data['points'], 'department_name')))
    if view in ('overview', 'points', 'sellers', 'report') and data.get('sellers') is not None:
        tables.append(('Продавцы', metric_rows(data['sellers'], 'employee_name')))
    if data.get('products') is not None:
        products = data['products']
        headers = ['Позиция', 'Категория', 'Точка', 'Количество', 'Выручка', 'Пред. количество', 'Пред. выручка', 'Чеки', 'Изменение выручки']
        rows = [headers]
        for p in products['products']:
            rows.append([p['product_name'] or 'Без названия', p['category'] or 'Без категории', p['department_name'] or 'Без названия',
                Decimal(p['quantity']), Decimal(p['revenue']), Decimal(p['previous_quantity']), Decimal(p['previous_revenue']), p['check_count'], Decimal(p['revenue']) - Decimal(p['previous_revenue'])])
        tables.append(('Продукция', rows))
        changes = data.get('product_changes')
        if changes:
            for key, label in [('growth', 'Рост продукции'), ('decline', 'Просадки продукции')]:
                tables.append((label, [['Позиция', 'Выручка', 'Пред. выручка', 'Изменение'],
                    *[[p['product_name'] or 'Без названия', Decimal(p['revenue']), Decimal(p['previous_revenue']), Decimal(p['revenue_change'])] for p in changes[key]]]))
    return tables


def _cell(value, ref, style):
    if value is None:
        return f'<c r="{ref}" s="{style}"/>'
    if isinstance(value, (int, Decimal)) and len(str(value).replace('.', '').replace('-', '')) <= 15:
        return f'<c r="{ref}" s="2"><v>{value}</v></c>'
    # inline strings prevent formula injection; large exact decimals remain text.
    value = ''.join(c for c in str(value) if c in '\n\t\r' or ord(c) >= 32)
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{escape(value)}</t></is></c>'


def excel(tables):
    buf = BytesIO()
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    with ZipFile(buf, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>' + ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, len(tables)+1)) + '</Types>')
        archive.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr('xl/workbook.xml', f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' + ''.join(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>' for i,(name,_) in enumerate(tables,1)) + '</sheets></workbook>')
        archive.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + ''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1,len(tables)+1)) + '<Relationship Id="styles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        archive.writestr('xl/styles.xml', f'<styleSheet xmlns="{ns}"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="3"><xf fontId="0" fillId="0" borderId="0" xfId="0"><alignment vertical="top" wrapText="1"/></xf><xf fontId="1" fillId="0" borderId="0" xfId="0"><alignment wrapText="1"/></xf><xf numFmtId="4" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
        for i, (_, rows) in enumerate(tables,1):
            cols = ''.join(f'<col min="{c+1}" max="{c+1}" width="{32 if c < 2 else 20}" customWidth="1"/>' for c in range(len(rows[0])))
            content = ''.join(f'<row r="{r}">' + ''.join(_cell(v, f'{chr(65+c)}{r}', 1 if r == 1 else 0) for c,v in enumerate(row)) + '</row>' for r,row in enumerate(rows,1))
            archive.writestr(f'xl/worksheets/sheet{i}.xml', f'<worksheet xmlns="{ns}"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols>{cols}</cols><sheetData>{content}</sheetData><autoFilter ref="A1:{chr(64+len(rows[0]))}{len(rows)}"/></worksheet>')
    return buf.getvalue()


def pdf(tables):
    regular, bold = _register_fonts()
    style = ParagraphStyle('sales', fontName=regular, fontSize=8, leading=11, splitLongWords=True)
    heading = ParagraphStyle('heading', parent=style, fontName=bold, fontSize=12, leading=16, spaceAfter=8, keepWithNext=True)
    buf = BytesIO(); document = SimpleDocTemplate(buf, pagesize=landscape(A4), rightMargin=28, leftMargin=28, topMargin=28, bottomMargin=28)
    story = [Paragraph('Статистика продаж EnterpriseOS', heading)]
    for title, rows in tables:
        story.extend([Spacer(1, 12), Paragraph(escape(title), heading)])
        if len(rows) == 1:
            story.append(Paragraph('Нет данных за выбранный период', style))
            continue
        def text(value):
            return escape('—' if value is None else format(value, '.2f') if isinstance(value, Decimal) else str(value)).replace('\n', '<br/>')
        widths = [document.width / len(rows[0])] * len(rows[0])
        if len(widths) > 4:
            widths = [document.width*.18, document.width*.15] + [document.width*.67/(len(widths)-2)]*(len(widths)-2)
        table = LongTable([[Paragraph(text(v), style) for v in row] for row in rows], colWidths=widths, repeatRows=1)
        table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#edf0f3')), ('VALIGN',(0,0),(-1,-1),'TOP'), ('GRID',(0,0),(-1,-1),.25,colors.HexColor('#dce0e5')), ('LEFTPADDING',(0,0),(-1,-1),5), ('RIGHTPADDING',(0,0),(-1,-1),5)]))
        story.append(table)
    def footer(canvas, doc):
        canvas.setFont(regular, 8); canvas.drawRightString(document.pagesize[0]-28, 14, f'EnterpriseOS · {doc.page}')
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
