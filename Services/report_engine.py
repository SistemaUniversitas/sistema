"""
report_engine.py — Motor central de Generación de Reportes PDF institucionales
==============================================================================

Genera informes PDF con calidad institucional y estructura académica (estilo
IEEE) para el dashboard "Análisis Saber 11 – Saber Pro" de la Universidad de
San Buenaventura · Seccional Medellín.

Estructura del documento:
    Portada · Tabla de contenido (con marcadores y enlaces internos) ·
    1 Introducción · 2 Metodología · 3 Resultados · 4 Indicadores ·
    5 Estimadores · 6 Análisis e interpretación · 7 Conclusiones · 8 Referencias

Cada página lleva encabezado (logo + identidad) y pie (información institucional
+ "Página X de Y").  El índice se genera automáticamente y es navegable.

────────────────────────────────────────────────────────────────────────────
Elección de la librería PDF — ReportLab
────────────────────────────────────────────────────────────────────────────
Se evaluaron ReportLab, WeasyPrint y xhtml2pdf.  Se eligió **ReportLab** porque:

1. Portabilidad sin dependencias nativas.  El despliegue es Windows (desarrollo)
   → Linux (producción); ReportLab es Python puro (+ Pillow) y se comporta
   idéntico en ambos.  WeasyPrint exige librerías nativas (Pango/Cairo/GDK) de
   instalación compleja en Windows y peso adicional en el servidor; xhtml2pdf
   tiene soporte CSS pobre y mal manejo de imágenes/gráficos complejos.
2. Ya está integrado y probado con el pipeline de exportación de gráficos
   Plotly→PNG (kaleido) en alta resolución.
3. Cubre todos los requisitos: encabezados/pies repetidos por página, índice
   automático con números de página (TableOfContents en build de dos pasadas),
   marcadores PDF y navegación interna clicable (bookmarkPage + addOutlineEntry
   + anclas), numeración jerárquica de secciones y control fino de estilos.

Dependencias: reportlab, kaleido (exportar Plotly a PNG), pillow.
"""

from __future__ import annotations

