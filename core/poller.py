from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from core.auth_errors import is_auth_error
from core.models import AppConfig, AppSnapshot, AccountSnapshot
from providers.registry import get_provider


def merge_last_good(previous: AppSnapshot, new: AppSnapshot) -> AppSnapshot:
    """Merge polls with auth-aware last-good retention.

    - Auth/login errors or logged_in=False: do **not** keep stale meters.
    - Transient errors while still logged in: keep prior metrics/plan.
    - Empty successful parses while logged in: keep prior metrics.
    """
    prev_by_id = {a.account_id: a for a in previous.accounts}
    merged: list[AccountSnapshot] = []
    for acct in new.accounts:
        prev = prev_by_id.get(acct.account_id)

        if acct.error is not None:
            clear = (
                is_auth_error(acct.error)
                or not acct.logged_in
                or prev is None
                or not prev.metrics
            )
            if clear:
                merged.append(acct)
            else:
                merged.append(
                    AccountSnapshot(
                        account_id=acct.account_id,
                        provider_id=acct.provider_id,
                        display_name=acct.display_name,
                        logged_in=True,
                        plan=prev.plan if prev.plan is not None else acct.plan,
                        metrics=list(prev.metrics),
                        error=acct.error,
                    )
                )
            continue

        # Soft empty success: keep last meters rather than blanking the icon.
        # Also clears a prior transient error when the latest poll "succeeded"
        # with no parseable meters. Do not retain meters when logged out.
        if (
            not acct.metrics
            and acct.logged_in
            and prev is not None
            and prev.metrics
        ):
            merged.append(
                AccountSnapshot(
                    account_id=acct.account_id,
                    provider_id=acct.provider_id,
                    display_name=acct.display_name or prev.display_name,
                    logged_in=acct.logged_in,
                    plan=acct.plan if acct.plan is not None else prev.plan,
                    metrics=list(prev.metrics),
                    error=None,
                )
            )
            continue

        merged.append(acct)
    return AppSnapshot(fetched_at=new.fetched_at, accounts=merged)


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


def next_poll_seconds(config: AppConfig) -> int:
    """Global poll interval, optionally tightened by per-account overrides."""
    seconds = [config.poll_seconds]
    for account in config.accounts:
        if account.enabled and account.poll_seconds:
            seconds.append(account.poll_seconds)
    return max(1, min(seconds))


def filter_enabled(snapshot: AppSnapshot, config: AppConfig) -> AppSnapshot:
    """Drop cached/disabled accounts so the tray only shows enabled ones."""
    enabled = {account.id for account in config.accounts if account.enabled}
    return AppSnapshot(
        fetched_at=snapshot.fetched_at,
        accounts=[
            account
            for account in snapshot.accounts
            if account.account_id in enabled
        ],
    )
