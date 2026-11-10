"""/login — port of reference/react-ui/app/login/page.tsx."""

from __future__ import annotations

import dash
from dash import dcc, html

from components.shell import FOOTER_TEXT, icon, logo_chip

dash.register_page(__name__, path="/login", title="Sign in · Transition Studio")

ILLUSTRATION = html.Div(
    [
        html.Div(className="ts-login-glow"),
        html.Img(src="/assets/login-art.svg", className="ts-login-art", alt="", **{"aria-hidden": "true"}),
        html.Div(
            [
                html.Div(icon("shield-check", 28, "ts-c-primary"), className="ts-login-tile"),
                html.P("Precision for every transition", className="ts-login-kicker"),
                html.H2("Transition client portfolios with precision.", className="ts-login-headline"),
                html.P(
                    "Minimize tracking error, control taxes, and make every recommendation easier "
                    "to explain.",
                    className="ts-login-sub",
                ),
                html.Div(
                    [
                        html.Span([icon("check", 16, "ts-c-primary"), label], className="ts-login-tick")
                        for label in ("Tax-aware", "Advisor-led", "Transparent")
                    ],
                    className="ts-login-ticks",
                ),
            ],
            className="ts-login-copy",
        ),
    ],
    className="ts-login-panel",
)


def _field(label: str, icon_name: str, input_: object, trailing: object | None = None) -> html.Label:
    return html.Label(
        [
            label,
            html.Div(
                [icon(icon_name, 17, "ts-input-icon"), input_, *( [trailing] if trailing else [])],
                className="ts-input-wrap",
            ),
        ],
        className="ts-field",
    )


def layout(**_: object) -> html.Main:
    return html.Main(
        [
            html.Section(
                html.Div(
                    [
                        html.Div(
                            [logo_chip(large=True),
                             html.Span("Transition Studio", className="ts-login-brand")],
                            className="ts-row ts-gap-3 ts-mb-12",
                        ),
                        html.Div(
                            [
                                html.P("Advisor workspace", className="ts-eyebrow ts-eyebrow--wide ts-mb-3"),
                                html.H1("Welcome back", className="ts-h1"),
                                html.P(
                                    "Sign in to review client portfolios and guide their next "
                                    "transition.",
                                    className="ts-lede ts-mt-3",
                                ),
                            ],
                            className="ts-mb-8",
                        ),
                        html.Div(
                            [
                                _field(
                                    "Email address", "mail",
                                    dcc.Input(id="login-email", type="email", value="demo@advisor.test",
                                              autoComplete="email", placeholder="you@firm.com",
                                              className="ts-input ts-input--icon", debounce=False),
                                ),
                                _field(
                                    "Password", "lock-keyhole",
                                    dcc.Input(id="login-password", type="password", value="demo1234",
                                              autoComplete="current-password",
                                              placeholder="Enter your password",
                                              className="ts-input ts-input--icon ts-input--trail",
                                              n_submit=0),
                                    html.Button([icon("eye", 18, "ts-eye-show"),
                                                 icon("eye-off", 18, "ts-eye-hide")],
                                                id="login-eye", type="button",
                                                className="ts-input-trailing",
                                                **{"aria-label": "Show password"}),
                                ),
                                html.Div(
                                    [
                                        html.Label(
                                            [dcc.Checklist(id="login-remember",
                                                           options=[{"label": "", "value": "remember"}],
                                                           value=["remember"], className="ts-check",
                                                           inline=True),
                                             "Remember me"],
                                            className="ts-check-label",
                                        ),
                                        html.Button("Forgot password?", type="button",
                                                    className="ts-link-btn"),
                                    ],
                                    className="ts-row ts-between",
                                ),
                                html.Div(id="login-error", className="ts-hidden", role="alert"),
                                html.Button(
                                    ["Sign in ", icon("arrow-right", 17)],
                                    id="login-submit", type="button", n_clicks=0,
                                    className="ts-btn ts-btn-primary ts-btn-lg ts-w-full",
                                ),
                            ],
                            className="ts-form",
                        ),
                        html.Div(
                            [
                                html.P("Demo access", className="ts-demo-title"),
                                html.P(
                                    ["Use ", html.Span("demo@advisor.test", className="ts-demo-em"),
                                     " with password ", html.Span("demo1234", className="ts-demo-em")],
                                    className="ts-demo-text",
                                ),
                            ],
                            className="ts-demo-box",
                        ),
                        html.P(FOOTER_TEXT, className="ts-login-footer"),
                    ],
                    className="ts-login-form-wrap",
                ),
                className="ts-login-left",
            ),
            ILLUSTRATION,
        ],
        className="ts-login",
    )