import io
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
from reportlab.lib.colors import Color, HexColor, white
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as canvas_mod
from reportlab.platypus import (BaseDocTemplate, Frame, Image, KeepTogether,
                                LongTable, NextPageTemplate, PageBreak,
                                PageTemplate, Paragraph, Spacer, Table,
                                TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents

# ─────────────────────────────────────────────────────────────────────────────
# Identidad visual institucional — Universidad de San Buenaventura (naranja)
# ─────────────────────────────────────────────────────────────────────────────
USB_ORANGE   = HexColor("#E8730C")   # naranja institucional principal
USB_ORANGE_D = HexColor("#C25E08")   # naranja oscuro
USB_TBL_HDR  = HexColor("#ED7D31")   # encabezado de tablas
USB_TINT     = HexColor("#FBE7D5")   # relleno suave / zebra
USB_TINT_2   = HexColor("#FDF3EA")
INK          = HexColor("#1A1A1A")   # títulos fuertes / texto negro
BODY         = HexColor("#333333")   # cuerpo de texto
GRAY         = HexColor("#7F7F7F")   # secundario (pies/encabezados)
LINE_GRAY    = HexColor("#D9D9D9")
WHITE        = white

# Fondo oscuro del dashboard: las figuras se exportan con su tema original para
# conservar colores/leyendas/etiquetas y se enmarcan como tarjeta.
DARK_CARD = "#161B22"
DARK_BG   = "#0D1117"

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
# Logo vertical (sello + "UNIVERSIDAD DE SAN BUENAVENTURA") para la portada y
# logo horizontal (sello + nombre + "MEDELLÍN") para el encabezado.  Si no
# existen, se cae al placeholder logo_usb.png.
LOGO_PATH    = ASSETS_DIR / "logo_usb.png"
LOGO_COVER   = ASSETS_DIR / "USB_Logo.svg.png"
LOGO_HEADER  = ASSETS_DIR / "logo-usb-medellin.png"


def _logo(*candidates):
    for c in candidates:
        if c.exists():
            return c
    return None

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
HEADER_H = 18 * mm
FOOTER_H = 14 * mm
CONTENT_W = PAGE_W - 2 * MARGIN

# ─────────────────────────────────────────────────────────────────────────────
# CATÁLOGO UNIVERSAL DE COMPONENTES
# Cada sección = una página fuente.  `store` es el id del dcc.Store global
# (en app.py) donde la página publica su payload.  kind: kpi | figure |
# figure_multi | table.  Para integrar una página nueva basta añadir aquí su
# sección y que la página llame a publish_payload con esos ids.
# ─────────────────────────────────────────────────────────────────────────────
REPORT_SECTIONS = [
    {
        "id": "interuniv",
        "title": "Saber Pro · Interuniversitario",
        "store": "report-store-interuniv",
        "items": [
            {"id": "kpi_best_global",   "label": "Mejor Universidad (Global)",            "kind": "kpi"},
            {"id": "kpi_best_calc",     "label": "Mejor Universidad (Global Calculado)",  "kind": "kpi"},
            {"id": "kpi_diff",          "label": "Diferencia Máxima",                     "kind": "kpi"},
            {"id": "kpi_count",         "label": "Universidades Comparadas",              "kind": "kpi"},
            {"id": "fig_bar",           "label": "Gráfico de Barras por Competencia",     "kind": "figure"},
            {"id": "fig_radar",         "label": "Radares Comparativos por Pareja",       "kind": "figure_multi"},
            {"id": "table_exec",        "label": "Tabla Comparativa Ejecutiva",           "kind": "table"},
            {"id": "table_rank_global", "label": "Ranking de Universidades (Global)",     "kind": "table"},
            {"id": "table_rank_calc",   "label": "Ranking de Universidades (Global Calculado)", "kind": "table"},
        ],
    },
    {
        "id": "puntajes",
        "title": "Saber Pro · Puntajes Unificado",
        "store": "report-store-puntajes",
        "items": [
            {"id": "fig_aporte",        "label": "Aporte Institucional por Competencia y Año", "kind": "figure"},
            {"id": "kpi_aporte_global", "label": "Aporte Global Promedio",               "kind": "kpi"},
            {"id": "kpi_aporte_comp",   "label": "Mejor Competencia (Aporte)",           "kind": "kpi"},
            {"id": "kpi_aporte_anio",   "label": "Mejor Año (Aporte)",                   "kind": "kpi"},
        ],
    },
    {
        "id": "puntajes_mod",
        "title": "Saber Pro · Puntajes por Módulo",
        "store": "report-store-puntajes-mod",
        "items": [
            {"id": "kpi_total", "label": "Total registros",                  "kind": "kpi"},
            {"id": "fig_punt",  "label": "Puntajes por módulo",              "kind": "figure_multi"},
            {"id": "fig_desem", "label": "Nivel de desempeño por módulo",    "kind": "figure_multi"},
        ],
    },
    {
        "id": "puntajes_par",
        "title": "Saber Pro · Comparativa Saber 11 ↔ Saber Pro",
        "store": "report-store-puntajes-par",
        "items": [
            {"id": "table_corr", "label": "Relación de puntajes Saber 11 ↔ Saber Pro", "kind": "table"},
            {"id": "fig_trend",  "label": "Tendencia por cohorte por módulo",          "kind": "figure_multi"},
            {"id": "fig_delta",  "label": "Distribución del Δ (Saber Pro − Saber 11)",  "kind": "figure_multi"},
            {"id": "fig_scatter","label": "Detalle pareado por módulo (densidad)",      "kind": "figure_multi"},
            {"id": "fig_quint",  "label": "Matriz de transición por quintiles",         "kind": "figure_multi"},
            {"id": "fig_eng",    "label": "Transición de nivel de desempeño en inglés", "kind": "figure"},
        ],
    },
    {
        "id": "socio",
        "title": "Saber Pro · Socioeconómico",
        "store": "report-store-socio",
        "items": [
            {"id": "kpi_total",        "label": "Total estudiantes",       "kind": "kpi"},
            {"id": "kpi_col",          "label": "Estudiantes colombianos", "kind": "kpi"},
            {"id": "kpi_ext",          "label": "Estudiantes extranjeros", "kind": "kpi"},
            # Identificación y ubicación
            {"id": "fig_genero",       "label": "Distribución por género",                  "kind": "figure"},
            {"id": "fig_nac",          "label": "Nacionalidad (Colombianos vs Extranjeros)","kind": "figure"},
            {"id": "fig_edad",         "label": "Distribución por edad",                    "kind": "figure"},
            {"id": "fig_extranjeros",  "label": "Top 25 nacionalidades extranjeras",        "kind": "figure"},
            {"id": "fig_top10_depto_r","label": "Top 10 departamentos de residencia",       "kind": "figure"},
            {"id": "fig_top10_mcpio_r","label": "Top 10 municipios de residencia",          "kind": "figure"},
            {"id": "fig_top10_depto_p","label": "Top 10 departamentos de presentación",     "kind": "figure"},
            {"id": "fig_top10_mcpio_p","label": "Top 10 municipios de presentación",        "kind": "figure"},
            {"id": "fig_area",         "label": "Área de residencia",                       "kind": "figure"},
            # Información académica
            {"id": "fig_semestre",     "label": "Semestre cursando",                        "kind": "figure"},
            {"id": "fig_caracter",     "label": "Tipo de institución (Pública/Privada/Especial)", "kind": "figure"},
            {"id": "fig_nivel",        "label": "Nivel del programa",                       "kind": "figure"},
            {"id": "fig_metodo",       "label": "Método del programa",                      "kind": "figure"},
            {"id": "fig_nucleo",       "label": "Top 25 núcleos de pregrado",               "kind": "figure"},
            # Información familiar
            {"id": "fig_edu_padre",    "label": "Educación del padre",                      "kind": "figure"},
            {"id": "fig_edu_madre",    "label": "Educación de la madre",                    "kind": "figure"},
            {"id": "fig_ocu_padre",    "label": "Ocupación del padre",                      "kind": "figure"},
            {"id": "fig_ocu_madre",    "label": "Ocupación de la madre",                    "kind": "figure"},
            # Condiciones socioeconómicas
            {"id": "fig_computador",   "label": "Tiene computador",                         "kind": "figure"},
            {"id": "fig_internet",     "label": "Tiene internet",                           "kind": "figure"},
            {"id": "fig_estrato",      "label": "Distribución por estrato",                 "kind": "figure"},
            {"id": "fig_inse",         "label": "INSE individual",                          "kind": "figure"},
            {"id": "fig_nse",          "label": "Nivel socioeconómico (NSE)",               "kind": "figure"},
            {"id": "fig_origen",       "label": "Origen (valores detallados)",              "kind": "figure"},
            {"id": "fig_grupo",        "label": "Grupo de referencia",                      "kind": "figure"},
            {"id": "fig_top_inst",     "label": "Top instituciones",                        "kind": "figure"},
            {"id": "fig_top_prgm",     "label": "Top programas",                            "kind": "figure"},
            # Análisis cruzados de pago
            {"id": "fig_pago",         "label": "Formas de pago",                           "kind": "figure"},
            {"id": "fig_pago_hm",      "label": "Co-ocurrencia entre tipos de pago",        "kind": "figure"},
            {"id": "fig_estrato_pago", "label": "Estrato × Tipo de pago",                   "kind": "figure"},
        ],
    },
    {
        "id": "desercion",
        "title": "Deserción · No profesionalización",
        "store": "report-store-desercion",
        "items": [
            {"id": "kpi_total",      "label": "Presentaron Saber 11",            "kind": "kpi"},
            {"id": "kpi_nocoinc",    "label": "No coincidentes",                 "kind": "kpi"},
            {"id": "kpi_coinc",      "label": "Coincidentes",                    "kind": "kpi"},
            {"id": "kpi_tasa",       "label": "Tasa de profesionalización",      "kind": "kpi"},
            {"id": "kpi_trend",      "label": "Tendencia (pp/año)",              "kind": "kpi"},
            {"id": "fig_trend_line", "label": "Tendencia de no coincidencia por cohorte", "kind": "figure"},
            {"id": "fig_trend_delta","label": "Variación interanual",            "kind": "figure"},
            {"id": "fig_estrato",    "label": "No coincidentes por estrato",     "kind": "figure"},
            {"id": "fig_naturaleza", "label": "Naturaleza del colegio",          "kind": "figure"},
            {"id": "fig_area",       "label": "Zona del colegio",                "kind": "figure"},
            {"id": "fig_depto",      "label": "Top 10 departamentos",            "kind": "figure"},
            {"id": "fig_incert_anos","label": "Radio de incertidumbre · año de presentación", "kind": "figure"},
            {"id": "fig_incert_desv","label": "Radio de incertidumbre · desviación", "kind": "figure"},
        ],
    },
    {
        "id": "rna",
        "title": "RNA · Predicción Saber Pro",
        "store": "report-store-rna",
        "items": [
            {"id": "kpi_n",       "label": "Estudiantes",                "kind": "kpi"},
            {"id": "kpi_mae",     "label": "MAE",                        "kind": "kpi"},
            {"id": "kpi_rmse",    "label": "RMSE",                       "kind": "kpi"},
            {"id": "kpi_r2",      "label": "R²",                         "kind": "kpi"},
            {"id": "kpi_sesgo",   "label": "Sesgo medio",                "kind": "kpi"},
            {"id": "fig_scatter", "label": "Real vs Predicho",           "kind": "figure"},
            {"id": "fig_dist",    "label": "Distribución real vs predicho", "kind": "figure"},
            {"id": "fig_resid",   "label": "Distribución de residuales",  "kind": "figure"},
            {"id": "table_metrics","label": "Métricas por módulo",        "kind": "table"},
        ],
    },
    {
        "id": "probestrato",
        "title": "Probabilidad · Estrato",
        "store": "report-store-probestrato",
        "items": [
            {"id": "kpi_best",   "label": "Estrato más probable",  "kind": "kpi"},
            {"id": "kpi_prob",   "label": "Probabilidad máxima",   "kind": "kpi"},
            {"id": "kpi_n",      "label": "Registros analizados",  "kind": "kpi"},
            {"id": "fig_prob",   "label": "Probabilidad por estrato", "kind": "figure"},
            {"id": "table_prob", "label": "Tabla de probabilidades",  "kind": "table"},
        ],
    },
]

# KPIs que son ESTIMADORES (estimaciones estadísticas / de modelo), no simples
# indicadores descriptivos.  El resto de KPIs se tratan como indicadores.
ESTIMADOR_KEYS = {
    "rna::kpi_mae", "rna::kpi_rmse", "rna::kpi_r2", "rna::kpi_sesgo",
    "desercion::kpi_trend",
    "probestrato::kpi_best", "probestrato::kpi_prob",
}

_SECTION_BY_ID = {s["id"]: s for s in REPORT_SECTIONS}
_ITEM_BY_KEY = {
    f'{s["id"]}::{it["id"]}': {**it, "section_id": s["id"], "section_title": s["title"]}
    for s in REPORT_SECTIONS for it in s["items"]
}
STORE_IDS = [(s["store"], s["id"]) for s in REPORT_SECTIONS]


# Saneador de glifos: la fuente estándar Helvetica del PDF no incluye flechas,
# letras griegas ni el signo menos Unicode.  Se reemplazan por equivalentes
# seguros solo en el PDF (la interfaz web conserva los símbolos originales).
_GLYPH_MAP = {
    "↔": " vs ", "⇄": " vs ", "→": "->", "⟶": "->", "←": "<-", "⇒": "=>",
    "−": "-", "Δ": "Delta ", "∆": "Delta ", "ρ": "rho", "σ": "sigma",
    "≤": "<=", "≥": ">=", "≠": "!=", "√": "raiz",
}

def _safe(text):
    if text is None:
        return ""
    s = str(text)
    for k, v in _GLYPH_MAP.items():
        if k in s:
            s = s.replace(k, v)
    return s


# ─────────────────────────────────────────────────────────────────────────────
# Construcción de payloads (lo que cada página publica en su store)
# ─────────────────────────────────────────────────────────────────────────────
def kpi(label, value, sub=None):
    return {"kind": "kpi", "label": label,
            "value": "—" if value is None else str(value), "sub": sub}

def _compact_figure(fig):
    """Serializa la figura compactando las trazas pesadas (Histogram /
    Histogram2d, que guardan todos los valores por fila → MB) a su equivalente
    pre-binned (Bar / Heatmap, unos KB), visualmente idéntico, para que el
    payload quepa en sessionStorage (~5 MB).  Se opera sobre el objeto go.Figure
    porque Plotly serializa los arreglos grandes como base64.  Marca la figura
    como distribución para no añadirle etiquetas/métricas de categoría."""
    f = fig if isinstance(fig, go.Figure) else go.Figure(fig)
    new_data, converted = [], False
    for tr in f.data:
        t = getattr(tr, "type", None)
        if t == "histogram" and tr.x is not None:
            arr = np.asarray(tr.x, dtype="float64")
            arr = arr[~np.isnan(arr)]
            if arr.size:
                counts, edges = np.histogram(arr, bins=int(tr.nbinsx or 40))
                new_data.append(go.Bar(
                    x=((edges[:-1] + edges[1:]) / 2.0).tolist(), y=counts.tolist(),
                    width=float(edges[1] - edges[0]),
                    marker=tr.marker.to_plotly_json() if tr.marker else None,
                    name=tr.name, hovertemplate=tr.hovertemplate,
                    showlegend=tr.showlegend))
                converted = True
                continue
        elif t == "histogram2d" and tr.x is not None and tr.y is not None:
            ax = np.asarray(tr.x, dtype="float64"); ay = np.asarray(tr.y, dtype="float64")
            mm = ~(np.isnan(ax) | np.isnan(ay))
            ax, ay = ax[mm], ay[mm]
            if ax.size:
                H, xe, ye = np.histogram2d(ax, ay, bins=[int(tr.nbinsx or 50),
                                                          int(tr.nbinsy or 50)])
                new_data.append(go.Heatmap(
                    z=H.T.tolist(),
                    x=((xe[:-1] + xe[1:]) / 2.0).tolist(),
                    y=((ye[:-1] + ye[1:]) / 2.0).tolist(),
                    colorscale=tr.colorscale, showscale=tr.showscale,
                    hovertemplate=tr.hovertemplate, name=tr.name))
                converted = True
                continue
        new_data.append(tr)

    f2 = go.Figure(data=new_data, layout=f.layout)
    if converted:
        cur = getattr(f2.layout, "meta", None)
        meta = dict(cur) if isinstance(cur, dict) else {}
        meta["compact_dist"] = True
        f2.update_layout(meta=meta)
    return json.loads(f2.to_json())


def figure(label, fig, desc=None, metrics=True):
    return {"kind": "figure", "label": label, "desc": desc, "metrics": metrics,
            "figure": _compact_figure(fig)}

def figure_multi(label, figs, captions=None, desc=None):
    out = [_compact_figure(f) for f in figs]
    return {"kind": "figure_multi", "label": label, "desc": desc, "figures": out,
            "captions": list(captions) if captions else [""] * len(out)}

def table(label, columns, rows):
    return {"kind": "table", "label": label,
            "columns": list(columns), "rows": [list(r) for r in rows]}

def publish_payload(section_id, filters, items):
    return {"section_id": section_id,
            "title": _SECTION_BY_ID.get(section_id, {}).get("title", section_id),
            "filters": {k: ("—" if v in (None, "", []) else v) for k, v in (filters or {}).items()},
            "items": items or {},
            "ts": datetime.now().isoformat(timespec="seconds")}


# ─────────────────────────────────────────────────────────────────────────────
# Exportación de figuras Plotly → PNG de alta resolución (kaleido)
# Mejoras universales para impresión: fuentes legibles, valores sobre las
# barras/sectores y prevención de solape de etiquetas.  Se aplican a CUALQUIER
# figura sin lógica específica por gráfico (escalable a páginas futuras).
# ─────────────────────────────────────────────────────────────────────────────
def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _fmt_num(v, big):
    if not _num(v):
        return ""
    return f"{v:,.0f}" if big else (f"{v:.2f}" if abs(v) < 10 else f"{v:.1f}")


def _bar_axis_values(tr):
    """Devuelve (categorias, valores) de una traza de barras según orientación."""
    horiz = getattr(tr, "orientation", None) == "h"
    cats = list(tr.y) if horiz else list(tr.x)
    vals = list(tr.x) if horiz else list(tr.y)
    return cats or [], vals or [], horiz


def _enhance_for_print(fig):
    """Optimiza una figura para el PDF: fuentes mayores y legibles, leyendas
    claras y valores visibles sobre los elementos cuando es razonable."""
    fig.update_layout(
        paper_bgcolor=DARK_CARD, plot_bgcolor=DARK_BG,
        margin=dict(l=60, r=28, t=50, b=52),
        font=dict(family="Helvetica", size=14, color="#E6EDF3"),
        legend=dict(font=dict(size=12)),
        uniformtext=dict(minsize=8, mode="hide"),   # oculta etiquetas que no caben
    )
    try:
        fig.update_xaxes(title_font=dict(size=13), tickfont=dict(size=11), automargin=True)
        fig.update_yaxes(title_font=dict(size=13), tickfont=dict(size=11), automargin=True)
    except Exception:
        pass

    # Las distribuciones (histogramas compactados a barras) no llevan etiqueta
    # por barra: son demasiadas y no aportan.
    meta = getattr(fig.layout, "meta", None)
    is_dist = isinstance(meta, dict) and meta.get("compact_dist")

    bar_traces = [t for t in fig.data if getattr(t, "type", None) == "bar"]
    single_bar = len(bar_traces) == 1   # solo etiquetar barras de serie única
    for tr in fig.data:
        ttype = getattr(tr, "type", None)
        if ttype == "bar" and single_bar and not is_dist:
            _cats, vals, horiz = _bar_axis_values(tr)
            nums = [v for v in vals if _num(v)]
            big = bool(nums) and max(abs(v) for v in nums) >= 100
            tr.text = [_fmt_num(v, big) for v in vals]
            tr.texttemplate = "%{text}"
            tr.textposition = "outside"
            tr.textfont = dict(size=10)
            tr.cliponaxis = False
        elif ttype == "pie":
            if not getattr(tr, "textinfo", None) or tr.textinfo == "none":
                tr.textinfo = "label+percent"
            tr.textfont = dict(size=11)
            tr.insidetextorientation = "radial"
    return fig


def _render_size(fig_dict, base_w=1000, base_h=540):
    """Tamaño de render adaptado: las barras horizontales con muchas categorías
    necesitan más alto para no encimarse."""
    w, h = base_w, base_h
    try:
        fig = go.Figure(fig_dict)
        for tr in fig.data:
            if getattr(tr, "type", None) == "bar" and getattr(tr, "orientation", None) == "h":
                n = len(tr.y) if tr.y is not None else 0
                h = max(h, min(1300, 150 + n * 24))
    except Exception:
        pass
    return w, h


def _fig_to_png(fig_dict, width=1000, height=540, scale=3):
    fig = go.Figure(fig_dict)
    _enhance_for_print(fig)
    return fig.to_image(format="png", width=width, height=height,
                        scale=scale, engine="kaleido")


def _figure_metrics_rows(fig_dict):
    """Deriva métricas resumen (total/promedio/máx/mín/participación) de los
    datos de una figura de barras o torta.  Devuelve (columns, rows) o None."""
    try:
        fig = go.Figure(fig_dict)
    except Exception:
        return None
    # Las distribuciones (histogramas compactados) no llevan tabla de métricas
    # de categorías (total/promedio/máx/mín no aplican a bins).
    meta = getattr(fig.layout, "meta", None)
    if isinstance(meta, dict) and meta.get("compact_dist"):
        return None
    traces = list(fig.data)
    if not traces:
        return None

    pies = [t for t in traces if getattr(t, "type", None) == "pie"]
    if pies:
        tr = pies[0]
        labels = list(tr.labels) if tr.labels is not None else []
        values = [float(v) for v in (tr.values or []) if _num(v)]
        if not values:
            return None
        total = sum(values)
        imax = max(range(len(values)), key=lambda i: values[i])
        imin = min(range(len(values)), key=lambda i: values[i])
        rows = [
            ["Total", f"{total:,.0f}"],
            ["Categorías", str(len(values))],
            ["Mayor participación",
             f"{labels[imax] if imax < len(labels) else '—'} · {values[imax]/total*100:.1f}%" if total else "—"],
            ["Menor participación",
             f"{labels[imin] if imin < len(labels) else '—'} · {values[imin]/total*100:.1f}%" if total else "—"],
        ]
        return ["Métrica", "Valor"], rows

    bars = [t for t in traces if getattr(t, "type", None) == "bar"]
    if len(bars) == 1:
        cats, vals, _ = _bar_axis_values(bars[0])
        pairs = [(c, float(v)) for c, v in zip(cats, vals) if _num(v)]
        if not pairs:
            return None
        total = sum(v for _, v in pairs)
        cmax = max(pairs, key=lambda kv: kv[1])
        cmin = min(pairs, key=lambda kv: kv[1])
        prom = total / len(pairs)
        big = total >= 1000 or any(v >= 1000 for _, v in pairs)

        def f(v):
            return _fmt_num(v, big)
        rows = [
            ["Total", f(total)],
            ["Promedio", f(prom)],
            ["Máximo", f"{cmax[0]} · {f(cmax[1])}"],
            ["Mínimo", f"{cmin[0]} · {f(cmin[1])}"],
        ]
        return ["Métrica", "Valor"], rows
    return None


def _framed_image(png_bytes, max_w, render_w, render_h):
    """Imagen enmarcada como tarjeta (borde gris + fondo oscuro)."""
    ratio = render_h / float(render_w)
    w = max_w
    h = w * ratio
    img = Image(io.BytesIO(png_bytes), width=w, height=h)
    t = Table([[img]], colWidths=[w])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, LINE_GRAY),
        ("BACKGROUND", (0, 0), (-1, -1), HexColor(DARK_CARD)),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


