"""
Pages/Generador_Reportes.py — Página "Generador de Reportes"
============================================================

Centro universal de construcción de reportes PDF institucionales para TODO el
dashboard.  Lista el catálogo de componentes reportables de cada página
(`report_engine.REPORT_SECTIONS`), permite seleccionarlos por checkbox, configurar
título/subtítulo/usuario y generar un PDF con identidad visual de la Universidad
de San Buenaventura.

Espejo de filtros en vivo: cada página publica sus filtros activos + KPIs/figuras/
tablas en un `dcc.Store` global (definido en `app.py`).  Esta página lee esos
stores como State al generar, de modo que el PDF refleja exactamente lo que el
usuario tiene filtrado en cada página — sin recalcular consultas.
"""

import sys
from datetime import datetime
from pathlib import Path

import dash
from dash import dcc, html, callback, Input, Output, State, ctx, no_update

# Importar el motor central (vive en desarrolloInterfaz/Services).
sys.path.append(str(Path(__file__).resolve().parent.parent))
import Services.report_engine as RE  # noqa: E402

if __name__ != "__main__":
    dash.register_page(__name__, path="/generador-reportes",
                       name="Generador de Reportes")

# ── Tema (igual al resto del dashboard) ──
BG         = "#0D1117"
CARD_BG    = "#161B22"
BORDER     = "#30363D"
ACCENT1    = "#58A6FF"
ACCENT2    = "#3FB950"
TEXT_MUTED = "#8B949E"
TEXT_MAIN  = "#E6EDF3"
MONO       = "'IBM Plex Mono', monospace"


def card(children, extra=None):
    st = {"background": CARD_BG, "border": f"1px solid {BORDER}",
          "borderRadius": "12px", "padding": "20px", "marginBottom": "20px"}
    if extra:
        st.update(extra)
    return html.Div(children, style=st)


def section_title(text):
    return html.H3(text, style={
        "color": ACCENT1, "fontFamily": MONO, "fontSize": "13px",
        "letterSpacing": "2px", "textTransform": "uppercase",
        "marginBottom": "14px", "marginTop": "0",
        "borderLeft": f"3px solid {ACCENT1}", "paddingLeft": "10px"})


def sublabel(text):
    return html.Div(text, style={"color": TEXT_MUTED, "fontSize": "11px",
                                 "marginBottom": "10px"})


def _input(cid, placeholder, value=""):
    return dcc.Input(id=cid, type="text", value=value, placeholder=placeholder,
                     debounce=True, style={
                         "width": "100%", "background": BG, "color": TEXT_MAIN,
                         "border": f"1px solid {BORDER}", "borderRadius": "6px",
                         "padding": "9px 11px", "fontFamily": MONO,
                         "fontSize": "12px", "marginBottom": "12px"})


def _section_catalog(sec):
    """Bloque de una sección del catálogo con su checklist."""
    opts = [{"label": it["label"], "value": f'{sec["id"]}::{it["id"]}'}
            for it in sec["items"]]
    return html.Div([
        html.Div([
            html.Span(sec["title"], style={
                "color": TEXT_MAIN, "fontFamily": MONO, "fontSize": "12px",
                "fontWeight": "700", "letterSpacing": "1px"}),
            html.Span(id=f'genrep-status-{sec["id"]}', style={
                "marginLeft": "10px", "fontSize": "10px", "fontFamily": MONO}),
        ], style={"marginBottom": "8px"}),
        dcc.Checklist(
            id=f'genrep-check-{sec["id"]}',
            options=opts, value=[],
            style={"display": "flex", "flexDirection": "column", "gap": "6px"},
            labelStyle={"color": TEXT_MUTED, "fontSize": "12px",
                        "fontFamily": MONO, "display": "flex",
                        "alignItems": "center", "gap": "8px", "cursor": "pointer"},
            inputStyle={"accentColor": ACCENT1, "width": "15px", "height": "15px"},
        ),
    ], style={"background": BG, "border": f"1px solid {BORDER}",
              "borderRadius": "8px", "padding": "14px 16px", "marginBottom": "12px"})


