"""Account operations for the local personal portfolio."""

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.contracts import AccountCreate, AccountPatch
from app.db.models import Account, utc_now


class AccountNotFound(Exception):
    """The requested account does not exist."""


def create_account(session: Session, data: AccountCreate) -> Account:
    account = Account(
        id=uuid4(),
        name=data.name.strip(),
        account_type=data.account_type,
        base_currency=data.base_currency,
        active=True,
        source_type="manual",
    )
    session.add(account)
    session.flush()
    return account


def list_accounts(session: Session) -> list[Account]:
    statement = select(Account).order_by(Account.created_at, Account.id)
    return list(session.scalars(statement))


def edit_account(session: Session, account_id: UUID, data: AccountPatch) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise AccountNotFound
    values = data.model_dump(exclude_unset=True)
    if "name" in values and values["name"] is not None:
        values["name"] = values["name"].strip()
    for key, value in values.items():
        setattr(account, key, value)
    account.updated_at = utc_now()
    session.flush()
    return account


def require_account(session: Session, account_id: UUID) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise AccountNotFound
    return account