# ─────────────────────────────────────────────────────────────────────────────
# Estilos de párrafo
# ─────────────────────────────────────────────────────────────────────────────
def _styles():
    ss = getSampleStyleSheet()
    s = {}
    s["h1"] = ParagraphStyle("h1", parent=ss["Heading1"], fontName="Helvetica-Bold",
                             fontSize=16, textColor=INK, spaceBefore=4, spaceAfter=10,
                             leading=19)
    s["h2"] = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold",
                             fontSize=12, textColor=USB_ORANGE_D, spaceBefore=10,
                             spaceAfter=6, leading=15)
    s["h3"] = ParagraphStyle("h3", parent=ss["Heading3"], fontName="Helvetica-Bold",
                             fontSize=10.5, textColor=INK, spaceBefore=6, spaceAfter=3,
                             leading=13)
    s["body"] = ParagraphStyle("body", parent=ss["BodyText"], fontName="Helvetica",
                               fontSize=9.7, textColor=BODY, leading=14.5,
                               alignment=TA_JUSTIFY, spaceAfter=6)
    s["bullet"] = ParagraphStyle("bullet", parent=s["body"], leftIndent=14,
                                 bulletIndent=2, spaceAfter=5, alignment=TA_LEFT)
    s["caption"] = ParagraphStyle("caption", parent=s["body"], fontSize=8.5,
                                  textColor=GRAY, alignment=TA_CENTER, spaceBefore=3,
                                  spaceAfter=12)
    s["kpi_label"] = ParagraphStyle("kpi_label", fontName="Helvetica", fontSize=7.3,
                                    textColor=GRAY, alignment=TA_CENTER, leading=9)
    s["kpi_value"] = ParagraphStyle("kpi_value", fontName="Helvetica-Bold", fontSize=13,
                                    textColor=USB_ORANGE_D, alignment=TA_CENTER, leading=15)
    s["kpi_sub"] = ParagraphStyle("kpi_sub", fontName="Helvetica", fontSize=6.8,
                                  textColor=GRAY, alignment=TA_CENTER, leading=8.5)
    s["cell"] = ParagraphStyle("cell", fontName="Helvetica", fontSize=8, textColor=INK,
                               leading=10)
    s["cell_b"] = ParagraphStyle("cell_b", fontName="Helvetica-Bold", fontSize=8,
                                 textColor=INK, leading=10)
    s["cell_h"] = ParagraphStyle("cell_h", fontName="Helvetica-Bold", fontSize=8,
                                 textColor=white, leading=10)
    s["fig_desc"] = ParagraphStyle("fig_desc", fontName="Helvetica-Oblique", fontSize=8.6,
                                   textColor=GRAY, leading=12, alignment=TA_LEFT, spaceAfter=4)
    s["toc0"] = ParagraphStyle("toc0", fontName="Helvetica-Bold", fontSize=10.5,
                               textColor=INK, leftIndent=6, firstLineIndent=-6,
                               spaceBefore=6, leading=15)
    s["toc1"] = ParagraphStyle("toc1", fontName="Helvetica", fontSize=9.5,
                               textColor=BODY, leftIndent=22, firstLineIndent=0,
                               spaceBefore=2, leading=13)
    return s


