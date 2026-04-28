from odoo import models

class PosSession(models.Model):
    _inherit = 'pos.session'

    def _loader_params_product_product(self):
        result = super()._loader_params_product_product()
        branch_id = self.config_id.pos_branch_id.id 

        if branch_id:
            result['search_params']['domain'].append('|')
            result['search_params']['domain'].append(['branch_id', '=', branch_id])
            result['search_params']['domain'].append(['branch_id', '=', False])
        return result