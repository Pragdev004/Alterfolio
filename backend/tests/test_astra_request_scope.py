from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

from app.api.dependencies.astra import get_astra_tool_executor
from app.services.authenticated_principal import AuthenticatedPrincipal


def _extract_bound_user_id(executor) -> str:
    return str(executor._tools.portfolio._user_id)  # noqa: SLF001 - test introspection


def test_request_scoped_tool_executor_instances_are_unique() -> None:
    principal = AuthenticatedPrincipal(user_id=uuid4())
    fake_db = SimpleNamespace()
    settings = SimpleNamespace(astra_execution_timeout_seconds=45, astra_symbol_max_chars=20)

    first = get_astra_tool_executor(db=fake_db, principal=principal, settings=settings)
    second = get_astra_tool_executor(db=fake_db, principal=principal, settings=settings)

    assert first is not second
    assert first._tools is not second._tools  # noqa: SLF001


def test_concurrent_request_isolation_by_principal() -> None:
    user_a = AuthenticatedPrincipal(user_id=uuid4())
    user_b = AuthenticatedPrincipal(user_id=uuid4())
    fake_db = SimpleNamespace()
    settings = SimpleNamespace(astra_execution_timeout_seconds=45, astra_symbol_max_chars=20)

    with ThreadPoolExecutor(max_workers=2) as pool:
        future_a = pool.submit(get_astra_tool_executor, db=fake_db, principal=user_a, settings=settings)
        future_b = pool.submit(get_astra_tool_executor, db=fake_db, principal=user_b, settings=settings)

    executor_a = future_a.result()
    executor_b = future_b.result()

    assert _extract_bound_user_id(executor_a) == str(user_a.user_id)
    assert _extract_bound_user_id(executor_b) == str(user_b.user_id)
    assert _extract_bound_user_id(executor_a) != _extract_bound_user_id(executor_b)
