"""Keyword field/sub-field classifier.

WHAT: Given a job's title + description, pick the best `Subfield` (and its
parent `Field`) by scoring the job's text against each sub-field's admin-editable
`keywords` list. Returns an abstention when no sub-field scores clearly enough —
those jobs land in the admin "needs categorization" queue.

WHY keyword scoring, not ML (for v1):
    * transparent — an admin can see *which* keyword matched and fix the list,
    * instant and free — runs inline in the ingestion pipeline,
    * deterministic — same input always yields the same category, so re-running
      after a keyword edit has predictable results.

The public surface is `Classifier.classify(...) -> Classification`. A smarter
backend (embeddings, an LLM) can later implement the same call without the rest
of the system noticing.

Scoring — the job TITLE is treated as far more reliable than the description
(descriptions on talent-marketplace and agency listings are full of unrelated
tech/skill keywords):

    * If ANY sub-field's keywords hit the title, only those sub-fields compete.
      Score = TITLE_WEIGHT * title_hits + min(description_hits, DESC_CAP).
    * If nothing hits the title, fall back to description-only scoring with a
      stricter bar.

Either way the winner must clear the path's MIN_SCORE and beat the runner-up by
MIN_MARGIN, else the classifier abstains and the job goes to the admin queue.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Subfield
from app.models.enums import CategorizationMethod

TITLE_WEIGHT = 3
DESC_CAP = 4  # description can contribute at most this much when a title matched
MIN_SCORE_TITLE = 3  # a single title keyword hit clears this
MIN_SCORE_DESC = 5  # description-only needs a strong, repeated signal
MIN_MARGIN_TITLE = 1  # title path: winner just has to be ahead
MIN_MARGIN_DESC = 3  # description-only path: winner must be clearly ahead
DESCRIPTION_SCAN_CHARS = 4000  # only the first N chars of the description count


@dataclass(frozen=True, slots=True)
class Classification:
    field_id: uuid.UUID | None
    subfield_id: uuid.UUID | None
    method: CategorizationMethod
    confidence: float | None

    @property
    def is_categorized(self) -> bool:
        return self.subfield_id is not None


ABSTAIN = Classification(None, None, CategorizationMethod.NONE, None)


@dataclass(frozen=True, slots=True)
class _SubfieldSpec:
    subfield_id: uuid.UUID
    field_id: uuid.UUID
    keywords: tuple[str, ...]


class Classifier:
    """Build once per ingestion run (or per re-categorization pass); reuse for
    every job. Construction compiles one regex per keyword phrase."""

    def __init__(self, specs: list[_SubfieldSpec]) -> None:
        self._specs = specs
        # Pre-compile: keyword phrase → compiled word-boundary regex. A phrase
        # like "registered nurse" matches as a unit; "r language" tolerates the
        # trailing space in the seed data.
        self._patterns: dict[str, re.Pattern[str]] = {}
        for spec in specs:
            for kw in spec.keywords:
                key = kw.strip().lower()
                if key and key not in self._patterns:
                    self._patterns[key] = re.compile(
                        r"(?<!\w)" + re.escape(key) + r"(?!\w)", re.IGNORECASE
                    )

    # -- construction helpers --------------------------------------------------

    @classmethod
    def from_db(cls, db: Session) -> Classifier:
        """Load every active sub-field (with an active parent field)."""
        rows = db.scalars(
            select(Subfield).join(Subfield.field).where(Subfield.is_active.is_(True))
        ).all()
        specs = [
            _SubfieldSpec(
                subfield_id=sf.id,
                field_id=sf.field_id,
                keywords=tuple(k.lower() for k in (sf.keywords or [])),
            )
            for sf in rows
            if sf.field is not None and sf.field.is_active and sf.keywords
        ]
        return cls(specs)

    # -- classification ------------------------------------------------------

    def _title_hits(self, spec: _SubfieldSpec, title_text: str) -> int:
        return sum(
            1
            for kw in spec.keywords
            if (p := self._patterns.get(kw)) is not None and p.search(title_text)
        )

    def _desc_hits(self, spec: _SubfieldSpec, desc_text: str) -> int:
        return sum(
            len(p.findall(desc_text))
            for kw in spec.keywords
            if (p := self._patterns.get(kw)) is not None
        )

    def classify(self, title: str | None, description: str | None) -> Classification:
        title_text = (title or "").lower()
        desc_text = (description or "")[:DESCRIPTION_SCAN_CHARS].lower()
        if not title_text and not desc_text:
            return ABSTAIN

        # --- Path 1: something matched the title → only those sub-fields run ---
        title_matched = [
            (h, spec) for spec in self._specs if (h := self._title_hits(spec, title_text))
        ]
        if title_matched:
            scored = [
                (h * TITLE_WEIGHT + min(self._desc_hits(spec, desc_text), DESC_CAP), spec)
                for h, spec in title_matched
            ]
            return self._pick(scored, MIN_SCORE_TITLE, MIN_MARGIN_TITLE)

        # --- Path 2: description only, stricter thresholds ---
        scored = [(d, spec) for spec in self._specs if (d := self._desc_hits(spec, desc_text))]
        return self._pick(scored, MIN_SCORE_DESC, MIN_MARGIN_DESC)

    @staticmethod
    def _pick(
        scored: list[tuple[int, _SubfieldSpec]], min_score: int, min_margin: int
    ) -> Classification:
        if not scored:
            return ABSTAIN
        scored.sort(key=lambda t: t[0], reverse=True)
        best_score, best = scored[0]
        runner_up = scored[1][0] if len(scored) > 1 else 0
        if best_score < min_score or (best_score - runner_up) < min_margin:
            return ABSTAIN

        total = sum(s for s, _ in scored) or 1
        return Classification(
            field_id=best.field_id,
            subfield_id=best.subfield_id,
            method=CategorizationMethod.KEYWORD,
            confidence=round(best_score / total, 3),
        )
