from odoo import models


class LabelImportWizard(models.TransientModel):
    """Thin transient model — the real wizard lives in the OWL client action.
    This model exists only to provide the menu action target."""
    _name = 'label.import.wizard'
    _description = 'Product Label Import Wizard'

    def action_open_wizard(self):
        return {
            'type': 'ir.actions.client',
            'tag': 'product_label_bulk_import_wizard',
            'name': 'Product Label Bulk Import',
            'target': 'fullscreen',
        }