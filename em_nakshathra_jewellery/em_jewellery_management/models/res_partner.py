from odoo import models, fields, api
from odoo.exceptions import ValidationError
import re


class ResPartner(models.Model):
    _inherit = 'res.partner'


    is_job_worker = fields.Boolean(string='Job Worker')
    default_making_charge = fields.Float(string='Making Charge / Gram')
    show_making_charge = fields.Boolean(compute='_compute_show_making_charge')
    scheme_amount = fields.Monetary(
        string='Scheme Balance',
        currency_field='currency_id',
        default=0.0
    )

    city = fields.Selection([
        ("Kochi", "Kochi"),
        ("Edappally", "Edappally"),
        ("Kaloor", "Kaloor"),
        ("Vyttila", "Vyttila"),
        ("Aluva", "Aluva"),
        ("Other", "Other"),
    ], string="City")




    # @api.depends('is_job_worker')
    # def _compute_show_making_charge(self):
    #     for rec in self:
    #         rec.show_making_charge = rec.is_job_worker

    @api.depends('is_job_worker')
    def _compute_show_making_charge(self):
        for rec in self:
            rec.show_making_charge = rec.is_job_worker


    @api.onchange("name")
    def _onchange_name_capitalize_first(self):
        if self.name:
            self.name = self.name.strip()
            self.name = self.name[0].upper() + self.name[1:]

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)

        # Auto-fill Salesperson with logged-in user
        if 'user_id' in fields_list and not res.get('user_id'):
            res['user_id'] = self.env.user.id
            
        if 'country_id' in fields_list and not res.get('country_id'):
            if self.env.company.country_id:
                res['country_id'] = self.env.company.country_id.id
                
        if 'state_id' in fields_list and not res.get('state_id'):
            if self.env.company.state_id:
                res['state_id'] = self.env.company.state_id.id

        return res

    @api.model
    def _format_phone(self, phone, country_id=None):
        if not phone:
            return phone
        
        # Remove all spaces and non-digit characters except +
        clean_phone = re.sub(r'[^\d+]', '', phone)
        
        if clean_phone.startswith('+'):
            return clean_phone
            
        country = self.env['res.country'].browse(country_id) if country_id else self.env.company.country_id
        
        if country and country.phone_code:
            phone_code = str(country.phone_code)
            
            # If it starts with the country code and has more than 10 digits, assume it includes the code
            if clean_phone.startswith(phone_code) and len(clean_phone) > 10:
                return '+' + clean_phone
                
            # Otherwise assume it's a local number and prepend the country code
            return '+' + phone_code + clean_phone
                
        return clean_phone

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            country_id = vals.get('country_id')
            if vals.get('phone'):
                vals['phone'] = self._format_phone(vals['phone'], country_id)
                self._check_duplicate_phone(vals['phone'])
            if vals.get('mobile'):
                vals['mobile'] = self._format_phone(vals['mobile'], country_id)
                self._check_duplicate_phone(vals['mobile'])
        return super().create(vals_list)

    def write(self, vals):
        if 'phone' in vals or 'mobile' in vals:
            for rec in self:
                c_id = vals.get('country_id', rec.country_id.id)
                if 'phone' in vals and vals.get('phone'):
                    vals['phone'] = rec._format_phone(vals['phone'], c_id)
                if 'mobile' in vals and vals.get('mobile'):
                    vals['mobile'] = rec._format_phone(vals['mobile'], c_id)
                break
                
        res = super().write(vals)
        
        if 'phone' in vals or 'mobile' in vals:
            for rec in self:
                if rec.phone:
                    rec._check_duplicate_phone(rec.phone, ignore_id=rec.id)
                if rec.mobile:
                    rec._check_duplicate_phone(rec.mobile, ignore_id=rec.id)
                    
        return res

    @api.model
    def _check_duplicate_phone(self, phone, ignore_id=False):
        if not phone:
            return
        
        domain = ['|', ('phone', '=', phone), ('mobile', '=', phone)]
        if ignore_id:
            domain.insert(0, ('id', '!=', ignore_id))
            
        existing = self.env['res.partner'].search(domain, limit=1)
        if existing:
            raise ValidationError(f"A contact with phone number {phone} already exists (Contact: {existing.name})!")
