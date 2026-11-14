"""/ — client book (landing page after sign-in). Port of reference/react-ui/app/page.tsx."""

from __future__ import annotations

import dash
import dash_ag_grid as dag
import dash_mantine_components as dmc
from dash import dcc, html

from components.add_account_modal import add_account_modal
from components.charts import TAX_VIEWS
from components.common import kpi_skeleton, skeleton
from components.delete_client_modal import delete_client_modal
from components.fold import fold_body, fold_button, fold_extra, fold_summary
from components.onboard_client_modal import onboard_modal
from components.risk_panel import risk_section
from components.shell import footer, icon, left_rail, topbar_book

dash.register_page(__name__, path="/", title="Client book · Transition Studio")

KPI_LABELS = ["Clients", "Accounts", "Total AUM", "Taxes saved YTD", "Since inception",
              "Average TE", "Outside tolerance"]
STATUS_OPTIONS = [
    {"label": "All statuses", "value": "all"},
    {"label": "On target", "value": "on_target"},
    {"label": "Drifting", "value": "drifting"},
    {"label": "Needs review", "value": "needs_review"},
    {"label": "Onboarding", "value": "onboarding"},
    {"label": "Outside tolerance", "value": "outside"},
]

COLUMNS = [
    {"field": "name", "headerName": "Client name", "cellRenderer": "ClientName", "flex": 268,
     "minWidth": 170, "sortable": True, "comparator": {"function": "(a,b)=>a.localeCompare(b)"}},
    {"field": "n_accounts", "headerName": "Accounts", "flex": 109, "minWidth": 76,
     "cellClass": "ts-num", "headerTooltip": "Number of accounts in the household"},
    {"field": "market_value", "headerName": "Market value", "flex": 132, "minWidth": 92,
     "cellClass": "ts-num ts-fw-500", "valueFormatter": {"function": "money(params.value)"}},
    {"field": "target_models", "headerName": "Target model", "flex": 190, "minWidth": 180,
     "cellRenderer": "ModelChips", "sortable": False, "cellDataType": False},
    {"field": "ex_ante_te", "headerName": "Current TE", "flex": 117, "minWidth": 78,
     "cellClass": "ts-num", "valueFormatter": {"function": "pct(params.value)"},
     "headerTooltip": "Ex-ante tracking error vs target, value-weighted across accounts"},
    {"field": "taxes_saved_ytd", "headerName": "Taxes saved YTD", "flex": 160, "minWidth": 92,
     "cellClass": "ts-num ts-fw-500 ts-c-positive", "valueFormatter": {"function": "money(params.value)"},
     "headerTooltip": "Estimated taxes saved this calendar year"},
    {"field": "last_rebalance_date", "headerName": "Last rebalance", "flex": 144, "minWidth": 100,
     "cellClass": "ts-c-ink600", "valueFormatter": {"function": "dash(params.value)"}},
    {"field": "status", "headerName": "Status", "flex": 159, "minWidth": 110,
     "cellRenderer": "StatusPill"},
    {"field": "id", "headerName": "", "cellRenderer": "RowMenu", "width": 69, "maxWidth": 69, "minWidth": 69,
     "sortable": False, "cellClass": "ts-cell-menu", "resizable": False},
]


def chart_card(title: str, subtitle: str, toggle: object, body_id: str, value_id: str,
               badge_id: str, icon_name: str, view_toggle: object | None = None) -> html.Div:
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Div([html.H2(title, className="ts-h2"), html.Span(id=badge_id)],
                                     className="ts-row ts-gap-2"),
                            html.P(subtitle, className="ts-sub ts-mt-1"),
                        ]
                    ),
                    toggle,
                ],
                className="ts-row ts-between ts-items-start ts-mb-5",
            ),
            *([html.Div(view_toggle, className="ts-mb-4")] if view_toggle is not None else []),
            html.Div(
                [html.Div(id=value_id, children=skeleton(56, "45%")),
                 icon(icon_name, 22, "ts-c-primary")],
                className="ts-row ts-between ts-items-end",
            ),
            dcc.Loading(html.Div(id=body_id, className="ts-mt-5", children=skeleton(112)),
                        type="dot", color="#00A0DF", delay_show=400,
                        overlay_style={"visibility": "visible", "opacity": .5}),
        ],
        className="ts-card ts-p-5",
    )


def select_toggle(id_: str, value: str, data: list[dict[str, str]], label: str) -> dmc.Select:
    return dmc.Select(id=id_, value=value, data=data, allowDeselect=False, searchable=False,
                      variant="unstyled", className="ts-text-toggle", comboboxProps={"width": 140},
                      rightSection=icon("chevron-down", 14), rightSectionPointerEvents="none",
                      **{"aria-label": label})


