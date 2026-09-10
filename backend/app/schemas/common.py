"""Shared response shapes."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Standard paginated list envelope.

    `total` is the unfiltered-by-pagination count so the frontend can render
    "1–20 of 3,481" and page controls. `pages` is derived for convenience.
    """

    items: list[T]
    total: int
    page: int
    page_size: int

    @property
    def pages(self) -> int:
        if self.page_size <= 0:
            return 0
        return (self.total + self.page_size - 1) // self.page_size

    @classmethod
    def build(cls, items: list[T], total: int, page: int, page_size: int) -> Page[T]:
        return cls(items=items, total=total, page=page, page_size=page_size)


class Message(BaseModel):
    """Trivial `{"detail": "..."}` responses."""

    detail: str
