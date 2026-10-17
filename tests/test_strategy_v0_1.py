from datetime import UTC, datetime
from decimal import Decimal

import pytest

from stock_factor_engine.strategy.v0_1 import (
    CONFIG,
    CandidateSnapshot,
    classic_greenblatt_targets,
    eligibility,
    estimate_transaction_cost,
    monthly_rotation_targets,
    rank_candidates,
    weekly_continuous_targets,
)


AS_OF = datetime(2026, 10, 9, 20, tzinfo=UTC)


def candidate(symbol, *, quality=10, value=10, fcf_margin=10, leverage=1,
              fcf_yield=5, momentum12=10, momentum6=10, volatility=10,
              drawdown=-10, member=True, sector="Industrials", price=100,
              sessions=300, ebit=100):
    return CandidateSnapshot(
        symbol=symbol,
        as_of=AS_OF,
        is_sp500_member=member,
        sector=sector,
        price=Decimal(str(price)) if price is not None else None,
        completed_sessions=sessions,
        ebit_ttm=Decimal(str(ebit)) if ebit is not None else None,
        return_on_capital=Decimal(str(quality)) if quality is not None else None,
        earnings_yield=Decimal(str(value)) if value is not None else None,
        fcf_margin=Decimal(str(fcf_margin)) if fcf_margin is not None else None,
        net_debt_to_ebitda=Decimal(str(leverage)) if leverage is not None else None,
        fcf_yield=Decimal(str(fcf_yield)) if fcf_yield is not None else None,
        momentum_12_1=Decimal(str(momentum12)) if momentum12 is not None else None,
        momentum_6_1=Decimal(str(momentum6)) if momentum6 is not None else None,
        volatility_63=Decimal(str(volatility)) if volatility is not None else None,
        max_drawdown_252=Decimal(str(drawdown)) if drawdown is not None else None,
    )


def ranked_universe(size=40):
    rows = [candidate(f"S{i:02d}", quality=i, value=i, fcf_margin=i,
                      leverage=size + 1 - i, fcf_yield=i, momentum12=i,
                      momentum6=i, volatility=size + 1 - i, drawdown=-(size + 1 - i))
            for i in range(1, size + 1)]
    return rank_candidates(rows, model="greenblatt")


def test_v01_universe_rules_have_no_extra_market_cap_filter():
    assert CONFIG.universe == "point-in-time S&P 500"
    assert CONFIG.minimum_market_cap is None
    assert CONFIG.minimum_price == Decimal("5")
    assert CONFIG.minimum_completed_sessions == 252

    assert eligibility(candidate("OK", price=5)).eligible
    for row, expected in [
        (candidate("FIN", sector="Financials"), "Excluded sector"),
        (candidate("UTL", sector="Utilities"), "Excluded sector"),
        (candidate("LOW", price=Decimal("4.99")), "Price below"),
        (candidate("NEW", sessions=251), "Fewer than 252"),
        (candidate("LOSS", ebit=0), "EBIT is not positive"),
        (candidate("OUT", member=False), "Not a point-in-time"),
    ]:
        result = eligibility(row)
        assert not result.eligible
        assert any(expected in reason for reason in result.reasons)


def test_greenblatt_ranking_is_equal_weight_quality_and_value_with_deterministic_ties():
    result = rank_candidates([
        candidate("A", quality=30, value=30),
        candidate("B", quality=20, value=20),
        candidate("C", quality=10, value=10),
    ], model="greenblatt")
    assert [item.symbol for item in result.ranked] == ["A", "B", "C"]
    assert result.ranked[0].score == 100
    assert result.ranked[1].score == 50
    assert result.ranked[2].score == 0

    tied = rank_candidates([candidate("B"), candidate("A")], model="greenblatt")
    assert [item.symbol for item in tied.ranked] == ["A", "B"]
    assert all(item.score == 50 for item in tied.ranked)