def layout(**_: object) -> html.Div:
    return html.Div(
        [
            html.Div(id="book-topbar", children=topbar_book("", "")),
            html.Div(
                [
                    left_rail("dashboard"),
                    html.Main(
                        html.Div(
                            [
                                dcc.Store(id={"type": "page-load", "page": "book"}, data=0),
                                dcc.Store(id="book-clients", data=None),
                                html.Div(
                                    [
                                        html.Div(
                                            [
                                                html.P(id="book-greeting", className="ts-greeting"),
                                                html.H1("Your client book", className="ts-h1"),
                                                html.P("A clear view of portfolio health and "
                                                       "transition opportunities.",
                                                       className="ts-sub-sm ts-mt-2"),
                                            ]
                                        ),
                                        html.Div(
                                            [
                                                dcc.Link([icon("layers", 17), " Model management"],
                                                         href="/models", id="open-models",
                                                         className="ts-btn ts-btn-secondary "
                                                                   "ts-no-underline"),
                                                html.Button([icon("plus", 17), " Onboard new client"],
                                                            id="open-onboard", n_clicks=0,
                                                            type="button",
                                                            className="ts-btn ts-btn-primary "
                                                                      "ts-shadow-sm"),
                                            ],
                                            className="ts-row ts-gap-3 ts-wrap",
                                        ),
                                    ],
                                    className="ts-page-head",
                                ),
                                html.Div(id="book-error"),
                                html.Section([kpi_skeleton(label) for label in KPI_LABELS],
                                             id="book-kpis", className="ts-kpi-grid ts-mb-8"),
                                html.Section(
                                    [
                                        chart_card("Average tracking error",
                                                   "AUM-weighted across all accounts",
                                                   select_toggle("book-te-window", "63",
                                                                 [{"value": "63", "label": "63-day"},
                                                                  {"value": "252", "label": "252-day"}],
                                                                 "Rolling window"),
                                                   "book-te-chart", "book-te-value", "book-te-badge",
                                                   "trending-up"),
                                        chart_card("Cumulative tax impact",
                                                   "Tax savings generated for the book",
                                                   select_toggle("book-tax-gran", "month",
                                                                 [{"value": "month", "label": "Monthly"},
                                                                  {"value": "year", "label": "Yearly"}],
                                                                 "Granularity"),
                                                   "book-tax-chart", "book-tax-value", "book-tax-badge",
                                                   "chart-column",
                                                   view_toggle=dcc.RadioItems(
                                                       id="book-tax-view", value="saved", inline=True,
                                                       options=TAX_VIEWS,
                                                       className="ts-segmented ts-segmented-sm")),
                                    ],
                                    className="ts-chart-grid ts-mb-8",
                                ),
                                html.Section(
                                    [
                                        html.Div(
                                            [
                                                html.Div(
                                                    [
                                                        html.Div([html.H2("Management activity",
                                                                          className="ts-h2"),
                                                                  html.Span(id="book-act-badge")],
                                                                 className="ts-row ts-gap-2"),
                                                        html.P("Events across the client book",
                                                               className="ts-sub ts-mt-1"),
                                                    ]
                                                ),
                                                dcc.RadioItems(
                                                    id="book-period", value="1y", inline=True,
                                                    options=[{"label": "1Y", "value": "1y"},
                                                             {"label": "3Y", "value": "3y"},
                                                             {"label": "Since inception",
                                                              "value": "all"}],
                                                    className="ts-segmented",
                                                ),
                                            ],
                                            className="ts-row ts-between ts-mb-5",
                                        ),
                                        dcc.Loading(html.Div(id="book-act-chart", children=skeleton(160)),
                                                    type="dot", color="#00A0DF", delay_show=400,
                                                    overlay_style={"visibility": "visible", "opacity": .5}),
                                    ],
                                    className="ts-card ts-p-5 ts-mb-8",
                                ),
                                risk_section("book", "Analytics",
                                             "Allocation, exposures and risk for the whole book"),
                                html.Section(
                                    [
                                        html.Div(
                                            [
                                                html.Div([html.H2("Clients", className="ts-h2"),
                                                          html.P("Monitor portfolio health and next "
                                                                 "best actions.",
                                                                 className="ts-sub ts-mt-1"),
                                                          fold_summary("book-clients-summary")]),
                                                html.Div(
                                                    [fold_extra("book-clients", html.Div(
                                                    [
                                                        html.Label(
                                                            [icon("search", 16, "ts-search-icon"),
                                                             dcc.Input(id="book-search", type="search",
                                                                       placeholder="Search clients",
                                                                       debounce=False,
                                                                       className="ts-search")],
                                                            className="ts-search-wrap",
                                                        ),
                                                        dcc.Dropdown(id="book-status", value="all",
                                                                     options=STATUS_OPTIONS,
                                                                     clearable=False, searchable=False,
                                                                     className="ts-status-select"),
                                                        html.Button("Name A–Z", id="book-sort",
                                                                    n_clicks=0, type="button",
                                                                    className="ts-sort-btn",
                                                                    **{"aria-label": "Sort clients by name"}),
                                                    ],
                                                    className="ts-row ts-gap-2 ts-wrap",
                                                    )),
                                                     fold_button("book-clients", "clients")],
                                                    className="ts-row ts-gap-2 ts-wrap ts-fold-actions",
                                                ),
                                            ],
                                            className="ts-table-head",
                                        ),
                                        fold_body("book-clients", html.Div(id="book-grid-wrap", children=[
                                            dag.AgGrid(
                                                id="book-grid",
                                                rowData=[],
                                                columnDefs=COLUMNS,
                                                defaultColDef={"sortable": True, "resizable": False,
                                                               "suppressMovable": True,
                                                               "wrapHeaderText": True,
                                                               "autoHeaderHeight": True},
                                                dashGridOptions={
                                                    "rowHeight": 71, "headerHeight": 41,
                                                    "domLayout": "autoHeight",
                                                    "suppressCellFocus": True,
                                                    "animateRows": True,
                                                    "getRowId": {"function": "params.data.id"},
                                                    "pagination": True,
                                                    "paginationPageSize": 25,
                                                    "paginationPageSizeSelector": [25, 50, 100],
                                                    "localeText": {
                                                        "noRowsToShow": "No clients match your filters."},
                                                    "tooltipShowDelay": 300,
                                                },
                                                className="ts-grid",
                                                style={"width": "100%"},
                                            ),
                                        ])),
                                    ],
                                    className="ts-card ts-overflow-hidden",
                                ),
                                footer(),
                                onboard_modal(),
                                add_account_modal(),
                                delete_client_modal(),
                            ],
                            className="ts-container",
                        ),
                        className="ts-main",
                    ),
                ],
                className="ts-flex",
            ),
        ],
        className="ts-page",
    )
