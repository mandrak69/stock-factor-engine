from datetime import date

from stock_factor_engine.models.company import Company, Security, TickerAssignment


def test_ticker_history_resolves_without_changing_security_identity() -> None:
    company = Company(
        id="meta",
        legal_name="Meta Platforms, Inc.",
        cik="0001326801",
    )
    security = Security(
        id="meta-nasdaq-common",
        company_id=company.id,
        exchange="NASDAQ",
        currency="USD",
    )
    fb = TickerAssignment(
        security_id=security.id,
        symbol="fb",
        valid_from=date(2012, 5, 18),
        valid_to=date(2022, 6, 8),
    )
    meta = TickerAssignment(
        security_id=security.id,
        symbol="META",
        valid_from=date(2022, 6, 9),
    )

    assert fb.symbol == "FB"
    assert fb.is_valid_on(date(2020, 1, 2))
    assert not fb.is_valid_on(date(2023, 1, 2))
    assert meta.is_valid_on(date(2023, 1, 2))
    assert fb.security_id == meta.security_id == security.id
