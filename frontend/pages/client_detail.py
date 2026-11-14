"""/clients/<client_id> — management history. Port of reference/react-ui/app/clients/[id]/page.tsx."""

from __future__ import annotations

import dash
import dash_ag_grid as dag
import dash_mantine_components as dmc
from dash import dcc, html

from components.add_account_modal import add_account_modal
from components.charts import TAX_VIEWS
from components.common import kpi_skeleton, skeleton
from components.edit_client_modal import edit_client_modal
from components.fold import fold_body, fold_button, fold_extra, fold_summary
from components.holdings_table import holdings_section
from components.risk_panel import risk_section
from components.shell import footer, icon, topbar_client

dash.register_page(__name__, path_template="/clients/<client_id>",
                   title="Client · Transition Studio")

KPI_LABELS = ["Market value", "Current TE", "Taxes saved YTD", "Since inception",
              "Rebalances, YTD", "Last rebalance"]
EVENT_FILTERS = [("all", "All event types"), ("transition", "Transitions"),
                 ("rebalance", "Rebalances"), ("tax_loss_harvest", "Tax-loss harvests"),
                 ("cash_flow", "Cash flows"), ("model_change", "Model changes")]

YEAR_COLUMNS = [
    {"field": "year", "headerName": "Year", "width": 90, "cellClass": "ts-fw-500"},
    {"field": "aum", "headerName": "AUM (year end)", "flex": 1, "cellClass": "ts-num",
     "valueFormatter": {"function": "money(params.value)"}},
    {"field": "realized_st_gain", "headerName": "Realized ST", "flex": 1, "cellClass": "ts-num",
     "valueFormatter": {"function": "moneyFull(params.value)"}},
    {"field": "realized_lt_gain", "headerName": "Realized LT", "flex": 1, "cellClass": "ts-num",
     "valueFormatter": {"function": "moneyFull(params.value)"}},
    {"field": "losses_harvested", "headerName": "Losses harvested", "flex": 1, "cellClass": "ts-num",
     "valueFormatter": {"function": "moneyFull(params.value)"}},
    {"field": "taxes_saved", "headerName": "Taxes saved", "flex": 1,
     "cellClass": "ts-num ts-c-positive", "valueFormatter": {"function": "moneyFull(params.value)"}},
    {"field": "n_rebalances", "headerName": "Rebalances", "width": 110, "cellClass": "ts-num"},
    {"field": "turnover", "headerName": "Turnover", "width": 110, "cellClass": "ts-num",
     "valueFormatter": {"function": "pct(params.value, 1)"},
     "headerTooltip": "Annual turnover: sum of event turnover, averaged across accounts"},
]
ACCOUNT_COLUMNS = [
    {"field": "label", "headerName": "Account", "flex": 1.6, "minWidth": 160, "cellClass": "ts-fw-500"},
    {"field": "type_label", "headerName": "Type", "flex": 1.1},
    {"field": "custodian", "headerName": "Custodian", "flex": 1},
    {"field": "market_value", "headerName": "Market value", "flex": 1, "cellClass": "ts-num",
     "valueFormatter": {"function": "moneyFull(params.value)"}},
    {"field": "unrealized_gain", "headerName": "Unrealized gain", "flex": 1.1, "cellRenderer": "Signed"},
    {"field": "target_model_id", "headerName": "Target model", "flex": 1,
     "valueFormatter": {"function": "dash(params.value)"}},
    {"field": "ex_ante_te", "headerName": "TE", "width": 90, "cellClass": "ts-num",
     "valueFormatter": {"function": "pct(params.value)"}},
    {"field": "id", "headerName": "", "cellRenderer": "ActionLink", "width": 170, "sortable": False,
     "cellRendererParams": {"action": "start"}},
]


def _select(id_: str, value: str, data: list[dict[str, str]], label: str) -> dmc.Select:
    return dmc.Select(id=id_, value=value, data=data, allowDeselect=False, searchable=False,
                      variant="unstyled", className="ts-text-toggle", comboboxProps={"width": 140},
                      rightSection=icon("chevron-down", 14), rightSectionPointerEvents="none",
                      **{"aria-label": label})


