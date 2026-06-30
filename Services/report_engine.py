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
import re
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
        "title": "No profesionalización",
        "store": "report-store-desercion",
        "items": [
            {"id": "kpi_total",      "label": "Presentaron Saber 11",            "kind": "kpi"},
            {"id": "kpi_nocoinc",    "label": "No coincidentes",                 "kind": "kpi"},
            {"id": "kpi_coinc",      "label": "Coincidentes",                    "kind": "kpi"},
            {"id": "kpi_tasa",       "label": "Tasa de profesionalización",      "kind": "kpi"},
            {"id": "kpi_trend",      "label": "Tendencia (pp/año)",              "kind": "kpi"},
            {"id": "kpi_ontime",     "label": "A tiempo",                        "kind": "kpi"},
            {"id": "kpi_early",      "label": "Antes del estándar",              "kind": "kpi"},
            {"id": "kpi_late",       "label": "Después del estándar",            "kind": "kpi"},
            {"id": "kpi_avgdev",     "label": "Desviación promedio global",      "kind": "kpi"},
            {"id": "fig_overview_tasa", "label": "Resumen general · tasa de no coincidencia por cohorte", "kind": "figure"},
            {"id": "fig_overview_comp", "label": "Resumen general · composición por cohorte", "kind": "figure"},
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
            {"id": "kpi_mse",     "label": "MSE",                        "kind": "kpi"},
            {"id": "kpi_rmse",    "label": "RMSE",                       "kind": "kpi"},
            {"id": "kpi_r2",      "label": "R²",                         "kind": "kpi"},
            {"id": "kpi_sesgo",   "label": "Sesgo medio",                "kind": "kpi"},
            {"id": "kpi_out3s",   "label": "Outliers 3σ",                "kind": "kpi"},
            {"id": "fig_scatter", "label": "Real vs Predicho · Elipse bivariada", "kind": "figure"},
            {"id": "fig_dist",    "label": "Distribución real vs predicho", "kind": "figure"},
            {"id": "fig_resid",   "label": "Distribución de residuales",  "kind": "figure"},
            {"id": "fig_formas",     "label": "Comparación F1 vs F2 · MAE por módulo", "kind": "figure"},
            {"id": "fig_formas_mse", "label": "Comparación F1 vs F2 · MSE por módulo", "kind": "figure"},
            {"id": "table_metrics","label": "Métricas por módulo",        "kind": "table"},
        ],
    },
    {
        "id": "kmeans",
        "title": "K-Means · Predicción Saber Pro",
        "store": "report-store-kmeans",
        "items": [
            {"id": "kpi_n",       "label": "Estudiantes",                "kind": "kpi"},
            {"id": "kpi_k",       "label": "K (clústeres)",              "kind": "kpi"},
            {"id": "kpi_mae",     "label": "MAE",                        "kind": "kpi"},
            {"id": "kpi_mse",     "label": "MSE",                        "kind": "kpi"},
            {"id": "kpi_rmse",    "label": "RMSE",                       "kind": "kpi"},
            {"id": "kpi_r2",      "label": "R²",                         "kind": "kpi"},
            {"id": "kpi_sesgo",   "label": "Sesgo medio",                "kind": "kpi"},
            {"id": "kpi_out3s",   "label": "Outliers 3σ",                "kind": "kpi"},
            {"id": "fig_scatter", "label": "Real vs Predicho · Elipse bivariada", "kind": "figure"},
            {"id": "fig_dist",    "label": "Distribución real vs predicho", "kind": "figure"},
            {"id": "fig_resid",   "label": "Distribución de residuales",  "kind": "figure"},
            {"id": "fig_barrido", "label": "Selección de K · MAE de validación", "kind": "figure"},
            {"id": "fig_metodos", "label": "Comparación media vs reg. lineal · MAE por módulo", "kind": "figure"},
            {"id": "fig_formas",     "label": "Comparación F1 vs F2 · MAE por módulo", "kind": "figure"},
            {"id": "fig_formas_mse", "label": "Comparación F1 vs F2 · MSE por módulo", "kind": "figure"},
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
    {
        # Sección de la Landing Ejecutiva. `hidden` la excluye del catálogo del
        # Generador (la landing arma su propio PDF directamente) y no tiene store.
        "id": "resumen",
        "title": "Resumen Ejecutivo",
        "hidden": True,
        "items": [
            {"id": "kpi_registros",     "label": "Registros analizados",        "kind": "kpi"},
            {"id": "kpi_universidades", "label": "Universidades",               "kind": "kpi"},
            {"id": "kpi_programas",      "label": "Programas académicos",        "kind": "kpi"},
            {"id": "kpi_tasa",           "label": "Tasa de profesionalización",  "kind": "kpi"},
            {"id": "kpi_mejor",          "label": "Mejor universidad (Global)",  "kind": "kpi"},
            {"id": "fig_top_uni",        "label": "Top 10 universidades por Puntaje Global", "kind": "figure"},
            {"id": "fig_dist_global",    "label": "Distribución del Puntaje Global",         "kind": "figure"},
            {"id": "fig_tendencia",      "label": "Tendencia de profesionalización por cohorte", "kind": "figure"},
        ],
    },
]

# KPIs que son ESTIMADORES (estimaciones estadísticas / de modelo), no simples
# indicadores descriptivos.  El resto de KPIs se tratan como indicadores.
ESTIMADOR_KEYS = {
    "rna::kpi_mae", "rna::kpi_mse", "rna::kpi_rmse", "rna::kpi_r2", "rna::kpi_sesgo",
    "kmeans::kpi_mae", "kmeans::kpi_mse", "kmeans::kpi_rmse", "kmeans::kpi_r2", "kmeans::kpi_sesgo",
    "desercion::kpi_trend",
    "probestrato::kpi_best", "probestrato::kpi_prob",
}

_SECTION_BY_ID = {s["id"]: s for s in REPORT_SECTIONS}
_ITEM_BY_KEY = {
    f'{s["id"]}::{it["id"]}': {**it, "section_id": s["id"], "section_title": s["title"]}
    for s in REPORT_SECTIONS for it in s["items"]
}
STORE_IDS = [(s["store"], s["id"]) for s in REPORT_SECTIONS if s.get("store")]
# Secciones visibles en el catálogo del Generador (excluye las ocultas, p. ej.
# la del Resumen Ejecutivo, que arma su propio PDF).
VISIBLE_SECTIONS = [s for s in REPORT_SECTIONS if not s.get("hidden")]


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

def publish_payload(section_id, filters, items, title=None):
    return {"section_id": section_id,
            "title": title or _SECTION_BY_ID.get(section_id, {}).get("title", section_id),
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
    s["fig_analysis"] = ParagraphStyle("fig_analysis", parent=s["body"], fontSize=8.7,
                                       textColor=BODY, leading=12.5, spaceBefore=2,
                                       spaceAfter=3, alignment=TA_JUSTIFY)
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
            # El destino navegable NO se crea aquí: NumberedCanvas emite las páginas
            # de forma diferida en save(), así que bookmarkPage en este punto ataría
            # TODOS los enlaces del índice a la portada (la primera página). Se anota
            # la marca y el destino se crea en save(), justo antes de emitir su página,
            # cuando la referencia de página ya es la correcta.
            marks = getattr(self.canv, "_toc_marks", None)
            if marks is not None:
                marks.append((self.canv.getPageNumber(), flowable.toc_level,
                              flowable.toc_text, flowable.toc_key))


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
        self._toc_marks = []     # (página, nivel, texto, clave) para el índice navegable

    def showPage(self):
        self._saved_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_states)
        # Destinos del índice agrupados por la página en la que está cada título.
        marks_by_page = {}
        for pg, level, text, key in self._toc_marks:
            marks_by_page.setdefault(pg, []).append((level, text, key))
        for state in self._saved_states:
            self.__dict__.update(state)
            if self._pageNumber > 1:           # la portada no lleva encabezado/pie
                self._draw_header()
                self._draw_footer(total)
            # Crear los marcadores/anclas ANTES de emitir la página: en este punto
            # de la reproducción la referencia de página apunta a la página correcta,
            # de modo que los enlaces del índice llevan al título y no a la portada.
            for level, text, key in marks_by_page.get(self._pageNumber, []):
                self.bookmarkPage(key)
                self.addOutlineEntry(text, key, level=level, closed=(level > 0))
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
    body = [[Paragraph("" if v is None else _fmt_cell(v), s["cell"]) for v in r] for r in rows]
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


def _coerce_array(v):
    """Convierte la coordenada de una traza a arreglo numpy. Plotly serializa los
    arreglos grandes (p. ej. nubes de dispersión) como typed-array en base64
    ({'dtype','bdata'}); aquí se decodifican para poder analizarlos."""
    if v is None:
        return np.asarray([], dtype="float64")
    if isinstance(v, dict) and "bdata" in v:
        import base64
        try:
            return np.frombuffer(base64.b64decode(v["bdata"]),
                                 dtype=np.dtype(v.get("dtype", "f8")))
        except Exception:
            return np.asarray([], dtype="float64")
    try:
        return np.asarray(v, dtype="float64")
    except (ValueError, TypeError):
        return np.asarray([], dtype="float64")


def _axis_title(layout, axis):
    """Texto del título de un eje ('xaxis'/'yaxis'), saneado, o '' si no hay."""
    ax = getattr(layout, axis, None)
    title = getattr(ax, "title", None) if ax is not None else None
    txt = getattr(title, "text", None) if title is not None else None
    return _safe(txt).strip() if txt else ""


# Pistas de unidad que aparecen en los títulos de los ejes del dashboard.
_PCT_HINTS = ("%", "porcentaje", "proporción", "proporcion", "tasa", "probabilidad")
_PP_HINTS = ("(pp)", "pp/", "puntos porcentuales", "punto porcentual")


def _axis_meaning(title):
    """Descompone el título de un eje en (sustantivo legible, unidad, aclaración).

    Es la pieza clave para que las descripciones sean concretas y digan la unidad
    SIN nada hardcodeado: el propio gráfico lleva en sus ejes qué mide y en qué
    unidad.  Ej.:  'Tasa (%)'            -> ('tasa', '%', '')
                   'Δ tasa previa (pp)'  -> ('Delta tasa previa', 'pp', '')
                   'Cohorte (año Saber 11)' -> ('cohorte', '', 'año Saber 11')
                   'Estudiantes coincidentes' -> ('estudiantes coincidentes', '', '')."""
    if not title:
        return "", "", ""
    low = title.lower()
    unit = ""
    if any(h in low for h in _PP_HINTS):
        unit = "pp"
    elif any(h in low for h in _PCT_HINTS):
        unit = "%"
    # Última aclaración entre paréntesis ('(año Saber 11)', '(normalizado)', '(%)').
    clar, noun = "", title
    m = re.search(r"\(([^)]*)\)\s*$", title)
    if m:
        inside = m.group(1).strip()
        noun = title[:m.start()].strip()
        low_in = inside.lower()
        # Si el paréntesis solo expresaba la unidad, no es una aclaración útil.
        if not (inside in ("%",) or "pp" in low_in or "porcentual" in low_in):
            clar = inside
    noun = noun.strip(" ·-—:")
    return noun, unit, clar


def _lc_first(t):
    """Baja a minúscula la inicial para usar el texto a mitad de frase, pero
    respeta siglas (MAE, RMSE) y nombres con mayúscula interna."""
    if not t:
        return t
    first = t.split(" ", 1)[0]
    if first.isupper() or (len(first) > 1 and first[1].isupper()):
        return t
    return t[:1].lower() + t[1:]


def _fmt_val(val, unit=""):
    """Formatea un número con su unidad para la prosa de las descripciones,
    ajustando los decimales a la magnitud (las métricas pequeñas como MAE/RMSE
    necesitan más precisión que los conteos)."""
    if not _num(val):
        return _safe(str(val))
    if unit == "%":
        return f"{val:.1f}%"
    if unit == "pp":
        return f"{val:+.1f} pp"
    a = abs(val)
    if a >= 1000:
        return f"{val:,.0f}"
    if float(val).is_integer():
        return f"{int(val):,}"
    if a >= 10:
        return f"{val:,.1f}"
    if a >= 1:
        return f"{val:,.2f}"
    if a >= 0.1:
        return f"{val:.3f}".rstrip("0").rstrip(".")
    return f"{val:.4f}".rstrip("0").rstrip(".")


# Magnitudes que NO se deben sumar entre categorías (promedios, tasas, puntajes,
# errores…): comparar series por su promedio, no por su total.
_AVG_HINTS = ("promedio", "media", "puntaje", "tasa", "índice", "indice",
              "probabilidad", "porcentaje", "proporción", "proporcion",
              "normalizado", "coeficiente", "error", "mae", "mse", "rmse",
              "r²", "r2")


def _is_averaged(ynoun, yunit):
    """True si la magnitud del eje Y es de tipo promedio/tasa/score (no aditiva)."""
    low = (ynoun or "").lower()
    return yunit == "%" or any(h in low for h in _AVG_HINTS)


def _fmt_cell(v):
    """Formatea el valor de una celda de tabla: limpia el ruido de los float32
    (p. ej. 0.47999998927116394 -> 0.48) y agrupa miles en los enteros, dejando
    como máximo 4 decimales.  Cualquier otro tipo se pasa tal cual."""
    if isinstance(v, bool):
        return _safe(str(v))
    if isinstance(v, (int, np.integer)):
        return f"{int(v):,}"
    if isinstance(v, (float, np.floating)):
        x = float(v)
        if not np.isfinite(x):
            return _safe(str(v))
        if x.is_integer():
            return f"{int(x):,}"
        return f"{x:.4f}".rstrip("0").rstrip(".")
    return _safe(v)


def _figure_description(label, fig_dict, s, caption=None):
    """Genera una descripción de dos partes para un gráfico, de forma totalmente
    automática (nada hardcodeado por figura):

    · «general»  — explica EN LENGUAJE LLANO qué muestra el gráfico y para qué
      sirve, usando el significado de sus propios ejes/etiquetas, de modo que se
      entienda aunque no se sepa leer el gráfico.
    · «específica» — entrega la lectura/conclusión concreta de los datos (dónde
      está lo más alto y lo más bajo, la tendencia, el promedio…), indicando la
      UNIDAD de los números cuando el gráfico la declara en sus ejes.

    Toda la información se deriva de la propia figura: tipo de traza, títulos de
    los ejes (que aportan el significado y la unidad), categorías y magnitudes."""
    try:
        fig = go.Figure(fig_dict)
    except Exception:
        return []
    traces = list(fig.data)
    if not traces:
        return []
    meta = getattr(fig.layout, "meta", None)
    is_dist = isinstance(meta, dict) and meta.get("compact_dist")
    name = _safe(caption or label or "este gráfico")

    pies = [t for t in traces if getattr(t, "type", None) == "pie"]
    bars = [t for t in traces if getattr(t, "type", None) == "bar"]
    heats = [t for t in traces if getattr(t, "type", None) in ("heatmap", "histogram2d")]
    scatter_all = [t for t in traces if getattr(t, "type", None) in ("scatter", "scattergl")]
    line_traces = [t for t in scatter_all if "lines" in (getattr(t, "mode", "") or "")]
    marker_traces = [t for t in scatter_all
                     if "markers" in (getattr(t, "mode", "") or "")
                     and "lines" not in (getattr(t, "mode", "") or "")]
    disp_main = disp_x = disp_y = None
    disp_n = 0
    if marker_traces:
        cand = [(t, _coerce_array(t.x), _coerce_array(t.y)) for t in marker_traces]
        disp_main, disp_x, disp_y = max(cand, key=lambda c: min(c[1].size, c[2].size))
        disp_n = int(min(disp_x.size, disp_y.size))

    # Significado y unidad que el propio gráfico declara en sus ejes.
    xnoun, xunit, _xclar = _axis_meaning(_axis_title(fig.layout, "xaxis"))
    ynoun, yunit, _yclar = _axis_meaning(_axis_title(fig.layout, "yaxis"))
    qty = _lc_first(ynoun)   # qué se mide (eje vertical)
    dim = _lc_first(xnoun)   # con qué se agrupa/recorre (eje horizontal)

    def _cap(t):
        return (t[:1].upper() + t[1:]) if t else t

    general = specific = ""

    # ── Distribución de frecuencias (histograma compactado a barras) ──
    if is_dist and bars:
        var = _lc_first(xnoun) or "la variable analizada"
        general = (f"Este gráfico muestra cómo se reparten los valores de {var} entre todos los "
                   f"casos: permite ver qué valores son los más habituales, cuáles aparecen poco "
                   f"y alrededor de qué cifra se agrupa la mayoría.")
        centers, counts = [], []
        for tr in bars:
            xs = list(tr.x) if tr.x is not None else []
            ys = list(tr.y) if tr.y is not None else []
            for x, y in zip(xs, ys):
                if _num(x) and _num(y):
                    centers.append(float(x)); counts.append(float(y))
        if centers and sum(counts) > 0:
            tot = sum(counts)
            mean = sum(c * w for c, w in zip(centers, counts)) / tot
            ipk = max(range(len(counts)), key=lambda i: counts[i])
            specific = (f"Los valores van desde {_fmt_val(min(centers), xunit)} hasta "
                        f"{_fmt_val(max(centers), xunit)}, con un promedio cercano a "
                        f"{_fmt_val(mean, xunit)} y la mayor concentración en torno a "
                        f"{_fmt_val(centers[ipk], xunit)}. En total se resumen {tot:,.0f} casos.")

    # ── Torta / participación ──
    elif pies:
        tr = pies[0]
        labels = list(tr.labels) if tr.labels is not None else []
        values = [float(v) for v in (tr.values or []) if _num(v)]
        general = (f"Este gráfico reparte el total entre las categorías de «{name}» y muestra qué "
                   f"porción del conjunto representa cada una, de modo que se ve de inmediato "
                   f"cuáles pesan más y cuáles menos.")
        if values and sum(values) > 0:
            total = sum(values)
            imax = max(range(len(values)), key=lambda i: values[i])
            imin = min(range(len(values)), key=lambda i: values[i])
            lmax = _safe(labels[imax]) if imax < len(labels) else "—"
            lmin = _safe(labels[imin]) if imin < len(labels) else "—"
            specific = (f"La categoría más frecuente es «{lmax}», que reúne el "
                        f"{values[imax] / total * 100:.1f}% del total, y la menos frecuente es "
                        f"«{lmin}» con el {values[imin] / total * 100:.1f}%. Se reparten "
                        f"{total:,.0f} casos entre {len(values)} categorías.")

    # ── Mapa de calor ──
    elif heats:
        h = heats[0]
        a, b = _lc_first(xnoun) or "una variable", _lc_first(ynoun) or "otra variable"
        xs = list(h.x) if h.x is not None else []
        ys = list(h.y) if h.y is not None else []
        try:
            zarr = np.asarray(h.z, dtype="float64")
        except Exception:
            zarr = None
        # Un mapa centrado en 0 (zmid) o con valores negativos NO cuenta casos:
        # codifica con color la magnitud y el SIGNO de una cantidad (p. ej. el
        # aporte SB Pro - SB 11). Se describe como tal, no como una densidad.
        is_signed = getattr(h, "zmid", None) is not None or (
            zarr is not None and zarr.size and np.nanmin(zarr) < 0)
        # Nombre de la cantidad codificada por el color (título de la barra de color).
        qname = ""
        try:
            cb = getattr(h, "colorbar", None)
            ct = getattr(getattr(cb, "title", None), "text", None) if cb else None
            qname = _lc_first(_safe(ct).strip()) if ct else ""
        except Exception:
            qname = ""

        if is_signed:
            q = qname or "el valor medido"
            general = (f"Este mapa de calor muestra, para cada combinación de {a} y {b}, la "
                       f"magnitud y el signo de {q}. En lugar de contar casos, usa una escala de "
                       f"color de dos sentidos: un extremo marca los valores más positivos y el "
                       f"otro los más negativos, de modo que se ve de un vistazo dónde {q} sube y "
                       f"dónde baja.")
            specific = (f"Las celdas de un color señalan dónde {q} es más alto y las del color "
                        f"opuesto, dónde es más bajo.")
            try:
                if zarr is not None and zarr.size:
                    iyx, ixx = np.unravel_index(int(np.nanargmax(zarr)), zarr.shape)
                    iyn, ixn = np.unravel_index(int(np.nanargmin(zarr)), zarr.shape)
                    cxx = _safe(xs[ixx]) if ixx < len(xs) else "—"
                    cyx = _safe(ys[iyx]) if iyx < len(ys) else "—"
                    cxn = _safe(xs[ixn]) if ixn < len(xs) else "—"
                    cyn = _safe(ys[iyn]) if iyn < len(ys) else "—"
                    vmx = float(zarr[iyx, ixx]); vmn = float(zarr[iyn, ixn])
                    specific = (f"El valor más alto de {q} se da en «{cxx}» / «{cyx}» ({vmx:+.1f}) "
                                f"y el más bajo en «{cxn}» / «{cyn}» ({vmn:+.1f}); el resto de "
                                f"celdas queda entre esos dos extremos según su color.")
            except Exception:
                pass
        else:
            general = (f"Este mapa de calor cruza {a} con {b} y usa la intensidad del color para "
                       f"mostrar dónde se acumulan más casos: las celdas más intensas son las "
                       f"combinaciones más frecuentes y las más claras, las menos habituales.")
            specific = ("Las zonas de color más intenso indican las combinaciones más frecuentes y "
                        "las más claras, las menos habituales, lo que ayuda a detectar dónde se "
                        "agrupan los casos y qué cruces casi no aparecen.")
            try:
                # Solo se nombra la celda pico cuando los ejes son categóricos; con ejes
                # numéricos (histograma 2D) el valor de la celda no es informativo.
                if xs and ys and not _num(xs[0]) and not _num(ys[0]) and zarr is not None:
                    iy, ix = np.unravel_index(int(np.nanargmax(zarr)), zarr.shape)
                    cx = _safe(xs[ix]) if ix < len(xs) else "—"
                    cy = _safe(ys[iy]) if iy < len(ys) else "—"
                    specific = (f"La combinación más frecuente es «{cx}» con «{cy}», donde se "
                                f"concentra el mayor número de casos; las zonas más claras señalan "
                                f"los cruces que casi no se dan.")
            except Exception:
                pass

    # ── Dispersión (nube de puntos: real vs. predicho, correlaciones) ──
    elif marker_traces and disp_n >= 30:
        es_pred = "real" in xnoun.lower() and "predich" in ynoun.lower()
        if es_pred:
            general = ("Este gráfico compara, caso por caso, el valor real con el valor que estima "
                       "el modelo. Cada punto es un estudiante; cuanto más cerca esté de la línea "
                       "diagonal, más se parece la estimación al dato real.")
        else:
            xv = _lc_first(xnoun) or "una variable"
            yv = _lc_first(ynoun) or "otra variable"
            general = (f"Este gráfico relaciona {xv} con {yv}, un punto por caso. Sirve para ver si "
                       f"ambas se mueven juntas: cuanto más alineados estén los puntos, más "
                       f"estrecha es la relación entre ellas.")
        if es_pred:
            # Real vs. predicho: la métrica correcta es el coeficiente de
            # determinación R² (qué tanta variación del valor real explica el
            # modelo), NO la correlación de Pearson. Se calcula sobre TODOS los
            # puntos del gráfico (incluidos los atípicos), que es lo que mide R².
            xs_all, ys_all = [], []
            for t in marker_traces:
                tx, ty = _coerce_array(t.x), _coerce_array(t.y)
                k = int(min(tx.size, ty.size))
                if k >= 5:                       # descarta marcas sueltas (p. ej. el centroide)
                    xs_all.append(tx[:k]); ys_all.append(ty[:k])
            if xs_all:
                xa = np.concatenate(xs_all); ya = np.concatenate(ys_all)
            else:
                xa, ya = disp_x[:disp_n], disp_y[:disp_n]
            mask = ~(np.isnan(xa) | np.isnan(ya))
            xa, ya = xa[mask], ya[mask]
            nn = int(xa.size)
            r2 = None
            if nn >= 2:
                ss_res = float(np.sum((xa - ya) ** 2))           # real - predicho
                ss_tot = float(np.sum((xa - xa.mean()) ** 2))
                if ss_tot > 0:
                    r2 = 1.0 - ss_res / ss_tot
            if r2 is not None:
                if r2 >= 0.7:
                    cierre = "las estimaciones se aproximan muy bien a los valores reales"
                elif r2 >= 0.4:
                    cierre = ("las estimaciones siguen la tendencia real, pero con un margen de "
                              "error apreciable")
                elif r2 >= 0:
                    cierre = "las estimaciones todavía se alejan bastante de los valores reales"
                else:
                    cierre = ("las estimaciones son peores que usar simplemente el promedio de los "
                              "valores reales")
                if r2 >= 0:
                    medida = (f"el modelo explica alrededor del {r2 * 100:.0f}% de la variación de "
                              f"los valores reales (coeficiente de determinación R² = {r2:.2f})")
                else:
                    medida = (f"el modelo no logra explicar la variación de los valores reales "
                              f"(coeficiente de determinación R² = {r2:.2f}, negativo)")
                specific = f"Sobre {nn:,} casos, {medida}: {cierre}."
            elif nn:
                specific = (f"Se representan {nn:,} casos que comparan a simple vista el valor real "
                            f"con el estimado por el modelo.")
        else:
            xa = disp_x[:disp_n]; ya = disp_y[:disp_n]
            mask = ~(np.isnan(xa) | np.isnan(ya))
            xa, ya = xa[mask], ya[mask]
            nn = int(xa.size)
            r = None
            if nn >= 2:
                try:
                    r = float(np.corrcoef(xa, ya)[0, 1])
                except Exception:
                    r = None
            if r is not None and not np.isnan(r):
                fuerza = "fuerte" if abs(r) >= 0.7 else ("moderada" if abs(r) >= 0.4 else "débil")
                signo = "positiva" if r >= 0 else "negativa"
                cierre = ("cuando una sube, la otra tiende a subir también" if r >= 0
                          else "cuando una sube, la otra tiende a bajar")
                referencia = "1" if r >= 0 else "-1"
                specific = (f"Sobre {nn:,} casos, la relación es {signo} y {fuerza} (coeficiente "
                            f"r = {r:.2f}, donde un valor cercano a {referencia} indica una "
                            f"relación más estrecha): {cierre}.")
            elif nn:
                specific = (f"Se representan {nn:,} casos que permiten valorar a simple vista qué "
                            f"tan relacionadas están ambas variables.")

    # ── Líneas / tendencia ──
    elif line_traces:
        qy = qty or "el indicador"
        general = (f"Este gráfico muestra cómo evoluciona {qy} a lo largo de "
                   f"{dim or 'la secuencia de períodos'}: permite ver de un vistazo si la cifra "
                   f"sube, baja o se mantiene estable de un período a otro.")
        main = max(line_traces, key=lambda t: len(t.y) if t.y is not None else 0)
        xs_raw = list(main.x) if main.x is not None else []
        raw = list(main.y) if main.y is not None else []
        # Área apilada normalizada a % (groupnorm='percent'): los valores crudos de
        # la traza NO son los que se ven; hay que normalizarlos por el total apilado
        # de cada punto, o se reportarían cifras absurdas (p. ej. 210555%).
        sg = getattr(main, "stackgroup", None)
        norm_pct = sg is not None and any(
            getattr(t, "groupnorm", None) == "percent" for t in line_traces)
        if norm_pct:
            group = [t for t in line_traces if getattr(t, "stackgroup", None) == sg]
            ys, xs = [], []
            for i in range(len(raw)):
                if not _num(raw[i]):
                    continue
                tot = 0.0
                for t in group:
                    ty = list(t.y) if t.y is not None else []
                    if i < len(ty) and _num(ty[i]):
                        tot += float(ty[i])
                if tot > 0:
                    ys.append(float(raw[i]) / tot * 100.0)
                    xs.append(xs_raw[i] if i < len(xs_raw) else None)
            yunit_eff = "%"
        else:
            ys = [float(v) for v in raw if _num(v)]
            xs = xs_raw
            yunit_eff = yunit
        if len(ys) >= 2:
            delta = ys[-1] - ys[0]
            rumbo = "al alza" if delta > 0 else ("a la baja" if delta < 0 else "estable")
            verbo = "subió" if delta > 0 else ("bajó" if delta < 0 else "se mantuvo")
            x0 = _safe(xs[0]) if xs else "el inicio"
            x1 = _safe(xs[-1]) if xs else "el final"
            if yunit_eff == "%":
                v0, v1 = f"{ys[0]:.1f}%", f"{ys[-1]:.1f}%"
                chg = f"{abs(delta):.1f} puntos porcentuales"
            else:
                v0, v1 = _fmt_val(ys[0], yunit_eff), _fmt_val(ys[-1], yunit_eff)
                chg = _fmt_val(abs(delta), yunit_eff)
            multi = (f" Para el contraste, el gráfico incluye {len(line_traces)} series."
                     if len(line_traces) > 1 else "")
            serie_lbl = _safe(getattr(main, "name", "") or "")
            sujeto = (f"La proporción de «{serie_lbl}»" if (norm_pct and serie_lbl)
                      else _cap(qy))
            specific = (f"{sujeto} {verbo} de {v0} en {x0} a {v1} en {x1}, una variación de "
                        f"{chg}. En conjunto, la tendencia es {rumbo}.{multi}")

    # ── Barras ──
    elif bars:
        if len(bars) == 1:
            cats, vals, _h = _bar_axis_values(bars[0])
            pairs = [(c, float(v)) for c, v in zip(cats, vals) if _num(v)]
            qy = qty or "la cantidad de casos"
            dm = dim or "cada grupo"
            general = (f"Este gráfico compara {qy} según {dm}, de manera que se ve rápidamente en "
                       f"qué grupo se acumula más y en cuál menos, y qué tan grandes son las "
                       f"diferencias entre ellos.")
            if pairs:
                total = sum(v for _, v in pairs)
                cmax = max(pairs, key=lambda kv: kv[1])
                cmin = min(pairs, key=lambda kv: kv[1])
                prom = total / len(pairs)
                vmax, vmin = _fmt_val(cmax[1], yunit), _fmt_val(cmin[1], yunit)
                vprom = _fmt_val(prom, yunit)
                comp = ""
                if yunit != "%" and prom > 0 and cmax[1] / prom >= 1.5:
                    comp = f" Eso equivale a unas {cmax[1] / prom:.1f} veces el promedio."
                specific = (f"El valor más alto de {qy} se registra en «{_safe(cmax[0])}» ({vmax}) "
                            f"y el más bajo en «{_safe(cmin[0])}» ({vmin}), con un promedio de "
                            f"{vprom}.{comp}")
        else:
            qy = qty or "los valores"
            dm = dim or "las categorías"
            names = [_safe(getattr(t, "name", "") or "serie") for t in bars]
            general = (f"Este gráfico enfrenta varias series ({', '.join(names)}) a lo largo de "
                       f"{dm}, para contrastar cómo se comporta cada una y dónde se separan más.")
            # Las magnitudes promediables (puntajes, tasas, errores…) se comparan
            # por su PROMEDIO entre categorías; los conteos, por su total (sumar
            # un puntaje normalizado no tiene sentido y daría cifras imposibles).
            averaged = _is_averaged(ynoun, yunit)
            aggs = []
            for tr in bars:
                _c, v, _o = _bar_axis_values(tr)
                nums = [float(x) for x in v if _num(x)]
                if nums:
                    val = (sum(nums) / len(nums)) if averaged else sum(nums)
                    aggs.append((_safe(getattr(tr, "name", "") or "serie"), val))
            if aggs:
                smax = max(aggs, key=lambda kv: kv[1])
                smin = min(aggs, key=lambda kv: kv[1])
                fmax, fmin = _fmt_val(smax[1], yunit), _fmt_val(smin[1], yunit)
                ref = max(abs(smax[1]), abs(smin[1]), 1e-9)
                criterio = "el promedio" if averaged else "el total"
                if (smax[0] == smin[0] or (smax[1] - smin[1]) / ref <= 0.02
                        or fmax == fmin):
                    specific = (f"Las series comparadas presentan {criterio} de {qy} muy parecido a "
                                f"lo largo de {dm}, sin que ninguna se imponga con claridad sobre "
                                f"las demás.")
                elif averaged:
                    specific = (f"En promedio a lo largo de {dm}, «{smax[0]}» es la serie más alta "
                                f"({fmax}) y «{smin[0]}» la más baja ({fmin}), lo que indica cuál "
                                f"grupo presenta valores más altos.")
                else:
                    specific = (f"Sumando {qy} a lo largo de {dm}, «{smax[0]}» acumula el mayor "
                                f"total ({fmax}) y «{smin[0]}» el menor ({fmin}), lo que indica "
                                f"cuál grupo presenta valores más altos en conjunto.")

    # ── Cualquier otro tipo de figura ──
    if not general:
        general = (f"Este gráfico resume de forma visual la información de «{name}» para facilitar "
                   f"su lectura e interpretación.")

    out = [Paragraph(f"<b>Descripción general:</b> {general}", s["fig_analysis"])]
    if specific:
        out.append(Paragraph(f"<b>Descripción específica:</b> {specific}", s["fig_analysis"]))
    return out


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
            # Descripción (general + específica) bajo cada gráfico.
            blocks += _figure_description(label, fig_dict, s, caption=cap)
            blocks.append(Spacer(1, 3 * mm))
    else:
        rw, rh = _render_size(item["figure"])
        png = _fig_to_png(item["figure"], width=rw, height=rh, scale=3)
        fig_flow = [_framed_image(png, CONTENT_W, rw, rh)]
        # Tabla resumen con métricas (total/promedio/máx/mín/participación).
        if item.get("metrics", True):
            mr = _figure_metrics_rows(item["figure"])
            if mr is not None:
                fig_flow += [Spacer(1, 2 * mm), _metrics_table(mr, s)]
        blocks.append(KeepTogether(fig_flow))
        # Descripción (general + específica) bajo el gráfico.
        blocks += _figure_description(label, item["figure"], s)
        blocks.append(Spacer(1, 5 * mm))
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
    "kmeans": "Se evalúa una predicción alternativa por K-Means (cluster-then-predict): los "
              "estudiantes se agrupan por su vector Saber 11 y cada clúster responde con la media "
              "de sus targets (método 'media') o una regresión lineal local (método 'reglineal'). "
              "El número de clústeres K se elige por validación. Se contrastan valores reales y "
              "predichos mediante MAE, RMSE, R² y sesgo medio, de forma comparable con la RNA.",
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

    if "kmeans" in sel:
        items = (payloads.get("kmeans") or {}).get("items", {})
        kr, km, kk = items.get("kpi_r2"), items.get("kpi_mae"), items.get("kpi_k")
        if kr and kr.get("value") not in (None, "—"):
            extra = f" con un MAE de {km['value']}" if km and km.get("value") not in (None, "—") else ""
            kpart = f" (K={kk['value']} clústeres)" if kk and kk.get("value") not in (None, "—") else ""
            bullets.append(f"La predicción alternativa por K-Means alcanzó un R² de "
                           f"{kr['value']}{extra}{kpart} sobre el conjunto seleccionado.")

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
def _meta_for(key, payloads):
    """Metadatos de un ítem: del catálogo si existe, o derivados del payload
    (permite secciones/ítems dinámicos, p. ej. los de la Landing Ejecutiva)."""
    if key in _ITEM_BY_KEY:
        return _ITEM_BY_KEY[key]
    sid, _, iid = key.partition("::")
    pl = payloads.get(sid) or {}
    it = (pl.get("items") or {}).get(iid)
    if it is None:
        return None
    return {"id": iid, "label": it.get("label", iid), "kind": it.get("kind", "figure"),
            "section_id": sid,
            "section_title": pl.get("title") or _SECTION_BY_ID.get(sid, {}).get("title", sid)}


def _section_title(sid, payloads):
    pl = payloads.get(sid) or {}
    return pl.get("title") or _SECTION_BY_ID.get(sid, {}).get("title", sid)


def build_report_pdf(config, payloads, selected_keys):
    """Construye el PDF (estructura IEEE) y devuelve los bytes."""
    s = _styles()
    date_str = config.get("date_str") or datetime.now().strftime("%d/%m/%Y")
    title = config.get("title", "Reporte Institucional")

    # Items realmente disponibles, en el orden recibido (selected_keys).
    available = []
    for key in selected_keys:
        sid, _, iid = key.partition("::")
        pl = payloads.get(sid) or {}
        if iid in (pl.get("items") or {}):
            available.append(key)

    secs_used = []
    for key in available:
        sid = _meta_for(key, payloads)["section_id"]
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
    src_titles = _safe(", ".join(_section_title(x, payloads) for x in secs_used)) or "—"
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
        story.append(Paragraph(_safe(_section_title(sid, payloads)), s["h3"]))
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
                   if any(_meta_for(k, payloads)["kind"] in ("figure", "figure_multi", "table")
                          and _meta_for(k, payloads)["section_id"] == sid for k in available)]
    if not res_sources:
        story.append(Paragraph("No se seleccionaron gráficos ni tablas para este reporte.", s["body"]))
    for i, sid in enumerate(res_sources, 1):
        story.append(SectionHeading(f"{n}.{i} {_section_title(sid, payloads)}", s["h2"],
                                    1, f"res-{sid}"))
        for key in available:
            meta = _meta_for(key, payloads)
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
    story.append(Paragraph(
        "<b>Cómo leer los valores.</b> Un valor <b>positivo</b> indica presencia, aumento o un "
        "resultado a favor de la métrica: por ejemplo, un mayor conteo, una tasa más alta, un "
        "aporte institucional o una variación al alza respecto al periodo anterior; en términos "
        "generales señala un comportamiento favorable o un crecimiento. Un valor <b>negativo</b> "
        "indica lo contrario: una disminución, un déficit o una variación a la baja —como una "
        "tendencia descendente entre cohortes o un aporte por debajo de lo esperado— por lo que "
        "suele advertir un comportamiento desfavorable o una caída que conviene revisar. Un valor "
        "de <b>cero</b> representa ausencia de cambio o equilibrio entre ambos extremos. Esta "
        "lectura debe tenerse presente al interpretar los indicadores que se muestran a "
        "continuación.", s["body"]))
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
        f"El presente reporte consolidó <b>{n_comp}</b> componente(s) provenientes de "
        f"{len(secs_used)} sección(es) del Sistema de Analítica Académica ({src_titles}), "
        f"integrando indicadores descriptivos, estimadores estadísticos, visualizaciones y tablas "
        f"en un único documento institucional construido a partir de los resultados que el usuario "
        f"visualiza en pantalla.", s["body"]))
    story.append(Paragraph("Principales hallazgos", s["h3"]))
    for b in _auto_conclusions(payloads, available):
        story.append(Paragraph(f"•&nbsp;&nbsp;{_safe(b)}", s["bullet"]))
    story.append(Paragraph(
        "En conjunto, los gráficos evidencian las distribuciones, comparaciones y tendencias más "
        "relevantes de la población analizada, mientras que los indicadores y estimadores "
        "cuantifican su magnitud y, cuando aplica, la evolución entre cohortes y el desempeño de "
        "los modelos predictivos. La lectura combinada de unos y otros permite identificar "
        "fortalezas, brechas y áreas de atención prioritaria: las categorías y series con mayor "
        "peso señalan dónde se concentra la población o el mejor desempeño, mientras que las "
        "variaciones negativas y los valores extremos advierten los puntos que requieren "
        "seguimiento.", s["body"]))
    story.append(Paragraph(
        "Estos resultados constituyen un insumo apto para comités de calidad, procesos de "
        "acreditación y toma de decisiones; no obstante, deben interpretarse en el contexto de los "
        "filtros aplicados y de las limitaciones propias de cada fuente de datos. Se recomienda "
        "complementar el análisis automático con la valoración experta del equipo académico antes "
        "de derivar conclusiones definitivas.", s["body"]))

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
