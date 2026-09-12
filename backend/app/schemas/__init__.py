"""Pydantic request/response models (the HTTP contract).

Kept separate from ORM models: the wire format is a deliberate, versioned API
surface, not a leak of the database schema.
"""
