"""Scoped security identifiers and issuer alias identity rules."""

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Base, Issuer, IssuerAlias, Security, SecurityIdentifier


def test_security_identifiers_are_scoped_and_alias_collisions_remain_reviewable() -> (
    None
):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    issuer_a_id, issuer_b_id, security_a_id, security_b_id = [uuid4() for _ in range(4)]
    with Session(engine) as session, session.begin():
        session.add_all(
            [
                Issuer(
                    id=issuer_a_id,
                    normalized_name="issuer a",
                    display_name="Issuer A",
                ),
                Issuer(
                    id=issuer_b_id,
                    normalized_name="issuer b",
                    display_name="Issuer B",
                ),
                Security(
                    id=security_a_id,
                    security_type="equity",
                    display_ticker="SAME",
                    name="Synthetic A",
                    issuer_id=issuer_a_id,
                    currency="USD",
                ),
                Security(
                    id=security_b_id,
                    security_type="equity",
                    display_ticker="SAME",
                    name="Synthetic B",
                    issuer_id=issuer_b_id,
                    currency="USD",
                ),
                IssuerAlias(
                    id=uuid4(),
                    issuer_id=issuer_a_id,
                    alias="Shared Name",
                    normalized_alias="shared name",
                    alias_namespace="name",
                    source="fixture",
                    review_status="unreviewed",
                ),
                IssuerAlias(
                    id=uuid4(),
                    issuer_id=issuer_b_id,
                    alias="Shared Name",
                    normalized_alias="shared name",
                    alias_namespace="name",
                    source="fixture",
                    review_status="needs_review",
                ),
                IssuerAlias(
                    id=uuid4(),
                    issuer_id=issuer_a_id,
                    alias="Shared Name",
                    normalized_alias="shared name",
                    alias_namespace="ticker",
                    source="fixture",
                    review_status="reviewed",
                ),
                SecurityIdentifier(
                    id=uuid4(),
                    security_id=security_a_id,
                    namespace="ticker",
                    exchange="NYSE",
                    value="SAME",
                    normalized_value="same",
                    valid_from=date(2020, 1, 1),
                    source="fixture",
                    review_status="reviewed",
                ),
                SecurityIdentifier(
                    id=uuid4(),
                    security_id=security_b_id,
                    namespace="ticker",
                    exchange="NASDAQ",
                    value="SAME",
                    normalized_value="same",
                    valid_from=date(2020, 1, 1),
                    source="fixture",
                    review_status="unreviewed",
                ),
                SecurityIdentifier(
                    id=uuid4(),
                    security_id=security_a_id,
                    namespace="cusip",
                    exchange="",
                    value="123456789",
                    normalized_value="123456789",
                    valid_from=date(2020, 1, 1),
                    source="fixture",
                    review_status="reviewed",
                ),
            ]
        )

    with Session(engine) as session:
        shared_name_aliases = list(
            session.scalars(
                select(IssuerAlias).where(
                    IssuerAlias.normalized_alias == "shared name",
                    IssuerAlias.alias_namespace == "name",
                )
            )
        )
        assert len(shared_name_aliases) == 2
        assert {alias.review_status for alias in shared_name_aliases} == {
            "unreviewed",
            "needs_review",
        }
        assert len(list(session.scalars(select(SecurityIdentifier)))) == 3

        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.add(
                    SecurityIdentifier(
                        id=uuid4(),
                        security_id=security_b_id,
                        namespace="ticker",
                        exchange="NYSE",
                        value="SAME",
                        normalized_value="same",
                        valid_from=date(2020, 1, 1),
                        source="fixture",
                        review_status="unreviewed",
                    )
                )
                session.flush()

    engine.dispose()