# ─────────────────────────────────────────────────────────────────────────────
# Encabezado de sección con registro en índice + marcador PDF
# ─────────────────────────────────────────────────────────────────────────────
class SectionHeading(Paragraph):
    """Título que además se registra en el índice y como marcador navegable."""
    _counter = 0

    def __init__(self, text, style, level, key, toc_text=None):
        text = _safe(text)
        super().__init__(text, style)
        self.toc_level = level
        self.toc_key = key
        self.toc_text = _safe(toc_text) if toc_text is not None else text


class ReportDoc(BaseDocTemplate):
    """BaseDocTemplate que alimenta el índice y crea marcadores/anclas."""

    def afterFlowable(self, flowable):
        if isinstance(flowable, SectionHeading):
            self.notify("TOCEntry",
                        (flowable.toc_level, flowable.toc_text, self.page, flowable.toc_key))
            self.canv.bookmarkPage(flowable.toc_key)
            self.canv.addOutlineEntry(flowable.toc_text, flowable.toc_key,
                                      level=flowable.toc_level,
                                      closed=(flowable.toc_level > 0))


# ─────────────────────────────────────────────────────────────────────────────
# Portada (PageTemplate 'cover')
# ─────────────────────────────────────────────────────────────────────────────
def _wrap_center(text, max_chars):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 <= max_chars:
            cur = (cur + " " + w).strip()
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines[:3] or [text]


