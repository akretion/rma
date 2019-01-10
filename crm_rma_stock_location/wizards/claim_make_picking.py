# -*- coding: utf-8 -*-
##############################################################################
#
#    Copyright 2015 Vauxoo
#    Copyright (C) 2009-2012  Akretion
#    Author: Emmanuel Samyn, Benoît GUILLOT <benoit.guillot@akretion.com>,
#            Osval Reyes
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from openerp import models, fields, api


class ClaimMakePicking(models.TransientModel):

    _inherit = 'claim_make_picking.wizard'
    _description = 'Wizard to create pickings from claim lines'

    def _default_claim_line_dest_location_id(self):
        """Return the location_id to use as destination.

        If it's an outgoing shipment: take the customer stock property
        If it's an incoming shipment take the location_dest_id common to all
        lines, or if different, return None.
        """
        picking_type = self.env.context.get('picking_type')
        claim_id = self.env.context.get('active_id')
        claim_record = self.env['crm.claim'].browse(claim_id)

        if isinstance(picking_type, int):
            picking_obj = self.env['stock.picking.type']
            return picking_obj.browse(picking_type)\
                .default_location_dest_id

        if picking_type == 'out':
            return claim_record.warehouse_id.rma_out_type_id.\
                default_location_dest_id
        elif picking_type == 'in':
            return claim_record.warehouse_id.rma_in_type_id.\
                default_location_dest_id
        elif picking_type == 'int':
            return claim_record.warehouse_id.rma_int_type_id.\
                default_location_dest_id
        elif picking_type == 'loss':
            return claim_record.warehouse_id.loss_loc_id

        return self.env['stock.location']

    claim_line_dest_location_id = fields.Many2one(
        default=_default_claim_line_dest_location_id)

    @api.model
    def _get_picking_type_and_field(self):
        picking_type, write_field = super(
            ClaimMakePicking, self)._get_picking_type_and_field()
        if self.env.context.get('picking_type', '') == 'loss':
            write_field = 'move_loss_id'
        return picking_type, write_field

    @api.returns('claim.line')
    def _default_claim_line_ids(self):
        if self.env.context.get('picking_type') == 'loss':
            move_field = 'move_loss_id'
            domain = [('claim_id', '=', self.env.context['active_id'])]
            lines = self.env['claim.line'].\
                search(domain)
            if lines:
                domain = domain + ['|', (move_field, '=', False),
                                   (move_field + '.state', '=', 'cancel')]
                lines = lines.search(domain)
                if not lines:
                    raise exceptions.Warning(
                        _('Error'),
                        _('A picking has already been created for this claim.'))
        else:
            lines = super(ClaimMakePicking, self)._default_claim_line_ids()
        return lines

    claim_line_ids = fields.Many2many(default=_default_claim_line_ids)