def test_compounder_score_combines_quality_value_momentum_and_risk():
    result = rank_candidates([
        candidate("BEST", quality=30, value=30, fcf_margin=30, leverage=1,
                  fcf_yield=30, momentum12=30, momentum6=30, volatility=1, drawdown=-1),
        candidate("MID", quality=20, value=20, fcf_margin=20, leverage=2,
                  fcf_yield=20, momentum12=20, momentum6=20, volatility=2, drawdown=-2),
        candidate("WORST", quality=10, value=10, fcf_margin=10, leverage=3,
                  fcf_yield=10, momentum12=10, momentum6=10, volatility=3, drawdown=-3),
    ], model="compounder")
    assert [item.symbol for item in result.ranked] == ["BEST", "MID", "WORST"]
    assert result.ranked[0].score == 100
    assert result.ranked[1].score == 50
    assert result.ranked[2].score == 0
    assert result.ranked[0].components["quality"] == 100
    assert result.ranked[0].components["risk"] == 100


def test_missing_or_invalid_factor_excludes_only_that_candidate():
    result = rank_candidates([
        candidate("GOOD"),
        candidate("MISSING", momentum6=None),
        candidate("BADVOL", volatility=-1),
        candidate("BADDRAW", drawdown=1),
    ], model="compounder")
    assert [item.symbol for item in result.ranked] == ["GOOD"]
    reasons = {item.symbol: item.reasons for item in result.excluded}
    assert any("momentum_6_1" in reason for reason in reasons["MISSING"])
    assert "volatility_63 must not be negative" in reasons["BADVOL"]
    assert "max_drawdown_252 must be zero or negative" in reasons["BADDRAW"]


def test_classic_greenblatt_is_top_30_equal_weight():
    ranking = ranked_universe()
    targets = classic_greenblatt_targets(ranking)
    assert len(targets) == 30
    assert set(targets) == {item.symbol for item in ranking.ranked[:30]}
    assert sum(targets.values(), Decimal(0)) == 1
    assert max(targets.values()) - min(targets.values()) < Decimal("1e-26")


def test_monthly_rotation_uses_20_35_hysteresis():
    ranking = ranked_universe()
    by_rank = {item.rank: item.symbol for item in ranking.ranked}
    targets = monthly_rotation_targets(ranking, [by_rank[10], by_rank[25], by_rank[36], "OLD"])
    assert set(by_rank[i] for i in range(1, 21)).issubset(targets)
    assert by_rank[25] in targets
    assert by_rank[36] not in targets
    assert "OLD" not in targets
    assert len(targets) == 21
    assert sum(targets.values(), Decimal(0)) == 1


def test_weekly_continuous_weighting_favors_better_ranks():
    ranking = ranked_universe()
    targets = weekly_continuous_targets(ranking)
    by_rank = {item.rank: item.symbol for item in ranking.ranked}
    assert len(targets) == 35
    assert sum(targets.values(), Decimal(0)) == 1
    assert targets[by_rank[1]] > targets[by_rank[10]] > targets[by_rank[35]]
    assert targets[by_rank[1]] == Decimal(35) / Decimal(630)
    assert abs(targets[by_rank[35]] - Decimal(1) / Decimal(630)) < Decimal("1e-26")


def test_transaction_cost_is_per_traded_notional():
    initial = estimate_transaction_cost({}, {"A": Decimal(1)})
    switch = estimate_transaction_cost({"A": Decimal(1)}, {"B": Decimal(1)})
    unchanged = estimate_transaction_cost({"A": Decimal(1)}, {"A": Decimal(1)})
    assert initial == Decimal("0.001")
    assert switch == Decimal("0.002")
    assert unchanged == 0


def test_batch_rejects_mixed_asof_and_duplicate_symbols():
    with pytest.raises(ValueError, match="unique"):
        rank_candidates([candidate("A"), candidate("A")], model="greenblatt")
    later = candidate("B")
    later = CandidateSnapshot(**{**later.__dict__, "as_of": datetime(2026, 10, 10, 20, tzinfo=UTC)})
    with pytest.raises(ValueError, match="same as_of"):
        rank_candidates([candidate("A"), later], model="greenblatt")