def _draw_cover(canvas, doc):
    cx = PAGE_W / 2
    # Filo naranja superior (sobre fondo blanco).
    canvas.setFillColor(USB_ORANGE)
    canvas.rect(0, PAGE_H - 8 * mm, PAGE_W, 8 * mm, fill=1, stroke=0)

    # Logo institucional vertical (sello + nombre) centrado sobre blanco.
    logo = _logo(LOGO_COVER, LOGO_PATH)
    logo_top = PAGE_H - 20 * mm
    logo_h = 46 * mm
    if logo:
        try:
            canvas.drawImage(str(logo), cx - logo_h / 2, logo_top - logo_h,
                             width=logo_h, height=logo_h, mask="auto",
                             preserveAspectRatio=True)
        except Exception:
            pass

    # "Seccional Medellín" + "Sistema..." (el nombre ya viene en el logo).
    y = logo_top - logo_h - 4 * mm
    canvas.setFillColor(GRAY)
    canvas.setFont("Helvetica-Bold", 12)
    canvas.drawCentredString(cx, y, "Seccional Medellín")
    canvas.setFont("Helvetica-Oblique", 10.5)
    canvas.drawCentredString(cx, y - 6.5 * mm, "Sistema de Analítica Académica")
    canvas.setStrokeColor(USB_ORANGE)
    canvas.setLineWidth(1.5)
    canvas.line(cx - 55 * mm, y - 12.5 * mm, cx + 55 * mm, y - 12.5 * mm)

    # Tipo de documento.
    canvas.setFillColor(USB_ORANGE_D)
    canvas.setFont("Helvetica-Bold", 12.5)
    canvas.drawCentredString(cx, PAGE_H * 0.55, "REPORTE INSTITUCIONAL")
    canvas.setStrokeColor(USB_ORANGE)
    canvas.setLineWidth(1.3)
    canvas.line(cx - 48 * mm, PAGE_H * 0.53, cx + 48 * mm, PAGE_H * 0.53)

    # Título y subtítulo del reporte.
    title = (getattr(doc, "_report_title", "Reporte") or "Reporte").upper()
    subtitle = getattr(doc, "_report_subtitle", "") or ""
    canvas.setFillColor(INK)
    y = PAGE_H * 0.50
    for line in _wrap_center(title, 32):
        canvas.setFont("Helvetica-Bold", 21)
        canvas.drawCentredString(cx, y, line)
        y -= 11 * mm
    if subtitle:
        canvas.setFillColor(GRAY)
        canvas.setFont("Helvetica", 12)
        canvas.drawCentredString(cx, y - 1 * mm, subtitle)

    # Caja de metadatos (fecha / usuario), sin hora.
    info_y = 44 * mm
    canvas.setFillColor(USB_TINT)
    canvas.roundRect(cx - 72 * mm, info_y - 5 * mm, 144 * mm, 26 * mm, 3 * mm, fill=1, stroke=0)
    canvas.setStrokeColor(USB_ORANGE)
    canvas.setLineWidth(0.8)
    canvas.line(cx - 72 * mm, info_y + 21 * mm, cx + 72 * mm, info_y + 21 * mm)
    canvas.setFillColor(GRAY)
    canvas.setFont("Helvetica", 9)
    canvas.drawCentredString(cx, info_y + 13.5 * mm, "Fecha de generación")
    canvas.setFillColor(USB_ORANGE_D)
    canvas.setFont("Helvetica-Bold", 12)
    canvas.drawCentredString(cx, info_y + 7.5 * mm, getattr(doc, "_report_date", ""))
    user = getattr(doc, "_report_user", "")
    if user:
        canvas.setFillColor(GRAY)
        canvas.setFont("Helvetica", 8.5)
        canvas.drawCentredString(cx, info_y + 1.5 * mm, f"Generado por: {user}")

    # Franja inferior.
    canvas.setFillColor(USB_ORANGE)
    canvas.rect(0, 0, PAGE_W, 13 * mm, fill=1, stroke=0)
    canvas.setFillColor(USB_ORANGE_D)
    canvas.rect(0, 13 * mm, PAGE_W, 1.8 * mm, fill=1, stroke=0)
    canvas.setFillColor(white)
    canvas.setFont("Helvetica", 7.5)
    canvas.drawCentredString(
        cx, 5 * mm,
        "Análisis Saber 11 – Saber Pro · Documento de uso académico e institucional")


