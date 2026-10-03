"""Public transaction pages must not hide rows beyond the first bounded page."""

from typing import Any

from test_stage2_transactions import _account, _manual
from test_stage2_transactions import stage2_database as stage2_database


def test_transaction_pages_have_stable_order_without_duplicates(
    stage2_database: Any,
) -> None:
    browser, _engine = stage2_database
    account_id = _account(browser)["id"]
    expected_ids = {
        _manual(browser, account_id, amount="-1.25", key=f"page-{index}")["id"]
        for index in range(5)
    }
    pages = [
        browser.get(
            "/v1/transactions",
            params={"account_id": account_id, "limit": 2, "offset": offset},
        )
        for offset in (0, 2, 4, 6)
    ]
    assert all(response.status_code == 200 for response in pages)
    rows = [row for response in pages for row in response.json()]
    assert [len(response.json()) for response in pages] == [2, 2, 1, 0]
    assert len(rows) == len(expected_ids)
    assert {row["id"] for row in rows} == expected_ids
    assert [row["id"] for row in rows] == sorted(expected_ids)
    assert browser.get("/v1/transactions", params={"offset": -1}).status_code == 422
