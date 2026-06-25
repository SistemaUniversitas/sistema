"""
Pages/Inicio.py — Landing Page (punto de entrada principal del sistema)
=======================================================================

Página de inicio del dashboard (ruta "/").  Presenta la plataforma con una
sección hero, accesos rápidos a cada módulo, un resumen general con cifras
reales, información metodológica y una vista previa de funcionalidades.

Identidad visual: tema oscuro del dashboard + naranja institucional USB.
Los estilos/animaciones viven en assets/landing.css (Dash lo sirve solo).
"""

import sys
from pathlib import Path

import dash
from dash import html, dcc
import pandas as pd
import plotly.graph_objects as go

# Motor de reportes (para contar indicadores del catálogo).
sys.path.append(str(Path(__file__).resolve().parents[1]))

if __name__ != "__main__":
    dash.register_page(__name__, path="/", name="Inicio", order=0)

CACHE_DIR = Path(__file__).resolve().parents[1] / "Cache"
LOGO_BANNER = "/assets/logo-usb-medellin.png"

ACCENT = "#E8730C"
MUTED  = "#8B949E"
BORDER = "#30363D"
GRID   = "#22272E"


# ─────────────────────────────────────────────────────────────
# Resumen general (cifras reales, lectura liviana de los caches)
# ─────────────────────────────────────────────────────────────
def _clean_inst_name(s):
    s = str(s)
    while '""' in s:
        s = s.replace('""', '"')
    s = s.strip().strip('"').strip().replace('"', ' ')
    return " ".join(s.split()).replace(" -", "-")


def _stats():
    out = {"registros": "—", "universidades": "—", "anios": "2010–2024",
           "programas": "—", "indicadores": "—"}
    try:
        import pyarrow.parquet as pq
        socio = CACHE_DIR / "SaberPro_Socioeconomico_cache.parquet"
        if socio.exists():
            out["registros"] = f"{pq.read_metadata(str(socio)).num_rows:,}"
        iu = CACHE_DIR / "SaberPro_Interuniversitario_cache.parquet"
        if iu.exists():
            df = pq.read_table(
                str(iu),
                columns=["inst_nombre_institucion", "estu_prgm_academico"]
            ).to_pandas()
            uniq = pd.Series(df["inst_nombre_institucion"].astype(str).unique())
            out["universidades"] = f"{uniq.map(_clean_inst_name).nunique():,}"
            out["programas"] = f"{df['estu_prgm_academico'].astype(str).str.strip().nunique():,}"
    except Exception:
        pass
    try:
        import Services.report_engine as RE
        out["indicadores"] = str(sum(len(s["items"]) for s in RE.REPORT_SECTIONS))
    except Exception:
        pass
    return out


_STATS = _stats()


# ─────────────────────────────────────────────────────────────
# Figuras de vista previa (datos ilustrativos, tema oscuro)
# ─────────────────────────────────────────────────────────────
def _prev_layout(h=210):
    return dict(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color=MUTED, family="IBM Plex Mono", size=9),
                margin=dict(l=28, r=12, t=10, b=22), height=h, showlegend=False)


def _prev_bar():
    comp = ["Lóg-Cuant", "Lectora", "Ciudadana", "Inglés", "Global"]
    fig = go.Figure(go.Bar(x=comp, y=[0.58, 0.61, 0.55, 0.49, 0.57],
                           marker_color=ACCENT))
    fig.update_layout(**_prev_layout(),
                      xaxis=dict(gridcolor="rgba(0,0,0,0)", tickangle=-12),
                      yaxis=dict(gridcolor=GRID, range=[0, 0.8]))
    return fig


