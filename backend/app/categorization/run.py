"""Re-run the keyword classifier over already-stored jobs.

    python -m app.categorization.run                 # only currently-uncategorized
    python -m app.categorization.run --all           # every keyword/none job
    python -m app.categorization.run --dry-run

Use after editing sub-field keywords (in the seed file or the admin panel) so
existing jobs pick up the change without a re-fetch. Never touches jobs an admin
or employer categorized by hand.
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from app.categorization.classifier import Classifier
from app.db.session import session_scope
from app.logging import configure_logging, get_logger
from app.models import Job
from app.models.enums import CategorizationMethod

log = get_logger(__name__)

_RECLASSIFIABLE = {CategorizationMethod.NONE, CategorizationMethod.KEYWORD}


def recategorize(*, only_uncategorized: bool, dry_run: bool) -> dict[str, int]:
    counts = {"scanned": 0, "changed": 0, "now_categorized": 0, "now_uncategorized": 0}
    with session_scope() as db:
        classifier = Classifier.from_db(db)

        stmt = select(Job).where(Job.categorization_method.in_(_RECLASSIFIABLE))
        if only_uncategorized:
            stmt = stmt.where(Job.is_uncategorized.is_(True))

        for job in db.scalars(stmt).yield_per(500):
            counts["scanned"] += 1
            result = classifier.classify(job.title, job.description_text)
            changed = job.field_id != result.field_id or job.subfield_id != result.subfield_id
            if not changed:
                continue
            counts["changed"] += 1
            if result.is_categorized and job.is_uncategorized:
                counts["now_categorized"] += 1
            if not result.is_categorized and not job.is_uncategorized:
                counts["now_uncategorized"] += 1

            if not dry_run:
                job.field_id = result.field_id
                job.subfield_id = result.subfield_id
                job.categorization_method = result.method
                job.categorization_confidence = result.confidence
                job.is_uncategorized = not result.is_categorized

        if dry_run:
            db.rollback()
    return counts


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Re-run the job classifier.")
    parser.add_argument("--all", action="store_true", help="reprocess every keyword/none job")
    parser.add_argument("--dry-run", action="store_true", help="report only, no writes")
    args = parser.parse_args()

    counts = recategorize(only_uncategorized=not args.all, dry_run=args.dry_run)
    log.info("categorization.recategorize", **counts)
    print(counts)


if __name__ == "__main__":
    main()
