"""Every source adapter, one module each.

Importing this package imports all adapter modules, which runs their `@register`
decorators and populates `app.ingestion.registry`. Add a new adapter module here
when you add a new API shape.
"""

from app.ingestion.adapters import (  # noqa: F401
    adzuna,
    arbeitnow,
    ashby,
    greenhouse,
    jooble,
    lever,
    remoteok,
    remotive,
    usajobs,
)
