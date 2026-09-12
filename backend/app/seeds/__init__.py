"""Seed data: the taxonomy and the source registry.

    taxonomy_seed.py  fields + sub-fields + classifier keywords
    sources_seed.py   the `sources` rows for every v1 adapter
    run.py            `python -m app.seeds.run` — idempotent upsert of both
    create_admin.py   `python -m app.seeds.create_admin` — provision an admin

Seeds are idempotent (upsert by natural key) so they can be re-run after edits
without duplicating rows.
"""