# ─────────────────────────────────────────────────────────────────────────────
# Canvas numerado: encabezado + pie en cada página de contenido (no en portada)
# ─────────────────────────────────────────────────────────────────────────────
class NumberedCanvas(canvas_mod.Canvas):
    _title = ""
    _date = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_states = []

    def showPage(self):
        self._saved_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_states)
        for state in self._saved_states:
            self.__dict__.update(state)
            if self._pageNumber > 1:           # la portada no lleva encabezado/pie
                self._draw_header()
                self._draw_footer(total)
            canvas_mod.Canvas.showPage(self)
        canvas_mod.Canvas.save(self)

    def _draw_header(self):
        self.saveState()
        band = HEADER_H
        # Banner institucional horizontal (sello + nombre + MEDELLÍN) a la izq.
        logo = _logo(LOGO_HEADER, LOGO_PATH)
        if logo:
            try:
                lh = 12 * mm
                lw = lh * 2.355 if logo == LOGO_HEADER else lh   # respeta proporción
                self.drawImage(str(logo), MARGIN, PAGE_H - band + (band - lh) / 2,
                               width=lw, height=lh, mask="auto",
                               preserveAspectRatio=True)
            except Exception:
                pass
        # Lado derecho: título del reporte + subtítulo institucional.
        self.setFillColor(GRAY)
        self.setFont("Helvetica-BoldOblique", 8.3)
        self.drawRightString(PAGE_W - MARGIN, PAGE_H - band + 9.5 * mm,
                             NumberedCanvas._title[:58])
        self.setFont("Helvetica", 7)
        self.drawRightString(PAGE_W - MARGIN, PAGE_H - band + 5 * mm,
                             "Sistema de Analítica Académica")
        # Filo naranja inferior del encabezado.
        self.setStrokeColor(USB_ORANGE)
        self.setLineWidth(1.3)
        self.line(MARGIN, PAGE_H - band, PAGE_W - MARGIN, PAGE_H - band)
        self.restoreState()

    def _draw_footer(self, total):
        self.saveState()
        self.setStrokeColor(USB_ORANGE)
        self.setLineWidth(0.7)
        self.line(MARGIN, FOOTER_H - 1 * mm, PAGE_W - MARGIN, FOOTER_H - 1 * mm)
        self.setFillColor(GRAY)
        self.setFont("Helvetica", 7.3)
        self.drawString(MARGIN, FOOTER_H - 5.5 * mm,
                        "Análisis Saber 11 – Saber Pro")
        if NumberedCanvas._date:
            self.drawCentredString(PAGE_W / 2, FOOTER_H - 5.5 * mm, NumberedCanvas._date)
        self.setFont("Helvetica-Bold", 7.3)
        self.drawRightString(PAGE_W - MARGIN, FOOTER_H - 5.5 * mm,
                             f"Página {self._pageNumber} de {total}")
        self.restoreState()


# ─────────────────────────────────────────────────────────────────────────────
# Flowables reutilizables
# ─────────────────────────────────────────────────────────────────────────────
def _kpi_grid(kpis, s, accent=USB_ORANGE):
    """kpis: list[(label, value, sub)] → grilla de 3 columnas."""
    if not kpis:
        return []
    cards = []
    for label, value, sub in kpis:
        inner = [[Paragraph(_safe(label), s["kpi_label"])],
                 [Paragraph(_safe(value), s["kpi_value"])]]
        if sub:
            inner.append([Paragraph(_safe(sub), s["kpi_sub"])])
        t = Table(inner, colWidths=[CONTENT_W / 3 - 6 * mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), USB_TINT_2),
            ("BOX", (0, 0), (-1, -1), 0.6, accent),
            ("LINEABOVE", (0, 0), (-1, 0), 2.2, accent),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        cards.append(t)
    rows = [cards[i:i + 3] for i in range(0, len(cards), 3)]
    if rows and len(rows[-1]) < 3:
        rows[-1] += [""] * (3 - len(rows[-1]))
    grid = Table(rows, colWidths=[CONTENT_W / 3] * 3, hAlign="LEFT")
    grid.setStyle(TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return [grid, Spacer(1, 5 * mm)]


def _data_table(columns, rows, s):
    header = [Paragraph(_safe(c), s["cell_h"]) for c in columns]
    body = [[Paragraph("" if v is None else _safe(v), s["cell"]) for v in r] for r in rows]
    data = [header] + body
    ncols = max(1, len(columns))
    if ncols == 1:
        widths = [CONTENT_W]
    else:
        first = max(min(CONTENT_W * 0.34, CONTENT_W - (ncols - 1) * 18 * mm), 26 * mm)
        widths = [first] + [(CONTENT_W - first) / (ncols - 1)] * (ncols - 1)
    t = LongTable(data, colWidths=widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), USB_TBL_HDR),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE_GRAY),
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, USB_ORANGE_D),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    for i in range(1, len(body) + 1):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), USB_TINT))
    t.setStyle(TableStyle(style))
    return t


def _metrics_table(cols_rows, s):
    """Tabla resumen compacta (debajo de un gráfico)."""
    columns, rows = cols_rows
    data = [[Paragraph("Resumen", s["cell_h"]), Paragraph("", s["cell_h"])]]
    data += [[Paragraph(_safe(k), s["cell"]), Paragraph(_safe(v), s["cell_b"])] for k, v in rows]
    t = Table(data, colWidths=[CONTENT_W * 0.34, CONTENT_W * 0.66])
    style = [
        ("SPAN", (0, 0), (-1, 0)),
        ("BACKGROUND", (0, 0), (-1, 0), USB_ORANGE_D),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE_GRAY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    for i in range(1, len(rows) + 1):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), USB_TINT_2))
    t.setStyle(TableStyle(style))
    return t


def _figure_block(label, item, s):
    blocks = [Paragraph(_safe(label), s["h3"])]
    if item.get("desc"):
        blocks.append(Paragraph(_safe(item["desc"]), s["fig_desc"]))
    if item.get("kind") == "figure_multi":
        figs = item.get("figures", [])
        caps = item.get("captions", [""] * len(figs))
        for fig_dict, cap in zip(figs, caps):
            png = _fig_to_png(fig_dict, width=900, height=640, scale=3)
            sub = [_framed_image(png, CONTENT_W * 0.74, 900, 640)]
            if cap:
                sub.append(Paragraph(_safe(cap), s["caption"]))
            blocks.append(KeepTogether(sub))
    else:
        rw, rh = _render_size(item["figure"])
        png = _fig_to_png(item["figure"], width=rw, height=rh, scale=3)
        fig_flow = [_framed_image(png, CONTENT_W, rw, rh)]
        # Tabla resumen con métricas (total/promedio/máx/mín/participación).
        if item.get("metrics", True):
            mr = _figure_metrics_rows(item["figure"])
            if mr is not None:
                fig_flow += [Spacer(1, 2 * mm), _metrics_table(mr, s)]
        fig_flow.append(Spacer(1, 5 * mm))
        blocks.append(KeepTogether(fig_flow))
    return blocks


# ─────────────────────────────────────────────────────────────────────────────
# Texto académico autogenerado
# ─────────────────────────────────────────────────────────────────────────────
def _is_num(v):
    try:
        float(v); return True
    except (ValueError, TypeError):
        return False


def _fmt_filter(v):
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v) if v else "—"
    return str(v)


_SECTION_METHOD = {
    "interuniv": "Se comparan universidades sobre puntajes normalizados (0–1) de Saber Pro "
                 "por competencia; los rankings y la diferencia máxima se derivan del promedio "
                 "institucional bajo los filtros activos.",
    "puntajes": "El aporte institucional se calcula como la diferencia entre el promedio de "
                "Saber Pro y el de Saber 11 por competencia y año, sobre puntajes normalizados, "
                "expresada en puntos sobre escala 0–100.",
    "socio": "Se describe la composición socioeconómica de la población de Saber Pro mediante "
             "distribuciones de frecuencia sobre las variables de identificación, familiares e "
             "institucionales, según los filtros aplicados.",
    "desercion": "La no profesionalización se estima por la ausencia de coincidencia de llave "
                 "entre Saber 11 y Saber Pro; se reportan tasas por cohorte y la tendencia "
                 "mediante regresión lineal de la tasa de no coincidencia.",
    "rna": "Se evalúa el desempeño de una Red Neuronal Artificial entrenada externamente, "
           "contrastando valores reales y predichos sobre el conjunto seleccionado mediante "
           "MAE, RMSE, R² y sesgo medio.",
    "probestrato": "Se estima la probabilidad condicional del estrato socioeconómico dado el "
                   "nivel educativo de los padres, como frecuencia relativa observada en el año "
                   "seleccionado.",
}