def _prev_radar():
    cats = ["Lóg-Cuant", "Lectora", "Ciudadana", "Inglés", "Global", "Lóg-Cuant"]
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(r=[.62, .58, .55, .60, .61, .62], theta=cats,
                                  fill="toself", line=dict(color=ACCENT)))
    fig.add_trace(go.Scatterpolar(r=[.50, .61, .57, .48, .55, .50], theta=cats,
                                  fill="toself", line=dict(color="#58A6FF")))
    fig.update_layout(**_prev_layout(),
                      polar=dict(bgcolor="rgba(0,0,0,0)",
                                 radialaxis=dict(visible=True, range=[0, 0.8],
                                                 gridcolor=GRID, color=MUTED, tickfont=dict(size=7)),
                                 angularaxis=dict(color=MUTED, gridcolor=GRID)))
    return fig


def _prev_line():
    yrs = list(range(2016, 2024))
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=yrs, y=[42, 39, 41, 37, 35, 33, 34, 31],
                             mode="lines+markers", line=dict(color=ACCENT, width=2)))
    fig.update_layout(**_prev_layout(),
                      xaxis=dict(gridcolor=GRID, dtick=1),
                      yaxis=dict(gridcolor=GRID, title="%"))
    return fig


def _graph(fig):
    return dcc.Graph(figure=fig, config={"displayModeBar": False, "staticPlot": True},
                     style={"height": fig.layout.height})


# ─────────────────────────────────────────────────────────────
# Helpers de UI
# ─────────────────────────────────────────────────────────────
MODULES = [
    ("📊", "Saber Pro · Interuniversitario",
     "Compara universidades por competencia con radares por pareja, rankings y tabla ejecutiva.",
     "/saberpro-interuniversitario"),
    ("📈", "Saber Pro · Puntajes",
     "Puntajes por módulo, comparativa Saber 11 ↔ Saber Pro y aporte institucional por año.",
     "/saberpro-puntajes"),
    ("🎓", "Saber Pro · Socioeconómico",
     "Perfil socioeconómico, familiar e institucional de la población evaluada.",
     "/saberpro-socioeconomico"),
    ("📉", "No profesionalización",
     "Coincidencia Saber 11 → Saber Pro por cohorte, tendencia y radio de incertidumbre.",
     "/no-profesionalizacion"),
    ("🤖", "RNA · Predicción",
     "Resultados del modelo de red neuronal: real vs predicho, residuales y métricas.",
     "/rna-prediccion"),
    ("🎯", "Probabilidad · Estrato",
     "Probabilidad del estrato socioeconómico según la educación de los padres.",
     "/probabilidad-estrato"),
    ("📄", "Generador de Reportes",
     "Construye reportes PDF institucionales con los indicadores, gráficos y tablas que elijas.",
     "/generador-reportes"),
]

METHOD = [
    ("🗄️", "Fuente de datos",
     "Microdatos oficiales del ICFES (Saber 11 y Saber Pro) integrados en una base de datos "
     "PostgreSQL y procesados con PySpark sobre grandes volúmenes."),
    ("⚙️", "Metodología",
     "Puntajes normalizados (0–1), cruce por llaves Saber 11 ↔ Saber Pro, agregaciones "
     "precalculadas en caché y un modelo de red neuronal para predicción."),
    ("🎯", "Alcance",
     "Análisis comparativo, socioeconómico, de no profesionalización y predictivo, con "
     "generación de reportes institucionales en PDF."),
]

PREVIEWS = [
    ("Comparativa por competencia", "Saber Pro · Interuniversitario", _prev_bar()),
    ("Perfil por pareja de universidades", "Radar comparativo", _prev_radar()),
    ("Tendencia de no coincidencia", "Deserción por cohorte", _prev_line()),
]


def _stat(val, lbl):
    return html.Div(className="ld-stat", children=[
        html.Div(val, className="ld-stat-val"),
        html.Div(lbl, className="ld-stat-lbl"),
    ])


def _module_card(icon, title, desc, href):
    return dcc.Link(href=href, className="ld-card", children=[
        html.Div(icon, className="ld-card-icon"),
        html.H3(title),
        html.P(desc),
        html.Span("Abrir módulo  →", className="ld-go"),
    ])


def _method_card(icon, title, desc):
    return html.Div(className="ld-method-card", children=[
        html.Div(icon, className="ld-m-icon"),
        html.H3(title),
        html.P(desc),
    ])


