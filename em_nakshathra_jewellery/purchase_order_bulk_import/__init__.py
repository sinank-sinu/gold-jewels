from . import models
from . import wizard
from . import controllers


def _cleanup_stale_views(env):
    """Remove stale view records that reference non-existent fields."""
    try:
        stale_views = env['ir.ui.view'].search([
            ('name', '=', 'purchase.order.form.destination_location')
        ])
        if stale_views:
            stale_views.unlink()
    except Exception:
        pass