def _auto_conclusions(payloads, selected_keys):
    bullets = []
    sel = {k.split("::")[0] for k in selected_keys}

    if "interuniv" in sel:
        items = (payloads.get("interuniv") or {}).get("items", {})
        et = items.get("table_exec")
        if et and et.get("rows"):
            cols, rows = et["columns"], et["rows"]
            if "Puntaje Global" in cols:
                gi = cols.index("Puntaje Global")
                try:
                    best = max(rows, key=lambda r: float(r[gi]))
                    bullets.append(f"La {best[0]} presenta el mayor Puntaje Global "
                                   f"({float(best[gi]):.2f}) entre las instituciones seleccionadas.")
                except (ValueError, TypeError):
                    pass
            avgs = {}
            for c in [c for c in cols if c != "Universidad"]:
                ci = cols.index(c)
                vals = [float(r[ci]) for r in rows if _is_num(r[ci])]
                if vals:
                    avgs[c] = sum(vals) / len(vals)
            if avgs:
                bc = max(avgs, key=avgs.get)
                bullets.append(f"La competencia con mejor desempeño promedio fue {bc} "
                               f"({avgs[bc]:.2f}).")
        kd = items.get("kpi_diff")
        if kd and kd.get("value") not in (None, "—"):
            bullets.append(f"La diferencia máxima entre universidades fue de {kd['value']} "
                           f"puntos normalizados.")

    if "puntajes" in sel:
        items = (payloads.get("puntajes") or {}).get("items", {})
        for kid, txt in [("kpi_aporte_comp", "La competencia con mayor aporte institucional fue {}."),
                         ("kpi_aporte_anio", "El año con mayor aporte institucional fue {}.")]:
            k = items.get(kid)
            if k and k.get("value") not in (None, "—"):
                bullets.append(txt.format(k["value"]))

    if "desercion" in sel:
        items = (payloads.get("desercion") or {}).get("items", {})
        kt, ktr = items.get("kpi_tasa"), items.get("kpi_trend")
        if kt and kt.get("value") not in (None, "—"):
            bullets.append(f"La tasa de profesionalización (coincidencia SB11→SB Pro) fue {kt['value']}.")
        if ktr and ktr.get("value") not in (None, "—"):
            bullets.append(f"La tendencia de la no coincidencia entre cohortes es {ktr['value']}.")

    if "socio" in sel:
        kt = (payloads.get("socio") or {}).get("items", {}).get("kpi_total")
        if kt and kt.get("value") not in (None, "—"):
            bullets.append(f"La población analizada fue de {kt['value']} estudiantes según los filtros.")

    if "rna" in sel:
        items = (payloads.get("rna") or {}).get("items", {})
        kr, km = items.get("kpi_r2"), items.get("kpi_mae")
        if kr and kr.get("value") not in (None, "—"):
            extra = f" con un MAE de {km['value']}" if km and km.get("value") not in (None, "—") else ""
            bullets.append(f"El modelo de RNA alcanzó un R² de {kr['value']}{extra} sobre el "
                           f"conjunto seleccionado.")

    if "probestrato" in sel:
        items = (payloads.get("probestrato") or {}).get("items", {})
        kb, kp = items.get("kpi_best"), items.get("kpi_prob")
        if kb and kb.get("value") not in (None, "—"):
            extra = f" ({kp['value']})" if kp and kp.get("value") not in (None, "—") else ""
            bullets.append(f"El {kb['value'].lower()} es el más probable dada la condición "
                           f"analizada{extra}.")

    if not bullets:
        bullets.append("El reporte recopila los indicadores, gráficos y tablas seleccionados "
                       "según los filtros activos en cada página.")
    return bullets


