"""Conservative Compounder / Greenblatt rotation strategy kernel v0.1.

This module deliberately contains no data fetching and no broker execution.
Inputs must already be point-in-time snapshots constructed from information that
was available at ``as_of``.  The strategy kernel is therefore deterministic and
can be used by reports, backtests, and later execution adapters without hiding
provider I/O inside ranking logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext
from enum import StrEnum
from typing import Iterable, Mapping


ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")
BPS_DENOMINATOR = Decimal("10000")


class RuleOrigin(StrEnum):
    GREENBLATT = "GREENBLATT"
    GOTHAM = "GOTHAM"
    ACADEMIC = "ACADEMIC"
    BACKTEST_PRACTICE = "BACKTEST_PRACTICE"
    DESIGN_CHOICE = "DESIGN_CHOICE"


@dataclass(frozen=True)
class RuleSpec:
    key: str
    value: str
    origin: RuleOrigin
    note: str


@dataclass(frozen=True)
class StrategyConfig:
    universe: str = "point-in-time S&P 500"
    excluded_sectors: frozenset[str] = frozenset({"Financials", "Utilities"})
    minimum_price: Decimal = Decimal("5")
    minimum_completed_sessions: int = 252
    require_positive_ebit: bool = True
    minimum_market_cap: Decimal | None = None
    winsor_lower: Decimal = Decimal("0.01")
    winsor_upper: Decimal = Decimal("0.99")
    classic_portfolio_size: int = 30
    monthly_entry_rank: int = 20
    monthly_exit_rank: int = 35
    continuous_portfolio_size: int = 35
    transaction_cost_bps: Decimal = Decimal("10")
    transaction_cost_sensitivity_bps: tuple[Decimal, ...] = (
        Decimal("0"), Decimal("10"), Decimal("25")
    )
    signal_basis: str = "completed-session close"
    execution_basis: str = "next-session open"


CONFIG = StrategyConfig()

RULES = (
    RuleSpec("universe", CONFIG.universe, RuleOrigin.DESIGN_CHOICE,
             "Historical membership must be known at each as-of date; never use today's constituents backwards."),
    RuleSpec("market_cap_filter", "none for S&P 500 v0.1", RuleOrigin.DESIGN_CHOICE,
             "A >= $1B filter is reserved for a later broader-US universe."),
    RuleSpec("sector_exclusions", "Financials, Utilities", RuleOrigin.GREENBLATT,
             "Keep the first benchmark close to the classic Magic Formula universe treatment."),
    RuleSpec("greenblatt_score", "50% ROC percentile + 50% EBIT/EV percentile", RuleOrigin.GREENBLATT,
             "Transparent Greenblatt-inspired cross-sectional ranking."),
    RuleSpec("classic_portfolio", "top 30, equal weight, annual rebalance", RuleOrigin.GREENBLATT,
             "Control portfolio for the active variants."),
    RuleSpec("monthly_rotation", "buy <= 20; keep <= 35; sell > 35", RuleOrigin.DESIGN_CHOICE,
             "A rank buffer is used to reduce churn; the numeric thresholds are a test hypothesis."),
    RuleSpec("continuous_weighting", "weekly top 35; raw weight = 36 - rank", RuleOrigin.DESIGN_CHOICE,
             "Inspired by Gotham's relative-value reweighting, not a claim about Gotham's proprietary formula."),
    RuleSpec("momentum", "60% 12-1 + 40% 6-1", RuleOrigin.ACADEMIC,
             "Skip the most recent month; the 60/40 mix is a design choice."),
    RuleSpec("quality", "50% ROC + 30% FCF margin + 20% inverse Net Debt/EBITDA", RuleOrigin.DESIGN_CHOICE,
             "Multi-metric quality extension beyond the classic Magic Formula."),
    RuleSpec("value", "60% EBIT/EV + 40% FCF yield", RuleOrigin.DESIGN_CHOICE,
             "Keeps EBIT/EV central while adding cash-flow valuation."),
    RuleSpec("risk", "60% inverse 63-session volatility + 40% inverse |252-session max drawdown|",
             RuleOrigin.DESIGN_CHOICE, "Risk is rewarded when volatility and drawdown magnitude are lower."),
    RuleSpec("final_score", "40% Quality + 25% Value + 20% Momentum + 15% Risk",
             RuleOrigin.DESIGN_CHOICE, "Locked v0.1 factor mix; do not tune after seeing the same backtest."),
    RuleSpec("execution", "signal at completed close; execute at next session open",
             RuleOrigin.BACKTEST_PRACTICE, "Avoid using the same close both to create a signal and fill the trade."),
    RuleSpec("cost", "10 bps per traded notional; sensitivity 0/10/25 bps",
             RuleOrigin.BACKTEST_PRACTICE, "A full A->B switch trades two notionals and therefore costs 20 bps at 10 bps."),
)


@dataclass(frozen=True)
class CandidateSnapshot:
    """One security's strategy inputs at one point in time.

    Upstream code owns provenance and must only populate these fields from data
    legally available at ``as_of``.  Values are ratios (0.10 == 10%), not
    percentages.
    """

    symbol: str
    as_of: datetime
    is_sp500_member: bool
    sector: str | None
    price: Decimal | None
    completed_sessions: int
    ebit_ttm: Decimal | None
    return_on_capital: Decimal | None
    earnings_yield: Decimal | None
    fcf_margin: Decimal | None
    net_debt_to_ebitda: Decimal | None
    fcf_yield: Decimal | None
    momentum_12_1: Decimal | None
    momentum_6_1: Decimal | None
    volatility_63: Decimal | None
    max_drawdown_252: Decimal | None

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol must not be blank")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if self.completed_sessions < 0:
            raise ValueError("completed_sessions must not be negative")


@dataclass(frozen=True)
class Eligibility:
    eligible: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExcludedCandidate:
    symbol: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RankedCandidate:
    symbol: str
    rank: int
    score: Decimal
    components: Mapping[str, Decimal]


@dataclass(frozen=True)
class RankingResult:
    model: str
    as_of: datetime
    ranked: tuple[RankedCandidate, ...]
    excluded: tuple[ExcludedCandidate, ...]


_GREENBLATT_METRICS = ("return_on_capital", "earnings_yield")
_COMPOUNDER_METRICS = (
    "return_on_capital",
    "fcf_margin",
    "net_debt_to_ebitda",
    "earnings_yield",
    "fcf_yield",
    "momentum_12_1",
    "momentum_6_1",
    "volatility_63",
    "max_drawdown_252",
)


def _is_finite(value: Decimal | None) -> bool:
    return value is not None and value.is_finite()


def eligibility(candidate: CandidateSnapshot, *, config: StrategyConfig = CONFIG) -> Eligibility:
    reasons: list[str] = []
    if not candidate.is_sp500_member:
        reasons.append("Not a point-in-time S&P 500 member")
    if candidate.sector is None:
        reasons.append("Sector unavailable")
    elif candidate.sector in config.excluded_sectors:
        reasons.append(f"Excluded sector: {candidate.sector}")
    if not _is_finite(candidate.price):
        reasons.append("Price unavailable or non-finite")
    elif candidate.price < config.minimum_price:
        reasons.append(f"Price below ${config.minimum_price}")
    if candidate.completed_sessions < config.minimum_completed_sessions:
        reasons.append(f"Fewer than {config.minimum_completed_sessions} completed sessions")
    if config.require_positive_ebit:
        if not _is_finite(candidate.ebit_ttm):
            reasons.append("TTM EBIT unavailable or non-finite")
        elif candidate.ebit_ttm <= 0:
            reasons.append("TTM EBIT is not positive")
    return Eligibility(not reasons, tuple(reasons))


def _quantile(values: list[Decimal], q: Decimal) -> Decimal:
    if not values:
        raise ValueError("Cannot calculate quantile of an empty series")
    if not ZERO <= q <= ONE:
        raise ValueError("Quantile must be in [0, 1]")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    with localcontext() as context:
        context.prec = 34
        position = Decimal(len(ordered) - 1) * q
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        fraction = position - Decimal(lower)
        return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _winsorize(values: Mapping[str, Decimal], *, lower: Decimal, upper: Decimal) -> dict[str, Decimal]:
    if not ZERO <= lower < upper <= ONE:
        raise ValueError("Winsor bounds must satisfy 0 <= lower < upper <= 1")
    low = _quantile(list(values.values()), lower)
    high = _quantile(list(values.values()), upper)
    return {symbol: min(max(value, low), high) for symbol, value in values.items()}


def _percentile_ranks(values: Mapping[str, Decimal], *, higher_is_better: bool,
                      config: StrategyConfig) -> dict[str, Decimal]:
    clipped = _winsorize(values, lower=config.winsor_lower, upper=config.winsor_upper)
    oriented = {symbol: value if higher_is_better else -value for symbol, value in clipped.items()}
    ordered_values = sorted(oriented.values())
    if len(ordered_values) == 1:
        return {next(iter(oriented)): HUNDRED}
    positions: dict[Decimal, tuple[int, int]] = {}
    for index, value in enumerate(ordered_values):
        if value not in positions:
            positions[value] = (index, index)
        else:
            positions[value] = (positions[value][0], index)
    denominator = Decimal(len(ordered_values) - 1)
    result = {}
    with localcontext() as context:
        context.prec = 34
        for symbol, value in oriented.items():
            first, last = positions[value]
            average_position = (Decimal(first) + Decimal(last)) / Decimal(2)
            result[symbol] = HUNDRED * average_position / denominator
    return result


def _validate_batch(candidates: tuple[CandidateSnapshot, ...]) -> datetime:
    if not candidates:
        raise ValueError("At least one candidate is required")
    symbols = [candidate.symbol for candidate in candidates]
    if len(set(symbols)) != len(symbols):
        raise ValueError("Candidate symbols must be unique")
    as_of = candidates[0].as_of
    if any(candidate.as_of != as_of for candidate in candidates[1:]):
        raise ValueError("All candidate snapshots must use the same as_of instant")
    return as_of


def _metric_reasons(candidate: CandidateSnapshot, names: Iterable[str]) -> tuple[str, ...]:
    reasons = []
    for name in names:
        value = getattr(candidate, name)
        if not _is_finite(value):
            reasons.append(f"{name} unavailable or non-finite")
    if _is_finite(candidate.volatility_63) and candidate.volatility_63 < 0:
        reasons.append("volatility_63 must not be negative")
    if _is_finite(candidate.max_drawdown_252) and candidate.max_drawdown_252 > 0:
        reasons.append("max_drawdown_252 must be zero or negative")
    return tuple(reasons)


def _score_greenblatt(candidates: tuple[CandidateSnapshot, ...], config: StrategyConfig):
    raw_roc = {candidate.symbol: candidate.return_on_capital for candidate in candidates}
    raw_yield = {candidate.symbol: candidate.earnings_yield for candidate in candidates}
    roc = _percentile_ranks(raw_roc, higher_is_better=True, config=config)
    value = _percentile_ranks(raw_yield, higher_is_better=True, config=config)
    scores = {}
    for candidate in candidates:
        symbol = candidate.symbol
        score = (roc[symbol] + value[symbol]) / Decimal(2)
        scores[symbol] = (score, {
            "return_on_capital_percentile": roc[symbol],
            "earnings_yield_percentile": value[symbol],
            "quality": roc[symbol],
            "value": value[symbol],
        })
    return scores


def _score_compounder(candidates: tuple[CandidateSnapshot, ...], config: StrategyConfig):
    def ranks(name: str, *, higher=True, transform=lambda value: value):
        values = {candidate.symbol: transform(getattr(candidate, name)) for candidate in candidates}
        return _percentile_ranks(values, higher_is_better=higher, config=config)

    roc = ranks("return_on_capital")
    fcf_margin = ranks("fcf_margin")
    leverage = ranks("net_debt_to_ebitda", higher=False)
    earnings_yield = ranks("earnings_yield")
    fcf_yield = ranks("fcf_yield")
    momentum_12_1 = ranks("momentum_12_1")
    momentum_6_1 = ranks("momentum_6_1")
    volatility = ranks("volatility_63", higher=False)
    drawdown = ranks("max_drawdown_252", higher=False, transform=abs)

    scores = {}
    with localcontext() as context:
        context.prec = 34
        for candidate in candidates:
            symbol = candidate.symbol
            quality = (Decimal("0.50") * roc[symbol] + Decimal("0.30") * fcf_margin[symbol]
                       + Decimal("0.20") * leverage[symbol])
            value = Decimal("0.60") * earnings_yield[symbol] + Decimal("0.40") * fcf_yield[symbol]
            momentum = Decimal("0.60") * momentum_12_1[symbol] + Decimal("0.40") * momentum_6_1[symbol]
            risk = Decimal("0.60") * volatility[symbol] + Decimal("0.40") * drawdown[symbol]
            final = (Decimal("0.40") * quality + Decimal("0.25") * value
                     + Decimal("0.20") * momentum + Decimal("0.15") * risk)
            scores[symbol] = (final, {
                "quality": quality,
                "value": value,
                "momentum": momentum,
                "risk": risk,
                "return_on_capital_percentile": roc[symbol],
                "fcf_margin_percentile": fcf_margin[symbol],
                "net_debt_to_ebitda_percentile": leverage[symbol],
                "earnings_yield_percentile": earnings_yield[symbol],
                "fcf_yield_percentile": fcf_yield[symbol],
                "momentum_12_1_percentile": momentum_12_1[symbol],
                "momentum_6_1_percentile": momentum_6_1[symbol],
                "volatility_63_percentile": volatility[symbol],
                "max_drawdown_252_percentile": drawdown[symbol],
            })
    return scores


def rank_candidates(candidates: Iterable[CandidateSnapshot], *, model: str,
                    config: StrategyConfig = CONFIG) -> RankingResult:
    candidates = tuple(candidates)
    as_of = _validate_batch(candidates)
    required = _GREENBLATT_METRICS if model == "greenblatt" else _COMPOUNDER_METRICS if model == "compounder" else None
    if required is None:
        raise ValueError("model must be 'greenblatt' or 'compounder'")

    scoreable: list[CandidateSnapshot] = []
    excluded: list[ExcludedCandidate] = []
    for candidate in candidates:
        reasons = list(eligibility(candidate, config=config).reasons)
        reasons.extend(_metric_reasons(candidate, required))
        reasons = list(dict.fromkeys(reasons))
        if reasons:
            excluded.append(ExcludedCandidate(candidate.symbol, tuple(reasons)))
        else:
            scoreable.append(candidate)

    if not scoreable:
        return RankingResult(model, as_of, (), tuple(sorted(excluded, key=lambda item: item.symbol)))

    scoreable_tuple = tuple(scoreable)
    scores = (_score_greenblatt(scoreable_tuple, config) if model == "greenblatt"
              else _score_compounder(scoreable_tuple, config))
    ordered = sorted(scoreable_tuple, key=lambda candidate: (-scores[candidate.symbol][0], candidate.symbol))
    ranked = tuple(RankedCandidate(candidate.symbol, index, scores[candidate.symbol][0],
                                   scores[candidate.symbol][1])
                   for index, candidate in enumerate(ordered, start=1))
    return RankingResult(model, as_of, ranked, tuple(sorted(excluded, key=lambda item: item.symbol)))


def _require_ranking(ranking: RankingResult, minimum: int) -> tuple[RankedCandidate, ...]:
    if len(ranking.ranked) < minimum:
        raise ValueError(f"Need at least {minimum} ranked candidates; got {len(ranking.ranked)}")
    expected = list(range(1, len(ranking.ranked) + 1))
    if [candidate.rank for candidate in ranking.ranked] != expected:
        raise ValueError("Ranking must contain contiguous ranks starting at 1")
    return ranking.ranked


def _normalized_weights(weight_pairs: list[tuple[str, Decimal]]) -> dict[str, Decimal]:
    if not weight_pairs:
        return {}
    total = sum((weight for _, weight in weight_pairs), ZERO)
    if total <= 0:
        raise ValueError("Target raw weights must sum to a positive amount")
    result: dict[str, Decimal] = {}
    # Use the caller-visible Decimal context here and put the rounding residual
    # into the last position.  This keeps the published weight map summing to
    # exactly 1 under the same arithmetic used by the simulator/cost model.
    running = ZERO
    for symbol, raw in weight_pairs[:-1]:
        value = raw / total
        result[symbol] = value
        running += value
    result[weight_pairs[-1][0]] = ONE - running
    return result


def classic_greenblatt_targets(ranking: RankingResult, *, config: StrategyConfig = CONFIG) -> dict[str, Decimal]:
    ranked = _require_ranking(ranking, config.classic_portfolio_size)
    selected = ranked[:config.classic_portfolio_size]
    return _normalized_weights([(candidate.symbol, ONE) for candidate in selected])


def monthly_rotation_targets(ranking: RankingResult, current_holdings: Iterable[str], *,
                             config: StrategyConfig = CONFIG) -> dict[str, Decimal]:
    ranked = _require_ranking(ranking, config.monthly_exit_rank)
    by_symbol = {candidate.symbol: candidate for candidate in ranked}
    keep = {symbol for symbol in current_holdings
            if symbol in by_symbol and by_symbol[symbol].rank <= config.monthly_exit_rank}
    enter = {candidate.symbol for candidate in ranked if candidate.rank <= config.monthly_entry_rank}
    selected = sorted(keep | enter, key=lambda symbol: (by_symbol[symbol].rank, symbol))
    return _normalized_weights([(symbol, ONE) for symbol in selected])


def weekly_continuous_targets(ranking: RankingResult, *, config: StrategyConfig = CONFIG) -> dict[str, Decimal]:
    ranked = _require_ranking(ranking, config.continuous_portfolio_size)
    selected = ranked[:config.continuous_portfolio_size]
    size = config.continuous_portfolio_size
    return _normalized_weights([
        (candidate.symbol, Decimal(size + 1 - candidate.rank)) for candidate in selected
    ])


def _validate_weight_map(weights: Mapping[str, Decimal], *, allow_empty: bool) -> None:
    if not weights and allow_empty:
        return
    if not weights:
        raise ValueError("Weight map must not be empty")
    if any(not weight.is_finite() or weight < 0 for weight in weights.values()):
        raise ValueError("Weights must be finite and non-negative")
    total = sum(weights.values(), ZERO)
    if total != ONE:
        raise ValueError(f"Weights must sum to 1; got {total}")


def estimate_transaction_cost(previous_weights: Mapping[str, Decimal], target_weights: Mapping[str, Decimal], *,
                              cost_bps: Decimal = CONFIG.transaction_cost_bps) -> Decimal:
    """Return cost as a fraction of portfolio NAV.

    Buying from cash trades one notional.  Moving 100% from A to B trades one
    sell notional plus one buy notional, so at 10 bps the modeled cost is 20 bps.
    """
    _validate_weight_map(previous_weights, allow_empty=True)
    _validate_weight_map(target_weights, allow_empty=False)
    if not cost_bps.is_finite() or cost_bps < 0:
        raise ValueError("cost_bps must be finite and non-negative")
    symbols = set(previous_weights) | set(target_weights)
    traded_notional = sum((abs(target_weights.get(symbol, ZERO) - previous_weights.get(symbol, ZERO))
                           for symbol in symbols), ZERO)
    with localcontext() as context:
        context.prec = 34
        return traded_notional * cost_bps / BPS_DENOMINATOR
