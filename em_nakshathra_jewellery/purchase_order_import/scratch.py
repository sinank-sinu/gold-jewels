import sys
import odoo

odoo.tools.config.parse_config(['-c', '/etc/odoo/odoo.conf', '-d', 'odoo', '--no-http'])
registry = odoo.registry('odoo')
with registry.cursor() as cr:
    env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
    journals = env['account.journal'].search([('name', 'ilike', 'opening')])
    print("Journals:", [(j.id, j.name, j.type) for j in journals])
    
    locations = env['stock.location'].search([('name', 'ilike', 'stock')])
    print("Locations:", [(loc.id, loc.complete_name) for loc in locations[:5]])
