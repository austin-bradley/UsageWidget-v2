from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from core.models import AppConfig, AppSnapshot, AccountSnapshot
from providers.registry import get_provider


def fetch_all(config: AppConfig) -> AppSnapshot:
    enabled = [a for a in config.accounts if a.enabled]
    accounts: list[AccountSnapshot] = []

    def one(acct):
        try:
            return get_provider(acct.provider).fetch(acct)
        except Exception as e:
            return AccountSnapshot(
                account_id=acct.id,
                provider_id=acct.provider,
                display_name=acct.label or acct.id,
                logged_in=False,
                plan=None,
                metrics=[],
                error=str(e),
            )

    if not enabled:
        return AppSnapshot(fetched_at=datetime.now(), accounts=[])

    with ThreadPoolExecutor(max_workers=min(8, len(enabled))) as pool:
        futs = {pool.submit(one, a): a for a in enabled}
        for fut in as_completed(futs):
            accounts.append(fut.result())

    # stable order matching config
    order = {a.id: i for i, a in enumerate(enabled)}
    accounts.sort(key=lambda s: order.get(s.account_id, 999))
    return AppSnapshot(fetched_at=datetime.now(), accounts=accounts)
