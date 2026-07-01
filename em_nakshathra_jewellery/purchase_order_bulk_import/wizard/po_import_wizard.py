from odoo import models, fields


class PoImportWizard(models.TransientModel):
    """Thin transient model — the real wizard lives in the OWL client action.
    This model exists only to provide the menu action target."""
    _name = 'po.import.wizard'
    _description = 'Purchase Order Import Wizard'

    def action_open_wizard(self):
        return {
            'type': 'ir.actions.client',
            'tag': 'po_bulk_import_wizard',
            'name': 'Purchase Order Bulk Import',
            'target': 'fullscreen',
        }