# ─────────────────────────────────────────────────────────────────────────────
# LAYOUT
# ─────────────────────────────────────────────────────────────────────────────
layout = html.Div(style={"padding": "28px 36px", "fontFamily": MONO,
                         "maxWidth": "1200px", "margin": "0 auto"}, children=[

    html.H1("📄 Generador de Reportes", style={
        "color": TEXT_MAIN, "fontFamily": MONO, "fontSize": "22px",
        "letterSpacing": "1px", "marginBottom": "4px"}),
    html.Div("Construye un reporte PDF institucional con los indicadores, gráficos "
             "y tablas de cualquier página del dashboard. El reporte respeta los "
             "filtros activos en cada página.",
             style={"color": TEXT_MUTED, "fontSize": "12px", "marginBottom": "24px"}),

    html.Div(style={"display": "flex", "gap": "20px", "flexWrap": "wrap",
                    "alignItems": "flex-start"}, children=[

        # ── Columna izquierda: catálogo ──
        html.Div(style={"flex": "1 1 560px", "minWidth": "320px"}, children=[
            card([
                section_title("1 · Selecciona los componentes"),
                sublabel("Activa los elementos de cada página que deseas incluir. "
                         "Una página aparece como «sin datos» hasta que la visites "
                         "y apliques filtros."),
                html.Div([_section_catalog(sec) for sec in RE.REPORT_SECTIONS]),
            ]),
        ]),

        # ── Columna derecha: configuración + acciones ──
        html.Div(style={"flex": "1 1 320px", "minWidth": "300px"}, children=[
            card([
                section_title("2 · Configuración del reporte"),
                sublabel("Título del reporte"),
                _input("genrep-title", "Análisis Institucional Saber Pro",
                       "Análisis Institucional Saber Pro"),
                sublabel("Subtítulo (opcional)"),
                _input("genrep-subtitle", "Comparación de resultados académicos"),
                sublabel("Usuario generador (opcional)"),
                _input("genrep-user", "Nombre de quien genera el reporte"),
                html.Div([
                    html.Span("Fecha de generación: ", style={"color": TEXT_MUTED,
                                                              "fontSize": "11px"}),
                    html.Span("se añade automáticamente al generar",
                              style={"color": ACCENT1, "fontSize": "11px"}),
                ], style={"marginTop": "4px", "marginBottom": "4px"}),
            ]),

            card([
                section_title("3 · Generar"),
                html.Button("Generar PDF", id="genrep-generate", n_clicks=0, style={
                    "width": "100%", "background": ACCENT1, "color": "#0D1117",
                    "border": "none", "borderRadius": "8px", "padding": "12px",
                    "fontFamily": MONO, "fontSize": "13px", "fontWeight": "700",
                    "letterSpacing": "1px", "cursor": "pointer", "marginBottom": "10px"}),
                html.Button("Cancelar / Limpiar selección", id="genrep-cancel",
                            n_clicks=0, style={
                                "width": "100%", "background": "transparent",
                                "color": TEXT_MUTED, "border": f"1px solid {BORDER}",
                                "borderRadius": "8px", "padding": "10px",
                                "fontFamily": MONO, "fontSize": "12px",
                                "cursor": "pointer"}),
                dcc.Loading(
                    type="circle", color=ACCENT1,
                    children=html.Div(id="genrep-status", style={
                        "marginTop": "14px", "fontSize": "11px", "color": TEXT_MUTED,
                        "minHeight": "18px", "textAlign": "center"}),
                ),
                dcc.Download(id="genrep-download"),
            ]),

            card([
                section_title("Estado de fuentes"),
                sublabel("Resumen de los datos capturados de cada página "
                         "(según sus filtros activos)."),
                html.Div(id="genrep-sources"),
            ]),
        ]),
    ]),
])


