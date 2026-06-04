from dash import Dash, html, dcc, page_container, page_registry
import dash

app = Dash(__name__, use_pages=True)

app.index_string = """<!DOCTYPE html>
<html>
<head>
    {%metas%}<title>{%title%}</title>{%favicon%}{%css%}
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;700&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; }
        body { margin: 0; background: #0D1117; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: #0D1117; }
        ::-webkit-scrollbar-thumb { background: #30363D; border-radius: 3px; }

        /* ── Overlay de carga global ── */
        @keyframes icfes-spin  { to { transform: rotate(360deg); } }
        @keyframes icfes-fade  { from { opacity: 0; } to { opacity: 1; } }
        @keyframes icfes-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.45; } }

        .icfes-loading-overlay {
            position: fixed; inset: 0;
            width: 100vw; height: 100vh;
            display: flex; align-items: center; justify-content: center;
            background: rgba(1, 4, 9, 0.74);
            backdrop-filter: blur(2px);
            -webkit-backdrop-filter: blur(2px);
            z-index: 9999;
            animation: icfes-fade 0.18s ease-out;
        }
        .icfes-loading-card {
            display: flex; flex-direction: column; align-items: center; gap: 18px;
            padding: 34px 46px;
            background: #161B22;
            border: 1px solid #30363D;
            border-radius: 14px;
            box-shadow: 0 12px 48px rgba(0, 0, 0, 0.6);
            font-family: 'IBM Plex Mono', monospace;
        }
        .icfes-spinner {
            width: 54px; height: 54px;
            border: 4px solid rgba(88, 166, 255, 0.18);
            border-top-color: #58A6FF;
            border-radius: 50%;
            animation: icfes-spin 0.8s linear infinite;
        }
        .icfes-loading-title {
            color: #E6EDF3; font-size: 14px; font-weight: 700;
            letter-spacing: 1.5px; text-transform: uppercase;
            animation: icfes-pulse 1.4s ease-in-out infinite;
        }
        .icfes-loading-sub {
            color: #8B949E; font-size: 11px; letter-spacing: 1px;
        }
    </style>
</head>
<body>{%app_entry%}{%config%}{%scripts%}{%renderer%}</body>
</html>"""

BG     = "#0D1117"
BORDER = "#30363D"
ACCENT1 = "#58A6FF"
TEXT_MUTED = "#8B949E"
TEXT_MAIN  = "#E6EDF3"

app.layout = html.Div(style={"background": BG, "minHeight": "100vh"}, children=[

    # ── Barra de navegación ──
    html.Div([
        html.Span("ICFES · Dashboards", style={
            "color": ACCENT1, "fontFamily": "'IBM Plex Mono', monospace",
            "fontSize": "13px", "letterSpacing": "3px"
        }),
        html.Div([
            dcc.Link(
                page["name"],
                href=page["path"],
                style={
                    "color": TEXT_MUTED, "textDecoration": "none",
                    "fontFamily": "'IBM Plex Mono', monospace",
                    "fontSize": "12px", "letterSpacing": "1px",
                    "padding": "6px 14px", "borderRadius": "6px",
                    "border": f"1px solid {BORDER}",
                }
            )
            for page in dash.page_registry.values()
            if page["path"] not in {
                "/2007", "/2015", "/2024",
                "/saberpro2006", "/saberpro2015", "/saberpro2023",
                "/saberpro2023-db",
            }
        ], style={"display": "flex", "gap": "10px"}),
    ], style={
        "display": "flex", "justifyContent": "space-between",
        "alignItems": "center", "padding": "14px 32px",
        "borderBottom": f"1px solid {BORDER}",
        "background": "#161B22",
    }),

    # ── Contenido de la página activa (con overlay de carga global) ──
    dcc.Loading(
        id="global-loading",
        # El custom_spinner es un overlay a pantalla completa (position: fixed)
        # que oscurece el fondo, lo difumina y bloquea la interacción mientras
        # se procesan/actualizan los diagramas o se navega a otra página.
        custom_spinner=html.Div(
            html.Div([
                html.Div(className="icfes-spinner"),
                html.Div("Procesando información", className="icfes-loading-title"),
                html.Div("Cargando y actualizando diagramas…",
                         className="icfes-loading-sub"),
            ], className="icfes-loading-card"),
            className="icfes-loading-overlay",
        ),
        # Mantener el contenido visible (atenuado por el overlay) en vez de ocultarlo.
        overlay_style={"visibility": "visible"},
        # Pequeños retardos para evitar parpadeo en actualizaciones instantáneas
        # y para que el cierre sea suave.
        delay_show=120,
        delay_hide=200,
        children=page_container,
    ),
])

print("Páginas registradas:", list(dash.page_registry.keys()))

if __name__ == "__main__":
    app.run(debug=False, port=8050)