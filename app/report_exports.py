"""Professional Excel/PDF exports for the Trivox analytics dashboard."""
from __future__ import annotations

from io import BytesIO
from urllib.parse import urlparse

import xlsxwriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

BRAND = "#075E66"
BRAND_DARK = "#12333B"
ACCENT = "#15A38C"
BG = "#F4F7F8"
TEXT = "#17242A"
MUTED = "#66747B"
LINE = "#DDE6E8"
RED = "#D9534F"


def _fmt_int(value):
    try:
        return f"{int(value or 0):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "0"


def _fmt_pct(value):
    if value is None:
        return "-"
    return f"{float(value):.1f}%".replace(".", ",")


def _fmt_duration(seconds):
    seconds = max(0, int(seconds or 0))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


def _safe_domain(value):
    if not value:
        return "Direto / desconhecido"
    try:
        parsed = urlparse(value)
        return parsed.netloc or value[:60]
    except Exception:
        return str(value)[:60]


def build_excel_report(insights: dict, site_name: str = "Portal Trivox") -> bytes:
    """Return an .xlsx dashboard as bytes.

    Native Excel charts expose point values on hover in desktop/web Excel.
    """
    output = BytesIO()
    wb = xlsxwriter.Workbook(output, {"in_memory": True})
    wb.set_properties({
        "title": f"Relatório de audiência - {site_name}",
        "subject": "Dashboard analítico de audiência",
        "author": site_name,
        "company": site_name,
    })

    fmt = {
        "title": wb.add_format({"bold": True, "font_size": 22, "font_color": "#FFFFFF", "bg_color": BRAND_DARK, "align": "left", "valign": "vcenter"}),
        "subtitle": wb.add_format({"font_size": 10, "font_color": "#D9E6E8", "bg_color": BRAND_DARK, "align": "left", "valign": "vcenter"}),
        "section": wb.add_format({"bold": True, "font_size": 12, "font_color": TEXT, "bottom": 2, "bottom_color": BRAND}),
        "kpi_label": wb.add_format({"bold": True, "font_size": 9, "font_color": MUTED, "bg_color": "#FFFFFF", "align": "left", "valign": "vcenter"}),
        "kpi_value": wb.add_format({"bold": True, "font_size": 21, "font_color": TEXT, "bg_color": "#FFFFFF", "align": "left", "valign": "vcenter"}),
        "kpi_meta": wb.add_format({"font_size": 8, "font_color": MUTED, "bg_color": "#FFFFFF", "align": "left", "valign": "vcenter"}),
        "header": wb.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": BRAND, "border": 0, "align": "left"}),
        "cell": wb.add_format({"font_color": TEXT, "bg_color": "#FFFFFF", "bottom": 1, "bottom_color": LINE}),
        "cell_num": wb.add_format({"font_color": TEXT, "bg_color": "#FFFFFF", "bottom": 1, "bottom_color": LINE, "num_format": "#,##0"}),
        "cell_pct": wb.add_format({"font_color": TEXT, "bg_color": "#FFFFFF", "bottom": 1, "bottom_color": LINE, "num_format": "0.0%"}),
        "note": wb.add_format({"font_size": 8, "font_color": MUTED, "bg_color": BG, "text_wrap": True, "valign": "top"}),
        "estimate": wb.add_format({"bold": True, "font_size": 8, "font_color": "#9A5B00", "bg_color": "#FFF7E6", "bottom": 1, "bottom_color": LINE, "align": "center"}),
        "measured": wb.add_format({"bold": True, "font_size": 8, "font_color": ACCENT, "bg_color": "#EFFAF7", "bottom": 1, "bottom_color": LINE, "align": "center"}),
        "date": wb.add_format({"num_format": "dd/mm/yyyy", "font_color": TEXT, "bg_color": "#FFFFFF", "bottom": 1, "bottom_color": LINE}),
    }

    dash = wb.add_worksheet("Dashboard")
    daily = wb.add_worksheet("Dados Diários")
    content = wb.add_worksheet("Top Conteúdos")
    acquisition = wb.add_worksheet("Aquisição")

    for ws in (dash, daily, content, acquisition):
        ws.hide_gridlines(2)
        ws.set_tab_color(BRAND)

    # DASHBOARD
    dash.set_zoom(90)
    dash.set_column("A:A", 2.2)
    dash.set_column("B:M", 12)
    dash.set_row(0, 34)
    dash.set_row(1, 20)
    dash.merge_range("B1:M1", f"{site_name}  |  TRAFFIC OVERVIEW", fmt["title"])
    dash.merge_range("B2:M2", f"Período: {insights['start_date'].strftime('%d/%m/%Y')} a {insights['end_date'].strftime('%d/%m/%Y')}  •  Horário de Brasília", fmt["subtitle"])
    dash.set_row(2, 8)

    estimated_meta = "ESTIMADO • baseado nos pageviews" if insights.get("metrics_estimated") else "Medido pelo rastreamento interno"
    metrics_ok = insights.get("session_metrics_available")
    kpis = [
        ("Visualizações", insights.get("total", 0), _delta_label(insights.get("delta"))),
        ("Páginas acessadas", insights.get("distinct_pages", 0), "URLs distintas no período"),
        ("Sessões", insights.get("sessions") if metrics_ok else "-", estimated_meta if metrics_ok else "Sem dados no período"),
        ("Usuários", insights.get("users") if metrics_ok else "-", estimated_meta if metrics_ok else "Sem dados no período"),
        ("Duração média", _fmt_duration(insights.get("avg_duration")) if metrics_ok else "-", estimated_meta if metrics_ok else "Sem dados no período"),
        ("Páginas/sessão", f"{insights.get('pages_per_session', 0):.2f}" if metrics_ok else "-", estimated_meta if metrics_ok else "Sem dados no período"),
        ("Taxa de rejeição", _fmt_pct(insights.get("bounce_rate")) if metrics_ok else "-", estimated_meta if metrics_ok else "Sem dados no período"),
        ("Últimas 24h", insights.get("last_24h", 0), "Contagem móvel de pageviews"),
    ]
    starts = [("B", "D"), ("E", "G"), ("H", "J"), ("K", "M"), ("B", "D"), ("E", "G"), ("H", "J"), ("K", "M")]
    rows = [4, 4, 4, 4, 8, 8, 8, 8]
    for (label, value, meta), (c1, c2), row in zip(kpis, starts, rows):
        dash.merge_range(f"{c1}{row}:{c2}{row}", label.upper(), fmt["kpi_label"])
        dash.merge_range(f"{c1}{row+1}:{c2}{row+2}", value if isinstance(value, str) else int(value or 0), fmt["kpi_value"])
        dash.merge_range(f"{c1}{row+3}:{c2}{row+3}", meta, fmt["kpi_meta"])

    dash.merge_range("B13:M13", "EVOLUÇÃO DIÁRIA", fmt["section"])

    # Raw daily data first, for charts.
    headers = ["Data", "Visualizações", "Sessões", "Usuários", "Duração média (s)", "Páginas/sessão", "Rejeição (%)", "Fonte"]
    daily.write_row(0, 0, headers, fmt["header"])
    for idx, row in enumerate(insights.get("daily_series", []), start=1):
        from datetime import datetime as _dt
        dt = _dt.strptime(row["iso"], "%Y-%m-%d")
        daily.write_datetime(idx, 0, dt, fmt["date"])
        daily.write_number(idx, 1, row.get("pageviews", 0), fmt["cell_num"])
        daily.write_number(idx, 2, row.get("sessions", 0), fmt["cell_num"])
        daily.write_number(idx, 3, row.get("users", 0), fmt["cell_num"])
        daily.write_number(idx, 4, row.get("avg_duration", 0), fmt["cell_num"])
        daily.write_number(idx, 5, row.get("pages_per_session", 0), fmt["cell"])
        daily.write_number(idx, 6, (row.get("bounce_rate", 0) or 0) / 100, fmt["cell_pct"])
        daily.write(idx, 7, row.get("metric_source", "Medido"), fmt["estimate"] if row.get("metrics_estimated") else fmt["measured"])
    daily.set_column("A:A", 13)
    daily.set_column("B:G", 18)
    daily.set_column("H:H", 13)
    daily.freeze_panes(1, 1)
    daily.autofilter(0, 0, max(1, len(insights.get("daily_series", []))), len(headers) - 1)

    line = wb.add_chart({"type": "line"})
    count = len(insights.get("daily_series", []))
    if count:
        line.add_series({
            "name": "Visualizações",
            "categories": ["Dados Diários", 1, 0, count, 0],
            "values": ["Dados Diários", 1, 1, count, 1],
            "line": {"color": ACCENT, "width": 2.5},
            "marker": {"type": "circle", "size": 5, "border": {"color": ACCENT}, "fill": {"color": "#FFFFFF"}},
        })
        if insights.get("session_metrics_available"):
            line.add_series({
                "name": "Sessões",
                "categories": ["Dados Diários", 1, 0, count, 0],
                "values": ["Dados Diários", 1, 2, count, 2],
                "line": {"color": BRAND_DARK, "width": 2},
                "marker": {"type": "none"},
            })
    line.set_title({"name": "Tendência de audiência"})
    line.set_legend({"position": "bottom"})
    line.set_x_axis({"date_axis": True, "num_format": "dd/mm", "major_gridlines": {"visible": False}, "line": {"color": LINE}})
    line.set_y_axis({"major_gridlines": {"visible": True, "line": {"color": LINE}}, "line": {"none": True}})
    line.set_chartarea({"border": {"none": True}, "fill": {"color": "#FFFFFF"}})
    line.set_plotarea({"border": {"none": True}, "fill": {"color": "#FFFFFF"}})
    line.set_size({"width": 920, "height": 330})
    dash.insert_chart("B14", line, {"x_offset": 4, "y_offset": 4})

    dash.merge_range("B31:G31", "TOP PÁGINAS", fmt["section"])
    dash.merge_range("H31:M31", "TOP MATÉRIAS", fmt["section"])
    dash.write_row("B32", ["Página", "Views"], fmt["header"])
    dash.write_row("H32", ["Matéria", "Views"], fmt["header"])
    dash.merge_range("B32:F32", "Página", fmt["header"])
    dash.write("G32", "Views", fmt["header"])
    dash.merge_range("H32:L32", "Matéria", fmt["header"])
    dash.write("M32", "Views", fmt["header"])
    for i, row in enumerate(insights.get("top_pages", [])[:10], start=33):
        path, views = row[0], row[1]
        dash.merge_range(f"B{i}:F{i}", str(path)[:80], fmt["cell"])
        dash.write_number(i - 1, 6, int(views or 0), fmt["cell_num"])
    for i, row in enumerate(insights.get("top_posts", [])[:10], start=33):
        title = getattr(row, "title", row[1] if len(row) > 1 else "")
        views = getattr(row, "views", row[-1])
        dash.merge_range(f"H{i}:L{i}", str(title)[:90], fmt["cell"])
        dash.write_number(i - 1, 12, int(views or 0), fmt["cell_num"])

    note_text = (
        "Fonte: registros internos do Portal Trivox. Visualizações são pageviews gravados pelo servidor e podem incluir repetições/robôs. "
        "Os gráficos do Excel exibem valores ao passar o mouse sobre os pontos."
    )
    if insights.get("metrics_estimated"):
        model = insights.get("estimation_model", {})
        note_text += (
            f" Nos {insights.get('estimated_days_count', 0)} dia(s) sem rastreamento de sessão, as métricas são ESTIMADAS e identificadas na aba Dados Diários. "
            f"Modelo usado: {model.get('pages_per_session', 1.62):.2f} pág./sessão, {model.get('sessions_per_user', 1.22):.2f} sessões/usuário, "
            f"{_fmt_duration(model.get('avg_duration', 138))} de duração média e {model.get('bounce_rate', 64.0):.1f}% de rejeição. "
            "Quando existem dados medidos, o modelo é calibrado por eles."
        )
    else:
        note_text += " Sessões, usuários, duração e rejeição são métricas medidas pelo rastreamento interno."
    dash.merge_range("B45:M47", note_text, fmt["note"])
    dash.set_row(44, 20)
    dash.set_row(45, 20)
    dash.set_row(46, 20)
    dash.freeze_panes(3, 1)
    dash.set_landscape()
    dash.fit_to_pages(1, 2)
    dash.set_margins(0.25, 0.25, 0.35, 0.35)

    # TOP CONTENT sheet
    content.set_column("A:A", 5)
    content.set_column("B:B", 75)
    content.set_column("C:C", 14)
    content.write_row("A1", ["#", "Matérias mais acessadas", "Visualizações"], fmt["header"])
    for i, post in enumerate(insights.get("top_posts", []), start=1):
        content.write_number(i, 0, i, fmt["cell_num"])
        content.write(i, 1, getattr(post, "title", ""), fmt["cell"])
        content.write_number(i, 2, int(getattr(post, "views", 0) or 0), fmt["cell_num"])
    start_pages = max(24, len(insights.get("top_posts", [])) + 4)
    content.write_row(start_pages, 0, ["#", "Páginas mais acessadas", "Visualizações"], fmt["header"])
    for i, row in enumerate(insights.get("top_pages", []), start=1):
        content.write_number(start_pages + i, 0, i, fmt["cell_num"])
        content.write(start_pages + i, 1, row[0], fmt["cell"])
        content.write_number(start_pages + i, 2, int(row[1] or 0), fmt["cell_num"])

    # ACQUISITION sheet
    acquisition.set_column("A:A", 6)
    acquisition.set_column("B:B", 48)
    acquisition.set_column("C:C", 16)
    acquisition.write_row("A1", ["#", "Origem / referência", "Sessões"], fmt["header"])
    for i, row in enumerate(insights.get("top_referrers", []), start=1):
        acquisition.write_number(i, 0, i, fmt["cell_num"])
        acquisition.write(i, 1, _safe_domain(row[0]), fmt["cell"])
        acquisition.write_number(i, 2, int(row[1] or 0), fmt["cell_num"])
    dev_row = max(16, len(insights.get("top_referrers", [])) + 4)
    acquisition.write_row(dev_row, 0, ["Dispositivo", "Sessões", "%"], fmt["header"])
    total_sessions = max(1, int(insights.get("measured_sessions") or 0))
    for i, (device, value) in enumerate(insights.get("devices", {}).items(), start=1):
        acquisition.write(dev_row + i, 0, device, fmt["cell"])
        acquisition.write_number(dev_row + i, 1, int(value or 0), fmt["cell_num"])
        acquisition.write_number(dev_row + i, 2, int(value or 0) / total_sessions, fmt["cell_pct"])

    wb.close()
    output.seek(0)
    return output.getvalue()


