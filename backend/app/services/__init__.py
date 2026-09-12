"""Cross-cutting business logic that doesn't belong to a single route.

search      JobQuery value-object → SQLAlchemy Select (the search seam)
auth        password hashing, JWT encode/decode, refresh-token rotation
authz       admin_role → permitted actions
moderation  employer account + posting approval workflow
analytics   event recording + dashboard rollups
email       SMTP send (or log, when SMTP is not configured)
"""