def _preview_card(title, tag, fig):
    return html.Div(className="ld-prev-card", children=[
        html.H4(title),
        html.Span(tag, className="ld-prev-tag"),
        _graph(fig),
    ])


def _section(title, sub, body, delay=0.0):
    head = [html.H2(title, className="ld-sec-title")]
    if sub:
        head.append(html.Span(sub, className="ld-sec-sub"))
    return html.Div(className="ld-section ld-fade",
                    style={"animationDelay": f"{delay}s"}, children=[
        html.Div(head, className="ld-sec-head"),
        body,
    ])


# ─────────────────────────────────────────────────────────────
# LAYOUT
# ─────────────────────────────────────────────────────────────
layout = html.Div(className="ld-root", children=[

    # ── Hero ──
    html.Div(className="ld-hero ld-fade", children=[
        html.Div(className="ld-hero-inner", children=[
            html.Div(html.Img(src=LOGO_BANNER), className="ld-logo-chip"),
            html.Span("Sistema de Analítica Académica", className="ld-kicker"),
            html.H1(className="ld-hero-title", children=[
                "Análisis Comparativo y Predictivo de ",
                html.Span("Competencias Universitarias", className="hl"),
            ]),
            html.P("Plataforma institucional de la Universidad de San Buenaventura · "
                   "Seccional Medellín para analizar la evolución de competencias a partir "
                   "de las pruebas Saber 11 y Saber Pro: comparaciones interuniversitarias, "
                   "perfil socioeconómico, no profesionalización, predicción con redes "
                   "neuronales y generación de reportes institucionales.",
                   className="ld-hero-desc"),
            html.Div(className="ld-cta-row", children=[
                dcc.Link("Explorar módulos  →", href="/saberpro-interuniversitario",
                         className="ld-btn ld-btn-primary"),
                dcc.Link("Generar un reporte", href="/generador-reportes",
                         className="ld-btn ld-btn-ghost"),
            ]),
        ]),
    ]),

    # ── Banner destacado: Vista Ejecutiva ──
    dcc.Link(href="/resumen-ejecutivo", className="ld-exec-banner ld-fade",
             style={"animationDelay": "0.04s"}, children=[
        html.Div("📊", className="ld-exec-icon"),
        html.Div(className="ld-exec-text", children=[
            html.Div("Vista Ejecutiva", className="ld-exec-title"),
            html.Div("Resumen General · Dashboard Principal — la información más "
                     "importante y consolidada del sistema en una sola página.",
                     className="ld-exec-sub"),
        ]),
        html.Div("Abrir  →", className="ld-exec-go"),
    ]),

    # ── Resumen general ──
    _section("Resumen general", "Cifras de la plataforma",
             html.Div(className="ld-stats", children=[
                 _stat(_STATS["registros"], "Registros analizados"),
                 _stat(_STATS["universidades"], "Universidades"),
                 _stat(_STATS["anios"], "Años disponibles"),
                 _stat(_STATS["programas"], "Programas académicos"),
                 _stat(_STATS["indicadores"], "Indicadores y métricas"),
             ]), delay=0.05),

    # ── Accesos rápidos ──
    _section("Accesos rápidos", "Navega directamente a cada módulo",
             html.Div(className="ld-grid",
                      children=[_module_card(*m) for m in MODULES]), delay=0.1),

    # ── Vista previa de funcionalidades ──
    _section("Vista previa de funcionalidades", "Algunos de los análisis disponibles",
             html.Div(className="ld-prev-grid",
                      children=[_preview_card(*p) for p in PREVIEWS]), delay=0.15),

    # ── Información metodológica ──
    _section("Información metodológica", "Cómo se construye el análisis",
             html.Div(className="ld-method",
                      children=[_method_card(*m) for m in METHOD]), delay=0.2),

    # ── Footer ──
    html.Div(className="ld-foot", children=[
        "Universidad de San Buenaventura · Seccional Medellín · "
        "Sistema de Analítica Académica · Saber 11 – Saber Pro",
    ]),
])
