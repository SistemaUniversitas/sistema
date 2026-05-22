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

    # ── Contenido de la página activa ──
    page_container,
])

print("Páginas registradas:", list(dash.page_registry.keys()))

if __name__ == "__main__":
    app.run(debug=False, port=8050)