# ─────────────────────────────────────────────────────────────────────────────
# CALLBACKS
# ─────────────────────────────────────────────────────────────────────────────
# Estado de fuentes + badge por sección (lee todos los stores globales).
@callback(
    [Output("genrep-sources", "children")]
    + [Output(f'genrep-status-{s["id"]}', "children") for s in RE.REPORT_SECTIONS]
    + [Output(f'genrep-status-{s["id"]}', "style") for s in RE.REPORT_SECTIONS],
    [Input(store_id, "data") for store_id, _ in RE.STORE_IDS],
)
def _sources_status(*store_datas):
    rows, badges, styles = [], [], []
    for (store_id, sec_id), data in zip(RE.STORE_IDS, store_datas):
        sec = next(s for s in RE.REPORT_SECTIONS if s["id"] == sec_id)
        has = bool(data and data.get("items"))
        if has:
            badges.append("● con datos")
            styles.append({"marginLeft": "10px", "fontSize": "10px",
                           "fontFamily": MONO, "color": ACCENT2})
            filt = data.get("filters") or {}
            filt_txt = " · ".join(f"{k}: {RE._fmt_filter(v)}" for k, v in filt.items()) or "—"
            rows.append(html.Div([
                html.Div(f"✓ {sec['title']}", style={"color": TEXT_MAIN,
                         "fontSize": "11px", "fontWeight": "700"}),
                html.Div(filt_txt, style={"color": TEXT_MUTED, "fontSize": "10px",
                         "marginBottom": "8px", "wordBreak": "break-word"}),
            ]))
        else:
            badges.append("○ sin datos")
            styles.append({"marginLeft": "10px", "fontSize": "10px",
                           "fontFamily": MONO, "color": TEXT_MUTED})
            rows.append(html.Div([
                html.Div(f"○ {sec['title']}", style={"color": TEXT_MUTED,
                         "fontSize": "11px"}),
                html.Div("Visita la página y aplica filtros para capturarla.",
                         style={"color": TEXT_MUTED, "fontSize": "10px",
                                "marginBottom": "8px", "fontStyle": "italic"}),
            ]))
    return [rows] + badges + styles


# Cancelar / limpiar: vacía todos los checklists.
@callback(
    [Output(f'genrep-check-{s["id"]}', "value") for s in RE.REPORT_SECTIONS],
    Input("genrep-cancel", "n_clicks"),
    prevent_initial_call=True,
)
def _clear(_n):
    return [[] for _ in RE.REPORT_SECTIONS]


# Generar el PDF.
@callback(
    Output("genrep-download", "data"),
    Output("genrep-status", "children"),
    Input("genrep-generate", "n_clicks"),
    [State(f'genrep-check-{s["id"]}', "value") for s in RE.REPORT_SECTIONS]
    + [State(store_id, "data") for store_id, _ in RE.STORE_IDS]
    + [State("genrep-title", "value"),
       State("genrep-subtitle", "value"),
       State("genrep-user", "value")],
    prevent_initial_call=True,
)
def _generate(_n, *vals):
    n_sec = len(RE.REPORT_SECTIONS)
    check_values = vals[:n_sec]
    store_values = vals[n_sec:2 * n_sec]
    title, subtitle, user = vals[2 * n_sec:2 * n_sec + 3]

    # Claves seleccionadas, en el orden del catálogo.
    selected = set()
    for cv in check_values:
        selected.update(cv or [])
    ordered = [f'{s["id"]}::{it["id"]}' for s in RE.REPORT_SECTIONS
               for it in s["items"] if f'{s["id"]}::{it["id"]}' in selected]

    if not ordered:
        return no_update, "⚠ Selecciona al menos un componente para generar el reporte."

    payloads = {sec_id: data for (store_id, sec_id), data
                in zip(RE.STORE_IDS, store_values) if data}

    # Verificar que haya al menos un elemento con datos disponibles.
    usable = [k for k in ordered
              if payloads.get(k.split("::")[0], {}).get("items", {}).get(k.split("::")[1])]
    if not usable:
        return no_update, ("⚠ Los componentes seleccionados aún no tienen datos. "
                           "Visita esas páginas y aplica filtros, luego regresa.")

    config = {
        "title": (title or "Reporte Institucional").strip(),
        "subtitle": (subtitle or "").strip(),
        "user": (user or "").strip(),
        "date_str": datetime.now().strftime("%d/%m/%Y"),
    }
    try:
        pdf = RE.build_report_pdf(config, payloads, ordered)
    except Exception as e:  # pragma: no cover - feedback al usuario
        return no_update, f"✗ Error al generar el reporte: {type(e).__name__}: {e}"

    fname = "Reporte_USB_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".pdf"
    msg = f"✓ Reporte generado con {len(usable)} componente(s). Descarga iniciada."
    return dcc.send_bytes(lambda b: b.write(pdf), fname), msg
