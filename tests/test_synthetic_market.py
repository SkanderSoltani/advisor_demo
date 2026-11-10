from __future__ import annotations

import numpy as np
import pandas as pd

from app.db.synthetic_market import SECTORS, SyntheticMarket, generate_market
from tests.conftest import TEST_AS_OF, TEST_SEED


def test_shapes_and_reference_data(market: SyntheticMarket) -> None:
    u = market.universe
    assert len(u) == 300
    assert u.index.is_unique
    assert set(u["sector"]) <= set(SECTORS)
    assert u["name"].is_unique
    assert (u["market_cap"] > 1e9).all()
    assert u["dividend_yield"].between(0, 0.08).all()
    for col in ("value", "quality", "profitability", "momentum"):
        assert u[col].abs().max() <= 3.0 + 1e-9
    assert market.prices.shape == (5 * 252 + 1, 300)
    assert market.as_of == TEST_AS_OF
    assert (market.prices > 0).all().all()


def test_deterministic_under_seed(market: SyntheticMarket) -> None:
    again = generate_market(seed=TEST_SEED, as_of=TEST_AS_OF, n_names=300, years=5)
    pd.testing.assert_frame_equal(market.universe, again.universe)
    pd.testing.assert_frame_equal(market.prices, again.prices)
    other = generate_market(seed=TEST_SEED + 1, as_of=TEST_AS_OF, n_names=300, years=5)
    assert not np.allclose(market.prices.to_numpy(), other.prices.to_numpy())


def test_realistic_return_statistics(market: SyntheticMarket) -> None:
    r = market.returns
    vol = r.std() * np.sqrt(252)
    assert 0.15 < vol.median() < 0.40
    corr = r.corr().to_numpy()
    avg_pair = (corr.sum() - len(corr)) / (len(corr) * (len(corr) - 1))
    assert 0.1 < avg_pair < 0.5
    # same-sector names co-move more than cross-sector names (sector factors are real)
    sec = market.universe["sector"].to_numpy()
    same = sec[:, None] == sec[None, :]
    np.fill_diagonal(same, False)
    cross = sec[:, None] != sec[None, :]
    assert corr[same].mean() > corr[cross].mean() + 0.05
    # cap-weighted index ends up over 5 years (pinned market drift) with a drawdown on the way
    w = market.universe["market_cap"] / market.universe["market_cap"].sum()
    idx = (market.prices / market.prices.iloc[0]) @ w
    assert idx.iloc[-1] > 1.1
    assert (1 - idx / idx.cummax()).max() > 0.05


def test_save_load_roundtrip(market: SyntheticMarket, tmp_path) -> None:  # type: ignore[no-untyped-def]
    market.save(tmp_path)
    assert SyntheticMarket.exists(tmp_path)
    loaded = SyntheticMarket.load(tmp_path)
    assert list(loaded.universe.index) == list(market.universe.index)
    np.testing.assert_allclose(loaded.prices.to_numpy(), market.prices.to_numpy(), atol=1e-4)
