"""Role-based access control for the admin panel (brief: "Role-based access
for multiple admins").

Four `AdminRole`s, each mapped to the set of admin actions it may perform.
Action names are coarse-grained strings checked at the route level
(`require_permission("sources.manage")`); `superadmin` implicitly has every
permission without being listed explicitly, so the permission set never needs
updating when a new permission is added — only non-superadmin roles need
curating.
"""

from __future__ import annotations

from app.models.enums import AdminRole

# The full permission vocabulary, grouped by admin screen. Kept as plain
# strings (not an enum) so a new permission is a one-line addition here plus
# wherever it's checked — no migration, no shared enum to import everywhere.
PERMISSIONS = {
    "taxonomy.manage",  # add/edit/remove fields & sub-fields, remap jobs
    "sources.manage",  # add/edit/disable sources, keys, rate limits
    "employers.moderate",  # approve/reject employer accounts + postings
    "jobs.manage",  # hide/unpublish/edit any listing
    "users.manage",  # view/disable/reset seeker + employer accounts
    "content.manage",  # homepage content, banners/announcements
    "admins.manage",  # create/edit other admin accounts (superadmin only)
    "analytics.view",
}

ROLE_PERMISSIONS: dict[AdminRole, set[str]] = {
    AdminRole.SUPERADMIN: set(PERMISSIONS),  # everything
    AdminRole.MODERATOR: {
        "employers.moderate",
        "jobs.manage",
        "users.manage",
        "analytics.view",
    },
    AdminRole.EDITOR: {
        "taxonomy.manage",
        "sources.manage",
        "content.manage",
        "analytics.view",
    },
    AdminRole.ANALYST: {
        "analytics.view",
    },
}


def has_permission(admin_role: AdminRole, permission: str) -> bool:
    if permission not in PERMISSIONS:
        raise ValueError(f"unknown permission {permission!r}")
    return permission in ROLE_PERMISSIONS.get(admin_role, set())
