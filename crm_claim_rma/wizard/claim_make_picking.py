# -*- coding: utf-8 -*-
##############################################################################
#
#    Copyright 2013 Camptocamp
#    Copyright 2009-2013 Akretion,
#    Author: Emmanuel Samyn, Raphaël Valyi, Sébastien Beau,
#            Benoît Guillot, Joel Grand-Guillaume
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
from openerp.osv import fields, orm
from openerp.tools import DEFAULT_SERVER_DATETIME_FORMAT
from openerp import netsvc
from openerp.tools.translate import _
import time
from collections import defaultdict


class claim_make_picking_line(orm.TransientModel):
    _name = "claim.make.picking.line"

    _columns = {
        'claim_line_id': fields.many2one('claim.line', 'Claim line'),
        'product_id': fields.many2one('product.product', 'Product'),
        'new_product_id': fields.many2one('product.product', 'New product'),
        'product_qty': fields.float('Quantity'),
        'wizard_id': fields.many2one('claim_make_picking.wizard', 'Wizard'),
        }


class claim_make_picking(orm.TransientModel):

    _name = 'claim_make_picking.wizard'
    _description = 'Wizard to create pickings from claim lines'
    _columns = {
        'claim_line_source_location': fields.many2one(
            'stock.location',
            string='Source Location',
            help="Location where the returned products are from.",
            required=True),
        'claim_line_dest_location': fields.many2one(
            'stock.location',
            string='Dest. Location',
            help="Location where the system will stock the returned products.",
            required=True),
        'claim_line_ids': fields.many2many(
            'claim.line',
            'claim_line_picking',
            'claim_picking_id',
            'claim_line_id',
            string='Claim lines'),
        'wizard_line_ids': fields.one2many(
            'claim.make.picking.line',
            'wizard_id',
            'Wizard lines',
            ),
        'claim_id': fields.many2one('crm.claim', 'Claim'),
    }

    def _get_claim_good_lines(self, cr, uid, context=None):
        line_obj = self.pool['claim.line']
        if context is None:
            context = {}
        lines = defaultdict(list)
        if context.get('picking_type') == 'out':
            move_field = 'move_out_id'
        else:
            move_field = 'move_in_id'
        line_ids = line_obj.search(
            cr, uid,
            [('claim_id', '=', context['active_id'])],
            context=context)
        for line in line_obj.browse(cr, uid, line_ids, context=context):
            if not line[move_field] or line[move_field].state == 'cancel':
                lines['good_lines'].append(line.id)
                lines['wizard_lines'].append({
                    'product_id': line.product_id.id,
                    'claim_line_id': line.id,
                    'product_qty': line.product_returned_quantity,
                })
        return lines

    def _get_claim_lines(self, cr, uid, context):
        # TODO use custom states to show buttons of this wizard or not instead
        # of raise an error
        good_lines = self._get_claim_good_lines(cr, uid,
                                                context=context)['good_lines']
        if not good_lines:
            raise orm.except_orm(
                _('Error'),
                _('A picking has already been created for this claim.'))
        return good_lines

    # Get default source location
    def _get_source_loc(self, cr, uid, context):
        loc_id = False
        if context is None:
            context = {}
        warehouse_obj = self.pool.get('stock.warehouse')
        warehouse_id = context.get('warehouse_id')
        if context.get('picking_type') == 'out':
            loc_id = warehouse_obj.read(
                cr, uid, warehouse_id,
                ['lot_stock_id'],
                context=context)['lot_stock_id'][0]
        elif context.get('partner_id'):
            loc_id = self.pool.get('res.partner').read(
                cr, uid, context['partner_id'],
                ['property_stock_customer'],
                context=context)['property_stock_customer'][0]
        return loc_id

    def _get_common_dest_location_from_line(self, cr, uid, line_ids, context):
        """Return the ID of the common location between all lines. If no common
        destination was  found, return False"""
        loc_id = False
        line_obj = self.pool.get('claim.line')
        line_location = []
        for line in line_obj.browse(cr, uid, line_ids, context=context):
            if line.location_dest_id.id not in line_location:
                line_location.append(line.location_dest_id.id)
        if len(line_location) == 1:
            loc_id = line_location[0]
        return loc_id

    def _get_common_partner_from_line(self, cr, uid, line_ids, context):
        """Return the ID of the common partner between all lines. If no common
        partner was found, return False"""
        partner_id = False
        line_obj = self.pool.get('claim.line')
        line_partner = []
        for line in line_obj.browse(cr, uid, line_ids, context=context):
            if (line.warranty_return_partner
                    and line.warranty_return_partner.id
                    not in line_partner):
                line_partner.append(line.warranty_return_partner.id)
        if len(line_partner) == 1:
            partner_id = line_partner[0]
        return partner_id

    # Get default destination location
    def _get_dest_loc(self, cr, uid, context):
        """Return the location_id to use as destination.
        If it's an outoing shippment: take the customer stock property
        If it's an incoming shippment take the location_dest_id common to all
        lines, or if different, return None."""
        if context is None:
            context = {}
        loc_id = False
        if context.get('picking_type') == 'out' and context.get('partner_id'):
            loc_id = self.pool.get('res.partner').read(
                cr, uid, context.get('partner_id'),
                ['property_stock_customer'],
                context=context)['property_stock_customer'][0]
        elif context.get('picking_type') == 'in' and context.get('partner_id'):
            # Add the case of return to supplier !
            line_ids = self._get_claim_lines(cr, uid, context=context)
            loc_id = self._get_common_dest_location_from_line(cr, uid,
                                                              line_ids,
                                                              context=context)
        return loc_id

    def _get_wizard_lines(self, cr, uid, context=None):
        return self._get_claim_good_lines(
            cr, uid, context=context)['wizard_lines']

    def _get_claim(self, cr, uid, context=None):
        if context is None:
            context = {}
        return context.get('active_id', False)

    _defaults = {
        'claim_line_source_location': _get_source_loc,
        'claim_line_dest_location': _get_dest_loc,
        'claim_line_ids': _get_claim_lines,
        'wizard_line_ids': _get_wizard_lines,
        'claim_id': _get_claim,
    }

    def action_cancel(self, cr, uid, ids, context=None):
        return {'type': 'ir.actions.act_window_close'}

    def _prepare_picking_vals(
            self, cr, uid, p_type, partner_id, wizard, context=None):
        return {
            'origin': wizard.claim_id.number,
            'type': p_type,
            'move_type': 'one',  # direct
            'state': 'draft',
            'date': time.strftime(DEFAULT_SERVER_DATETIME_FORMAT),
            'partner_id': partner_id,
            'invoice_state': "none",
            'company_id': wizard.claim_id.company_id.id,
            'location_id': wizard.claim_line_source_location.id,
            'location_dest_id': wizard.claim_line_dest_location.id,
            'note': 'RMA picking %s' % p_type,
            'claim_id': wizard.claim_id.id,
            }

    def _prepare_move_vals(
            self, cr, uid, wizard_line, partner_id, picking_id, product,
            context=None):
        claim_line = wizard_line.claim_line_id
        return {
            'name': product.partner_ref,
            'priority': '0',
            'date': time.strftime(DEFAULT_SERVER_DATETIME_FORMAT),
            'date_expected': time.strftime(DEFAULT_SERVER_DATETIME_FORMAT),
            'product_id': product.id,
            'product_qty': wizard_line.product_qty,
            'product_uom': product.uom_id.id,
            'partner_id': partner_id,
            'prodlot_id': wizard_line.claim_line_id.prodlot_id.id,
            'picking_id': picking_id,
            'state': 'draft',
            'price_unit': wizard_line.claim_line_id.unit_sale_price,
            'company_id': wizard_line.wizard_id.claim_id.company_id.id,
            'location_id': wizard_line.wizard_id.claim_line_source_location.id,
            'location_dest_id': wizard_line.wizard_id.claim_line_dest_location.id,
            'note': 'RMA move',
            }

    def _create_move(
            self, cr, uid, wizard_line, partner_id, picking_id, product,
            context=None):
        move_obj = self.pool['stock.move']
        move_vals = self._prepare_move_vals(
            cr, uid, wizard_line, partner_id, picking_id, product,
            context=context)
        move_id = move_obj.create(cr, uid, move_vals, context=context)
        return move_id

    def _prepare_procurement_vals(
            self, cr, uid, move_id, wizard_line, product, context=None):
        claim_line = wizard_line.claim_line_id
        return {
            'name': product.partner_ref,
            'origin': wizard_line.wizard_id.claim_id.number,
            'date_planned': time.strftime(DEFAULT_SERVER_DATETIME_FORMAT),
            'product_id': product.id,
            'product_qty': wizard_line.product_qty,
            'product_uom': product.uom_id.id,
            'location_id': wizard_line.wizard_id.claim_line_source_location.id,
            'procure_method': product.procure_method,
            'move_id': move_id,
            'company_id': wizard_line.wizard_id.claim_id.company_id.id,
            'note': 'RMA procurement',
            }

    def _create_procurement(
            self, cr, uid, move_id, wizard_line, product, context=None):
        proc_obj = self.pool['procurement.order']
        proc_vals = self._prepare_procurement_vals(
            cr, uid, move_id, wizard_line, product, context=context)
        proc_id = proc_obj.create(cr, uid, proc_vals, context=context)
        return proc_id

    # If "Create" button pressed
    def action_create_picking(self, cr, uid, ids, context=None):
        picking_obj = self.pool['stock.picking']
        line_obj = self.pool['claim.line']
        claim_obj = self.pool['crm.claim']
        if context is None:
            context = {}
        view_obj = self.pool['ir.ui.view']
        name = 'RMA picking out'
        if context.get('picking_type') == 'out':
            p_type = 'out'
            write_field = 'move_out_id'
        else:
            p_type = 'in'
            write_field = 'move_in_id'
            if context.get('picking_type'):
                name = 'RMA picking ' + str(context.get('picking_type'))
        model = 'stock.picking.' + p_type
        view_id = view_obj.search(cr, uid,
                                  [('model', '=', model),
                                   ('type', '=', 'form')],
                                  context=context)[0]
        wizard = self.browse(cr, uid, ids[0], context=context)
        partner_id = wizard.claim_id.delivery_address_id.id
        line_ids = [x.id for x in wizard.claim_line_ids]
        # In case of product return, we don't allow one picking for various
        # product if location are different
        # or if partner address is different
        if context.get('product_return'):
            common_dest_loc_id = self._get_common_dest_location_from_line(
                cr, uid, line_ids, context=context)
            if not common_dest_loc_id:
                raise orm.except_orm(
                    _('Error !'),
                    _('A product return cannot be created for various '
                      'destination locations, please choose line with a '
                      'same destination location.'))
            line_obj.auto_set_warranty(cr, uid, line_ids, context=context)
            common_dest_partner_id = self._get_common_partner_from_line(
                cr, uid, line_ids, context=context)
            if not common_dest_partner_id:
                raise orm.except_orm(
                    _('Error !'),
                    _('A product return cannot be created for various '
                      'destination addresses, please choose line with a '
                      'same address.'))
            partner_id = common_dest_partner_id
        # create picking
        picking_vals = self._prepare_picking_vals(
            cr, uid, p_type, partner_id, wizard, context=context)
        picking_id = picking_obj.create(cr, uid, picking_vals, context=context)
        # Create picking lines
        proc_ids = []
        for wizard_line in wizard.wizard_line_ids:
            if wizard_line.new_product_id:
                product = wizard_line.new_product_id
            else:
                product = wizard_line.product_id,
            if product.type not in ['consu', 'product']:
                continue
            move_id = self._create_move(
                cr, uid, wizard_line, partner_id, picking_id, product,
                context=context)
            line_obj.write(
                cr, uid, wizard_line.claim_line_id.id, {write_field: move_id},
                context=context)
            if p_type == 'out':
                proc_id = self._create_procurement(
                    cr, uid, move_id, wizard_line, product, context=context)
                proc_ids.append(proc_id)
        wf_service = netsvc.LocalService("workflow")
        if picking_id:
            wf_service.trg_validate(uid, 'stock.picking',
                                    picking_id, 'button_confirm', cr)
            picking_obj.action_assign(cr, uid, [picking_id])
        if proc_ids:
            for proc_id in proc_ids:
                wf_service.trg_validate(uid, 'procurement.order',
                                        proc_id, 'button_confirm', cr)
        domain = ("[('type', '=', '%s'), ('partner_id', '=', %s)]" %
                  (p_type, partner_id))
        return {
            'name': '%s' % name,
            'view_type': 'form',
            'view_mode': 'form',
            'view_id': view_id,
            'domain': domain,
            'res_model': model,
            'res_id': picking_id,
            'type': 'ir.actions.act_window',
        }

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