def _delta_label(value):
    if value is None:
        return "Sem base para comparação"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f}% vs. período anterior".replace(".", ",")


def build_pdf_report(insights: dict, site_name: str = "Portal Trivox") -> bytes:
    output = BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=f"Relatório de audiência - {site_name}",
        author=site_name,
    )

    styles = {
        "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=18, leading=21, textColor=colors.white, alignment=TA_LEFT),
        "subtitle": ParagraphStyle("subtitle", fontName="Helvetica", fontSize=8.5, leading=11, textColor=colors.HexColor("#DDECEE")),
        "section": ParagraphStyle("section", fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=colors.HexColor(TEXT)),
        "kpi_l": ParagraphStyle("kpi_l", fontName="Helvetica-Bold", fontSize=7.5, leading=9, textColor=colors.HexColor(MUTED)),
        "kpi_v": ParagraphStyle("kpi_v", fontName="Helvetica-Bold", fontSize=17, leading=19, textColor=colors.HexColor(TEXT)),
        "kpi_m": ParagraphStyle("kpi_m", fontName="Helvetica", fontSize=7, leading=9, textColor=colors.HexColor(MUTED)),
        "body": ParagraphStyle("body", fontName="Helvetica", fontSize=8, leading=10, textColor=colors.HexColor(TEXT)),
        "small": ParagraphStyle("small", fontName="Helvetica", fontSize=7, leading=9, textColor=colors.HexColor(MUTED)),
        "right": ParagraphStyle("right", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=colors.HexColor(TEXT), alignment=TA_RIGHT),
    }

    story = []
    title_box = Table([
        [Paragraph(f"{site_name}  |  TRAFFIC OVERVIEW", styles["title"])],
        [Paragraph(f"Período: {insights['start_date'].strftime('%d/%m/%Y')} a {insights['end_date'].strftime('%d/%m/%Y')} • Horário de Brasília", styles["subtitle"])],
    ], colWidths=[landscape(A4)[0] - 24 * mm])
    title_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(BRAND_DARK)),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, 0), 9),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
        ("TOPPADDING", (0, 1), (-1, 1), 2),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
    ]))
    story += [title_box, Spacer(1, 7)]

    metrics_ok = insights.get("session_metrics_available")
    metric_meta = "ESTIMADO" if insights.get("metrics_estimated") else "Medido"
    kpis = [
        ("VISUALIZAÇÕES", _fmt_int(insights.get("total")), _delta_label(insights.get("delta"))),
        ("PÁGINAS", _fmt_int(insights.get("distinct_pages")), "URLs distintas"),
        ("SESSÕES", _fmt_int(insights.get("sessions")) if metrics_ok else "-", metric_meta if metrics_ok else "Sem dados"),
        ("USUÁRIOS", _fmt_int(insights.get("users")) if metrics_ok else "-", metric_meta if metrics_ok else "Sem dados"),
        ("DURAÇÃO MÉDIA", _fmt_duration(insights.get("avg_duration")) if metrics_ok else "-", metric_meta if metrics_ok else "Sem dados"),
        ("PÁGINAS/SESSÃO", f"{insights.get('pages_per_session', 0):.2f}" if metrics_ok else "-", metric_meta if metrics_ok else "Sem dados"),
        ("REJEIÇÃO", _fmt_pct(insights.get("bounce_rate")) if metrics_ok else "-", metric_meta if metrics_ok else "Sem dados"),
        ("ÚLTIMAS 24H", _fmt_int(insights.get("last_24h")), "Pageviews"),
    ]
    cards = []
    for label, value, meta in kpis:
        cards.append([Paragraph(label, styles["kpi_l"]), Paragraph(str(value), styles["kpi_v"]), Paragraph(meta, styles["kpi_m"])])
    rows = [[cards[i], cards[i+1], cards[i+2], cards[i+3]] for i in (0, 4)]
    kpi_table = Table(rows, colWidths=[64 * mm] * 4, rowHeights=[25 * mm, 25 * mm])
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), .5, colors.HexColor(LINE)),
        ("INNERGRID", (0, 0), (-1, -1), .5, colors.HexColor(LINE)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [kpi_table, Spacer(1, 8), Paragraph("EVOLUÇÃO DIÁRIA", styles["section"]), Spacer(1, 3)]

    # Compact table is more reliable than drawing a chart in PDF and keeps all values auditable.
    daily_rows = [["Data", "Visualizações", "Sessões", "Usuários", "Duração média", "Pág./sessão", "Rejeição", "Fonte"]]
    series = insights.get("daily_series", [])
    # PDF stays readable: use up to 31 most recent daily rows on the overview page.
    for row in series[-31:]:
        daily_rows.append([
            row.get("label_short", ""),
            _fmt_int(row.get("pageviews")),
            _fmt_int(row.get("sessions")) if metrics_ok else "-",
            _fmt_int(row.get("users")) if metrics_ok else "-",
            _fmt_duration(row.get("avg_duration")) if metrics_ok else "-",
            f"{row.get('pages_per_session', 0):.2f}" if metrics_ok else "-",
            _fmt_pct(row.get("bounce_rate")) if metrics_ok else "-",
            row.get("metric_source", "Medido") if metrics_ok else "-",
        ])
    daily_table = Table(daily_rows, repeatRows=1, colWidths=[24*mm, 31*mm, 26*mm, 26*mm, 34*mm, 31*mm, 31*mm, 25*mm])
    daily_table.setStyle(_pdf_table_style())
    story += [daily_table, Spacer(1, 8)]

    note = "Visualizações são pageviews registrados pelo servidor e podem incluir repetições/robôs. "
    if insights.get("metrics_estimated"):
        model = insights.get("estimation_model", {})
        note += (
            f"Nos {insights.get('estimated_days_count', 0)} dia(s) sem rastreamento de sessão, sessões, usuários, duração, páginas/sessão e rejeição são ESTIMADOS. "
            f"Modelo: {model.get('pages_per_session', 1.62):.2f} pág./sessão; {model.get('sessions_per_user', 1.22):.2f} sessões/usuário; "
            f"{_fmt_duration(model.get('avg_duration', 138))} de duração média; {model.get('bounce_rate', 64.0):.1f}% de rejeição. "
            "Quando há dados medidos, eles calibram o modelo."
        )
    elif insights.get("sessions_available"):
        note += "Sessões, usuários, duração e rejeição usam o rastreamento interno de sessões."
    story += [Paragraph(note, styles["small"]), PageBreak()]

    story += [Paragraph("CONTEÚDO MAIS ACESSADO", styles["section"]), Spacer(1, 4)]
    top_rows = [["#", "Matéria", "Visualizações"]]
    for i, post in enumerate(insights.get("top_posts", [])[:20], start=1):
        top_rows.append([str(i), Paragraph(str(getattr(post, "title", "")), styles["body"]), _fmt_int(getattr(post, "views", 0))])
    if len(top_rows) == 1:
        top_rows.append(["-", "Nenhuma matéria com acessos registrados.", "0"])
    top_table = Table(top_rows, repeatRows=1, colWidths=[12*mm, 220*mm, 35*mm])
    top_table.setStyle(_pdf_table_style())
    story += [top_table, Spacer(1, 10), Paragraph("PÁGINAS MAIS ACESSADAS", styles["section"]), Spacer(1, 4)]
    page_rows = [["#", "Página", "Visualizações"]]
    for i, (path, views) in enumerate(insights.get("top_pages", [])[:20], start=1):
        page_rows.append([str(i), Paragraph(str(path), styles["body"]), _fmt_int(views)])
    if len(page_rows) == 1:
        page_rows.append(["-", "Nenhuma página com acessos registrados.", "0"])
    page_table = Table(page_rows, repeatRows=1, colWidths=[12*mm, 220*mm, 35*mm])
    page_table.setStyle(_pdf_table_style())
    story += [page_table]

    if insights.get("sessions_available"):
        story += [Spacer(1, 10), Paragraph("AQUISIÇÃO E DISPOSITIVOS", styles["section"]), Spacer(1, 4)]
        acq_rows = [["Origem / referência", "Sessões"]]
        for ref, value in insights.get("top_referrers", [])[:12]:
            acq_rows.append([_safe_domain(ref), _fmt_int(value)])
        if len(acq_rows) == 1:
            acq_rows.append(["Direto / sem referência", "0"])
        acq = Table(acq_rows, repeatRows=1, colWidths=[210*mm, 45*mm])
        acq.setStyle(_pdf_table_style())
        story += [KeepTogether(acq)]

    doc.build(story)
    output.seek(0)
    return output.getvalue()


def _pdf_table_style():
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(BRAND)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor(TEXT)),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFA")]),
        ("GRID", (0, 0), (-1, -1), .35, colors.HexColor(LINE)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ALIGN", (-1, 1), (-1, -1), "RIGHT"),
    ])
