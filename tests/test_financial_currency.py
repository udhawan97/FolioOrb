# pylint: disable=protected-access
"""Fail-closed allowlists for persisted USD financial provenance."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, DcaContribution, DcaPlan, Portfolio, RealizedTrade
from app.services import financial_currency
from app.services.dca_ledger import DcaConflictError, DcaLedger


def test_realized_sale_python_policy_allows_only_supported_sale_sources():
    for source in financial_currency.TRUSTED_SALE_PRICE_SOURCES:
        assert financial_currency.is_trusted_reporting_fact(" USD ", source.upper())

    for source in (
        None,
        "",
        "legacy_unknown",
        "future_provider",
        "restored_verified",
        "ticker_validation",
        "validated_plan",
    ):
        assert not financial_currency.is_trusted_reporting_fact("USD", source)


def test_realized_sale_sql_policy_excludes_unknown_and_cross_domain_sources():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add(Portfolio(id=1, name="Disposable"))
    sources = [
        "manual_entry",
        "market_quote",
        "legacy_unknown",
        "future_provider",
        "restored_verified",
        "ticker_validation",
        "validated_plan",
    ]
    for index, source in enumerate(sources, start=1):
        db.add(
            RealizedTrade(
                id=index,
                portfolio_id=1,
                ticker="DEMO",
                shares_sold=1,
                sale_price=110,
                avg_cost=100,
                realized_gain=10,
                sale_currency="USD",
                sale_price_source=source,
            )
        )
    db.commit()

    included = (
        db.query(RealizedTrade.sale_price_source)
        .filter(
            financial_currency.trusted_reporting_fact_clause(
                RealizedTrade.sale_currency,
                RealizedTrade.sale_price_source,
            )
        )
        .order_by(RealizedTrade.id)
        .all()
    )

    assert [row[0] for row in included] == ["manual_entry", "market_quote"]


def test_supported_domestic_dca_sources_still_pass_ledger_guards():
    plan = DcaPlan(
        quote_currency="USD",
        quote_currency_source=next(
            iter(financial_currency.TRUSTED_DCA_PLAN_CURRENCY_SOURCES)
        ),
    )
    contribution = DcaContribution(
        plan=plan,
        price_currency="USD",
        price_currency_source=next(
            iter(financial_currency.TRUSTED_DCA_CONTRIBUTION_CURRENCY_SOURCES)
        ),
    )

    DcaLedger._require_trusted_contribution(contribution)


@pytest.mark.parametrize("layer", ["plan", "contribution"])
@pytest.mark.parametrize("unknown_source", ["future_provider", "restored_verified"])
def test_unknown_dca_sources_remain_rejected(layer, unknown_source):
    plan = DcaPlan(
        quote_currency="USD",
        quote_currency_source="ticker_validation",
    )
    contribution = DcaContribution(
        plan=plan,
        price_currency="USD",
        price_currency_source="validated_plan",
    )
    if layer == "plan":
        plan.quote_currency_source = unknown_source
    else:
        contribution.price_currency_source = unknown_source

    with pytest.raises(DcaConflictError, match="trusted USD currency provenance"):
        DcaLedger._require_trusted_contribution(contribution)
