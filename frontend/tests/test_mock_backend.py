"""The mock backend must return exactly the openapi shapes (validated by the generated schemas),
be stable across calls, and script both conversation paths."""

from __future__ import annotations

import pytest

from services import schemas as s
from services.api_client import ApiClient, ApiError, AuthError


@pytest.fixture()
def api() -> ApiClient:
    tok = ApiClient(use_mocks=True).login("demo@advisor.test", "demo1234")
    return ApiClient(tok.access_token, use_mocks=True)


def test_auth() -> None:
    with pytest.raises(AuthError):
        ApiClient(use_mocks=True).login("demo@advisor.test", "nope")
    with pytest.raises(AuthError):
        ApiClient("bad", use_mocks=True).book_summary()


def test_book_and_clients_shapes(api: ApiClient) -> None:
    b = api.book_summary()
    assert b.data_source == "mock_random" and b.n_clients == 9
    for w in (63, 252):
        te = api.book_tracking_error(w)
        assert te.series and all(p.p10 <= p.p90 for p in te.series)
    for g in ("month", "year"):
        assert api.book_tax_impact(g).periods
        assert api.book_activity(g).periods
    rows = api.clients().items
    assert {r.name for r in rows} >= {"Maya & Daniel Chen", "Priya Shah Family Trust"}
    assert any(r.status.value == "onboarding" for r in rows)
    assert len(api.clients(search="chen").items) == 1
    assert api.book_summary() == b  # stable across refreshes


def test_client_detail_shapes(api: ApiClient) -> None:
    d = api.client("cl-001")
    assert len(d.accounts) == 3 and d.tax_profile.state == "CA"
    aid = d.accounts[0].id
    for acct in (None, aid):
        api.client_tracking_error("cl-001", 63, acct)
        api.client_tax_savings("cl-001", "year", acct)
        api.client_summary("cl-001", acct)
        ev = api.client_events("cl-001", account_id=acct)
        assert ev.items
    e = api.event(ev.items[0].id)
    assert e.trades and e.client_id == "cl-001"
    a = api.account(aid)
    assert 20 <= a.account.n_positions <= 60
    api.account_exposures(aid)
    new = api.client("cl-009")
    assert new.status.value == "onboarding" and not api.client_events("cl-009").items
    with pytest.raises(ApiError) as exc:
        api.client("nope")
    assert exc.value.status == 404


def test_models(api: ApiClient) -> None:
    ms = api.models()
    assert [m.id for m in ms.items] == ["SCHWAB-TR", "SCHWAB-INC"]
    assert api.model("SCHWAB-INC").holdings
    cmp = api.compare(["SCHWAB-TR", "SCHWAB-INC"], "cl-001-acct-1")
    assert len(cmp.comparisons) == 2


def test_onboarding_and_help_path(api: ApiClient) -> None:
    c = api.create_client({"name": "Rivera Household", "email": "rivera@example.com",
                           "client_type": "couple", "tax_profile": {
                               "federal_st_rate": .35, "federal_lt_rate": .2, "state": "ca",
                               "state_rate": .133}})
    acct = api.create_account(c.id, {"account_type": "joint_taxable", "custodian": "Schwab"})
    t = api.create_transition(c.id, acct.id)
    turn = api.chat(t.transition_id)
    assert turn.state == "INGEST_CHOICE" and turn.ui_payload.type.value == "ingest_choice"
    pv = api.upload_pdf(t.transition_id, "s.pdf", b"%PDF-1.4 fake")
    assert pv.summary.n_error_rows == 1
    turn = api.chat(t.transition_id)
    assert turn.state == "INGEST_REVIEW"
    turn = api.chat(t.transition_id, quick_reply="accept_suggestions")
    assert turn.state == "TARGET_KNOWLEDGE"
    for qr, state in (("help", "Q_OBJECTIVE"), ("objective:income", "Q_CONSTRUCTION"),
                      ("construction:market_cap_fundamental", "TARGET_COMPARE"),
                      ("choose:SCHWAB-INC", "TARGET_CONFIRM"), ("yes", "TRANSITION_SETUP")):
        turn = api.chat(t.transition_id, quick_reply=qr)
        assert turn.state == state, (qr, turn.assistant_message)
    turn = api.chat(t.transition_id, message="keep taxes under 20k")
    assert turn.state == "TRANSITION_RESULTS"
    opt = s.OptimizationResult.model_validate(turn.ui_payload.data["optimization"])
    assert opt.realized.est_tax <= 20_000
    s.FrontierResult.model_validate(turn.ui_payload.data["frontier"])
    assert api.trades_csv(t.transition_id).startswith(b'"# Transition Studio')
    assert api.summary_pdf(t.transition_id).startswith(b"%PDF")
    turn = api.chat(t.transition_id, quick_reply="approve")
    turn = api.chat(t.transition_id, action="approve")
    assert turn.state == "DONE"
    assert api.client_events(c.id).total == 1
    assert api.history(t.transition_id).items


def test_knows_path_locks_frontier_and_back(api: ApiClient) -> None:
    t = api.create_transition("cl-002", "cl-002-acct-1")
    api.chat(t.transition_id, quick_reply="use_existing")
    turn = api.chat(t.transition_id, quick_reply="knows")
    assert turn.state == "TARGET_PICK_LIST" and turn.ui_payload.type.value == "model_list"
    api.chat(t.transition_id, quick_reply="choose:SCHWAB-TR")
    api.chat(t.transition_id, quick_reply="yes")
    lots = api.account("cl-002-acct-1").lots
    api.set_locks(t.transition_id, [lots[0].lot_id])
    tes = [api.optimize(t.transition_id, {"budget_mode": "tax", "budget_value": b}).post.te
           for b in (0, 5_000, 20_000)]
    assert tes == sorted(tes, reverse=True)
    opt = api.optimize(t.transition_id, {"budget_mode": "none"})
    assert lots[0].lot_id not in {x.lot_id for x in opt.trades.sells}
    fr = api.frontier(t.transition_id, {"n_points": 20})
    assert len(fr.points) == 20
    turn = api.back(t.transition_id, "TARGET_KNOWLEDGE")
    assert turn.state == "TARGET_KNOWLEDGE"
    pv = api.plaid_exchange(t.transition_id, api.plaid_link_token().mock_public_token or "")
    assert pv.requires_basis_decision