# ─────────────────────────────────────────────────────────────────────────────
# API principal
# ─────────────────────────────────────────────────────────────────────────────
def build_report_pdf(config, payloads, selected_keys):
    """Construye el PDF (estructura IEEE) y devuelve los bytes."""
    s = _styles()
    date_str = config.get("date_str") or datetime.now().strftime("%d/%m/%Y")
    title = config.get("title", "Reporte Institucional")

    # Items realmente disponibles, en el orden del catálogo.
    available = []
    for sec in REPORT_SECTIONS:
        for it in sec["items"]:
            key = f'{sec["id"]}::{it["id"]}'
            if key in selected_keys:
                pl = payloads.get(sec["id"]) or {}
                if it["id"] in (pl.get("items") or {}):
                    available.append(key)

    secs_used = []
    for key in available:
        sid = _ITEM_BY_KEY[key]["section_id"]
        if sid not in secs_used:
            secs_used.append(sid)

    NumberedCanvas._title = title
    NumberedCanvas._date = date_str

    buf = io.BytesIO()
    doc = ReportDoc(buf, pagesize=A4,
                    leftMargin=MARGIN, rightMargin=MARGIN,
                    topMargin=HEADER_H + 8 * mm, bottomMargin=FOOTER_H + 4 * mm,
                    title=title, author="Sistema de Analítica Académica · USB")
    doc._report_title = title
    doc._report_subtitle = config.get("subtitle", "")
    doc._report_user = config.get("user", "")
    doc._report_date = date_str

    cover_frame = Frame(0, 0, PAGE_W, PAGE_H, id="cover")
    content_frame = Frame(MARGIN, FOOTER_H + 4 * mm, CONTENT_W,
                          PAGE_H - (HEADER_H + 8 * mm) - (FOOTER_H + 4 * mm), id="content")
    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[cover_frame], onPage=_draw_cover),
        PageTemplate(id="content", frames=[content_frame]),
    ])

    story = [NextPageTemplate("content"), PageBreak()]

    # ── Tabla de contenido ──
    story.append(Paragraph("Tabla de Contenido", s["h1"]))
    story.append(_rule())
    toc = TableOfContents()
    toc.levelStyles = [s["toc0"], s["toc1"]]
    toc.dotsMinLevel = 0
    story.append(toc)
    story.append(PageBreak())

    n = 0  # numeración de secciones principales

    # ── 1. Introducción ──
    n += 1
    story.append(SectionHeading(f"{n}. Introducción", s["h1"], 0, "sec-intro"))
    story.append(_rule())
    n_comp = len(available)
    src_titles = _safe(", ".join(_SECTION_BY_ID[x]["title"] for x in secs_used)) or "—"
    story.append(Paragraph(
        f"Este informe presenta un análisis comparativo y predictivo de la evolución de "
        f"competencias universitarias a partir de las pruebas Saber 11 y Saber Pro. El "
        f"documento se genera de forma automática desde el Sistema de Analítica Académica de "
        f"la Universidad de San Buenaventura, recopilando <b>{n_comp}</b> componente(s) "
        f"seleccionado(s) por el usuario y respetando los filtros activos en cada página de "
        f"origen.", s["body"]))
    story.append(Paragraph(
        f"<b>Alcance.</b> El reporte integra información de las siguientes secciones del "
        f"sistema: {src_titles}. Cada sección aporta indicadores descriptivos, estimadores "
        f"estadísticos, visualizaciones y tablas, organizados conforme a una estructura de "
        f"informe técnico.", s["body"]))

    meta_rows = [["Título", title], ["Subtítulo", config.get("subtitle") or "—"],
                 ["Fecha de generación", date_str],
                 ["Usuario generador", config.get("user") or "—"],
                 ["Componentes incluidos", str(n_comp)]]
    story.append(Spacer(1, 2 * mm))
    story.append(_data_table(["Parámetro", "Valor"], meta_rows, s))

    # ── 2. Metodología ──
    n += 1
    story.append(SectionHeading(f"{n}. Metodología", s["h1"], 0, "sec-metodo"))
    story.append(_rule())
    story.append(Paragraph(
        "Los datos provienen de los microdatos del ICFES (Saber 11 y Saber Pro) integrados en "
        "una base de datos PostgreSQL. El dashboard calcula y almacena en caché los resultados; "
        "este reporte reutiliza dichos resultados —tal como el usuario los visualiza— sin "
        "recalcular consultas, garantizando consistencia entre la pantalla y el documento. Los "
        "puntajes se manejan en su escala normalizada (0–1) salvo indicación contraria.", s["body"]))
    for sid in secs_used:
        story.append(Paragraph(_safe(_SECTION_BY_ID[sid]["title"]), s["h3"]))
        if sid in _SECTION_METHOD:
            story.append(Paragraph(_SECTION_METHOD[sid], s["body"]))
        filt = (payloads.get(sid) or {}).get("filters") or {}
        if filt:
            frows = [[str(k), _fmt_filter(v)] for k, v in filt.items()]
            story.append(_data_table(["Filtro aplicado", "Selección"], frows, s))
            story.append(Spacer(1, 3 * mm))

    # ── 3. Resultados (gráficos + tablas) ──
    n += 1
    story.append(SectionHeading(f"{n}. Resultados", s["h1"], 0, "sec-result"))
    story.append(_rule())
    res_sources = [sid for sid in secs_used
                   if any(_ITEM_BY_KEY[k]["kind"] in ("figure", "figure_multi", "table")
                          and _ITEM_BY_KEY[k]["section_id"] == sid for k in available)]
    if not res_sources:
        story.append(Paragraph("No se seleccionaron gráficos ni tablas para este reporte.", s["body"]))
    for i, sid in enumerate(res_sources, 1):
        story.append(SectionHeading(f"{n}.{i} {_SECTION_BY_ID[sid]['title']}", s["h2"],
                                    1, f"res-{sid}"))
        for key in available:
            meta = _ITEM_BY_KEY[key]
            if meta["section_id"] != sid:
                continue
            it = payloads[sid]["items"][meta["id"]]
            if meta["kind"] in ("figure", "figure_multi"):
                story += _figure_block(it.get("label", meta["label"]), it, s)
            elif meta["kind"] == "table":
                story.append(Paragraph(_safe(it.get("label", meta["label"])), s["h3"]))
                story.append(_data_table(it["columns"], it["rows"], s))
                story.append(Spacer(1, 5 * mm))

    # ── 4. Indicadores ──
    n += 1
    story.append(SectionHeading(f"{n}. Indicadores", s["h1"], 0, "sec-ind"))
    story.append(_rule())
    story.append(Paragraph(
        "Los <b>indicadores</b> son medidas descriptivas calculadas directamente sobre los datos "
        "observados (conteos, promedios, tasas, máximos y mínimos). Resumen el estado de la "
        "población analizada bajo los filtros aplicados.", s["body"]))
    _kpi_section(story, s, payloads, available, estimador=False)

    # ── 5. Estimadores ──
    n += 1
    story.append(SectionHeading(f"{n}. Estimadores", s["h1"], 0, "sec-est"))
    story.append(_rule())
    story.append(Paragraph(
        "Los <b>estimadores</b> son valores que infieren o aproximan una cantidad no observada "
        "directamente: estimaciones de error de un modelo predictivo (MAE, RMSE, R², sesgo), "
        "pendientes de tendencia obtenidas por regresión, o probabilidades estimadas. A "
        "diferencia de los indicadores, conllevan un componente inferencial y un margen de "
        "incertidumbre.", s["body"]))
    _kpi_section(story, s, payloads, available, estimador=True)

    # ── 6. Análisis e interpretación ──
    n += 1
    story.append(SectionHeading(f"{n}. Análisis e Interpretación", s["h1"], 0, "sec-analisis"))
    story.append(_rule())
    story.append(Paragraph(
        "A partir de los indicadores y estimadores incluidos, se destacan los siguientes "
        "hallazgos:", s["body"]))
    for b in _auto_conclusions(payloads, available):
        story.append(Paragraph(f"•&nbsp;&nbsp;{_safe(b)}", s["bullet"]))

    # ── 7. Conclusiones ──
    n += 1
    story.append(SectionHeading(f"{n}. Conclusiones", s["h1"], 0, "sec-conclu"))
    story.append(_rule())
    story.append(Paragraph(
        "El reporte consolida la información seleccionada en un documento institucional único, "
        "apto para comités de calidad, procesos de acreditación y toma de decisiones. Los "
        "resultados deben interpretarse en el contexto de los filtros aplicados y de las "
        "limitaciones propias de cada fuente de datos. Se recomienda complementar el análisis "
        "automático con la valoración experta del equipo académico.", s["body"]))

    # ── 8. Referencias ──
    n += 1
    story.append(SectionHeading(f"{n}. Referencias", s["h1"], 0, "sec-ref"))
    story.append(_rule())
    for ref in [
        "ICFES — Instituto Colombiano para la Evaluación de la Educación. Microdatos Saber 11 y "
        "Saber Pro.",
        "Universidad de San Buenaventura, Seccional Medellín. Sistema de Analítica Académica — "
        "Análisis Saber 11 – Saber Pro.",
        "ISO/IEC 20000-1:2018; ISO/IEC/IEEE 12207:2017; ISO 21500:2021 (lineamientos de gestión "
        "y documentación del sistema).",
    ]:
        story.append(Paragraph(f"•&nbsp;&nbsp;{ref}", s["bullet"]))

    if not available:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph(
            "Nota: no se incluyó ningún elemento con datos disponibles. Visita las páginas de "
            "origen, aplica los filtros deseados y vuelve a generar el reporte.", s["body"]))

    doc.multiBuild(story, canvasmaker=NumberedCanvas)
    pdf = buf.getvalue()
    buf.close()
    return pdf


def _kpi_section(story, s, payloads, available, estimador):
    """Agrega al story las tarjetas de KPI (indicadores o estimadores)."""
    any_added = False
    accent = USB_ORANGE_D if estimador else USB_ORANGE
    for sec in REPORT_SECTIONS:
        sid = sec["id"]
        kpis = []
        for it in sec["items"]:
            key = f'{sid}::{it["id"]}'
            if key not in available or it["kind"] != "kpi":
                continue
            is_est = key in ESTIMADOR_KEYS
            if is_est != estimador:
                continue
            data = payloads[sid]["items"][it["id"]]
            kpis.append((data.get("label", it["label"]), data.get("value", "—"), data.get("sub")))
        if kpis:
            story.append(Paragraph(_safe(sec["title"]), s["h3"]))
            story += _kpi_grid(kpis, s, accent)
            any_added = True
    if not any_added:
        txt = ("No se incluyeron estimadores en esta selección."
               if estimador else "No se incluyeron indicadores en esta selección.")
        story.append(Paragraph(txt, s["body"]))


def _rule(color=USB_ORANGE, thickness=1.4):
    """Línea horizontal de acento bajo un título."""
    t = Table([[""]], colWidths=[CONTENT_W], rowHeights=[1])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), thickness, color)]))
    return KeepTogether([t, Spacer(1, 3 * mm)])
