"""Shared FastAPI dependencies.

Auth dependencies (current user / role guards) are added in milestone 8; for now
this holds pagination and the anonymous session id.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, Query

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20


@dataclass(slots=True)
class Pagination:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def pagination(
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
) -> Pagination:
    return Pagination(page=page, page_size=page_size)


def session_id(x_session_id: str | None = Header(default=None)) -> str | None:
    """The client-generated UUID (stored in localStorage) that ties an anonymous
    visitor's analytics events together. Never required."""
    if not x_session_id:
        return None
    return x_session_id[:64]