def layout(client_id: str | None = None, start: str | None = None, **_: object) -> html.Main:
    return html.Main(
        [
            dcc.Store(id={"type": "page-load", "page": "client"}, data=0),
            dcc.Store(id="cd-client-id", data=client_id),
            dcc.Store(id="cd-start-hint", data=bool(start)),
            dcc.Store(id="cd-detail", data=None),
            dcc.Store(id="cd-events-limit", data=12),
            html.Div(id="cd-topbar", children=topbar_client("")),
            html.Div(
                [
                    html.Div(id="cd-error"),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.P("Client profile", className="ts-eyebrow ts-mb-2"),
                                    html.H1(id="cd-name", className="ts-h1",
                                            children=skeleton(36, "320px")),
                                    html.P(id="cd-subtitle", className="ts-sub-sm ts-mt-2"),
                                    html.Div(id="cd-chips", className="ts-chip-row"),
                                ]
                            ),
                            html.Div(
                                [
                                    html.Button([icon("pencil", 15), "Edit client"], id="cd-edit",
                                                n_clicks=0, type="button", className="ts-btn-outline"),
                                    html.Button([icon("plus", 16), "Add account"], id="cd-add-account",
                                                n_clicks=0, type="button", className="ts-btn-outline"),
                                    dmc.Menu(
                                        [
                                            dmc.MenuTarget(html.Button(
                                                ["Start transition", icon("arrow-right", 16)],
                                                id="cd-start", n_clicks=0, type="button",
                                                className="ts-btn-cta")),
                                            dmc.MenuDropdown(id="cd-start-menu", children=[]),
                                        ],
                                        id="cd-start-wrap", position="bottom-end", width=280,
                                        shadow="md", radius=8,
                                    ),
                                ],
                                className="ts-row ts-gap-2",
                            ),
                        ],
                        className="ts-detail-head",
                    ),
                    dcc.RadioItems(id="cd-account", value="all", options=[], inline=True,
                                   className="ts-acct-selector"),
                    html.Section([kpi_skeleton(label) for label in KPI_LABELS], id="cd-kpis",
                                 className="ts-kpi-grid-6 ts-mb-6"),
                    html.Div(
                        [
                            html.Section(
                                [
                                    html.Div(
                                        [
                                            html.Div([
                                                html.Div([html.H2("Tracking error to target",
                                                                  className="ts-h2"),
                                                          html.Span(id="cd-te-badge")],
                                                         className="ts-row ts-gap-2"),
                                                html.P(id="cd-te-sub", className="ts-sub ts-mt-1",
                                                       children="Rolling 63-day history with target band"),
                                            ]),
                                            _select("cd-te-window", "63",
                                                    [{"value": "63", "label": "63-day"},
                                                     {"value": "252", "label": "252-day"}],
                                                    "Rolling window"),
                                        ],
                                        className="ts-row ts-between ts-items-start",
                                    ),
                                    dcc.Loading(html.Div(id="cd-te-chart", className="ts-mt-6",
                                                         children=skeleton(250)),
                                                type="dot", color="#00A0DF", delay_show=400,
                                                overlay_style={"visibility": "visible", "opacity": .5}),
                                ],
                                className="ts-card ts-p-5",
                            ),
                            html.Section(
                                [
                                    html.Div(
                                        [
                                            html.Div([
                                                html.Div([html.H2("Taxes saved", id="cd-tax-title",
                                                                  className="ts-h2"),
                                                          html.Span(id="cd-tax-badge")],
                                                         className="ts-row ts-gap-2"),
                                                html.P("Monthly realized impact", id="cd-tax-sub",
                                                       className="ts-sub ts-mt-1"),
                                            ]),
                                            html.Div([
                                                _select("cd-tax-gran", "month",
                                                        [{"value": "month", "label": "Monthly"},
                                                         {"value": "year", "label": "Yearly"}],
                                                        "Granularity"),
                                                icon("trending-down", 20, "ts-c-positive"),
                                            ], className="ts-row ts-gap-3"),
                                        ],
                                        className="ts-row ts-between",
                                    ),
                                    dcc.RadioItems(id="cd-tax-view", value="saved", inline=True,
                                                   options=TAX_VIEWS,
                                                   className="ts-segmented ts-segmented-sm ts-mt-4"),
                                    dcc.Loading(html.Div(id="cd-tax-chart", className="ts-mt-4",
                                                         children=skeleton(250)),
                                                type="dot", color="#00A0DF", delay_show=400,
                                                overlay_style={"visibility": "visible", "opacity": .5}),
                                ],
                                className="ts-card ts-p-5",
                            ),
                        ],
                        className="ts-detail-charts",
                    ),
                    html.Section(
                        [html.Div([html.Div([icon("sparkles", 18, "ts-c-primary"),
                                             html.H2("AI review", className="ts-h2"),
                                             html.Span("Simulated analytics",
                                                       className="ts-sim-badge")],
                                            className="ts-row ts-gap-2"),
                                   html.P(id="cd-ai-sub", className="ts-sub ts-mt-1")]),
                         dcc.Loading(html.Div(id="cd-ai-body", className="ts-mt-4",
                                              children=[skeleton(56, cls="ts-mb-2")] * 2),
                                     type="dot", color="#00A0DF", delay_show=300)],
                        className="ts-card ts-p-5 ts-mt-6 ts-ai-card",
                    ),
                    html.Div(risk_section("cd", "Analytics",
                                          "Household view, all accounts combined"),
                             className="ts-mt-6"),
                    holdings_section(),
                    html.Section(
                        [
                            html.Div(
                                [
                                    html.Div([html.H2("Management history", className="ts-h2"),
                                              html.P("Newest activity across selected accounts",
                                                     className="ts-sub ts-mt-1"),
                                              fold_summary("cd-history-summary")]),
                                    html.Div([fold_extra("cd-history", dmc.Menu(
                                        [
                                            dmc.MenuTarget(html.Button(
                                                icon("sliders-horizontal", 16), id="cd-filter-btn",
                                                type="button", className="ts-icon-btn",
                                                **{"aria-label": "Filter events by type"})),
                                            dmc.MenuDropdown([
                                                dmc.MenuItem(label, id={"type": "evt-filter", "value": v},
                                                             n_clicks=0)
                                                for v, label in EVENT_FILTERS
                                            ]),
                                        ],
                                        position="bottom-end", width=200, shadow="md", radius=8,
                                    )),
                                        fold_button("cd-history", "history")],
                                        className="ts-row ts-gap-2 ts-fold-actions"),
                                ],
                                className="ts-row ts-between ts-items-start ts-gap-3 ts-section-head",
                            ),
                            dcc.Store(id="cd-event-type", data="all"),
                            fold_body("cd-history", [
                                html.Div(id="cd-filter-chip"),
                                html.Div(id="cd-events", children=[skeleton(56, cls="ts-m-5")] * 3),
                            ]),
                        ],
                        className="ts-card ts-overflow-hidden ts-mt-6",
                    ),
                    html.Section(
                        [
                            html.Div([html.Div([html.H2("Summary by year", className="ts-h2"),
                                                html.P("Realized gains, harvesting and rebalancing "
                                                       "per calendar year", className="ts-sub ts-mt-1"),
                                                fold_summary("cd-years-summary")]),
                                      fold_button("cd-years", "summary"), fold_extra("cd-years")],
                                     className="ts-section-head ts-row ts-between ts-items-start "
                                               "ts-gap-3"),
                            fold_body("cd-years", dag.AgGrid(
                                id="cd-years", rowData=[], columnDefs=YEAR_COLUMNS,
                                       defaultColDef={"sortable": True, "suppressMovable": True},
                                       dashGridOptions={"rowHeight": 44, "headerHeight": 40,
                                                        "domLayout": "autoHeight",
                                                        "suppressCellFocus": True,
                                                        "localeText": {"noRowsToShow": "No history yet."}},
                                       className="ts-grid", style={"width": "100%"})),
                        ],
                        className="ts-card ts-overflow-hidden ts-mt-6",
                    ),
                    html.Section(
                        [
                            html.Div([html.Div([html.H2("Accounts", className="ts-h2"),
                                                html.P("Holdings, targets and next actions per "
                                                       "account", className="ts-sub ts-mt-1"),
                                                fold_summary("cd-accounts-summary")]),
                                      fold_button("cd-accounts", "accounts"),
                                      fold_extra("cd-accounts")],
                                     className="ts-section-head ts-row ts-between ts-items-start "
                                               "ts-gap-3", id="cd-accounts-anchor"),
                            fold_body("cd-accounts", dag.AgGrid(
                                id="cd-accounts-grid", rowData=[], columnDefs=ACCOUNT_COLUMNS,
                                       defaultColDef={"sortable": True, "suppressMovable": True},
                                       dashGridOptions={"rowHeight": 52, "headerHeight": 40,
                                                        "domLayout": "autoHeight",
                                                        "suppressCellFocus": True,
                                                        "getRowId": {"function": "params.data.id"}},
                                       className="ts-grid", style={"width": "100%"})),
                        ],
                        className="ts-card ts-overflow-hidden ts-mt-6",
                    ),
                    footer(),
                    dmc.Drawer(id="cd-drawer", opened=False, position="right", size=600,
                               padding=24, title=html.Div(id="cd-drawer-title"),
                               overlayProps={"color": "#003D5C", "backgroundOpacity": 0.25},
                               classNames={"title": "ts-drawer-title"},
                               children=html.Div(id="cd-drawer-body")),
                    add_account_modal(),
                    edit_client_modal(),
                ],
                className="ts-detail",
            ),
        ],
        className="ts-page",
    )
