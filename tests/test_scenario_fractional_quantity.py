from decimal import Decimal
import unittest

from proteus import Model

from trytond.modules.company.tests.tools import create_company, get_company
from trytond.modules.stock.exceptions import MoveOriginWarning
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules


class TestFractionalQuantity(unittest.TestCase):

    def setUp(self):
        drop_db()

    def tearDown(self):
        drop_db()

    def test(self):
        config = activate_modules(['stock_plan'])
        ProductUom = Model.get('product.uom')
        ProductTemplate = Model.get('product.template')
        StockLocation = Model.get('stock.location')
        StockMove = Model.get('stock.move')
        StockPlan = Model.get('stock.plan')
        Warning = Model.get('res.user.warning')

        create_company()
        company = get_company()

        unit, = ProductUom.find([('name', '=', 'Unit')])
        unit.digits = 5
        unit.rounding = 0.00001
        unit.save()

        template = ProductTemplate(
            name='Fractional Product',
            default_uom=unit,
            type='goods',
            list_price=Decimal('1'),
            cost_price_method='average')
        product, = template.products
        product.code = 'FRACTIONAL'
        template.save()
        product, = template.products

        supplier_location, = StockLocation.find([('code', '=', 'SUP')])
        storage_location, = StockLocation.find([('code', '=', 'STO')])
        customer_location, = StockLocation.find([('code', '=', 'CUS')])

        source_move = StockMove(
            product=product,
            quantity=0.34,
            from_location=supplier_location,
            to_location=storage_location,
            currency=company.currency,
            unit_price=Decimal('1'))
        source_move.save()
        storage_move = StockMove(
            product=product,
            quantity=0.01,
            from_location=supplier_location,
            to_location=storage_location,
            currency=company.currency,
            unit_price=Decimal('1'))
        storage_move.save()
        try:
            storage_move.click('do')
        except MoveOriginWarning as warning:
            _, (key, *_) = warning.args
            Warning(user=config.user, name=key).save()
            storage_move.click('do')
        customer_move = StockMove(
            product=product,
            quantity=0.35,
            from_location=storage_location,
            to_location=customer_location,
            currency=company.currency,
            unit_price=Decimal('1'))
        customer_move.save()

        plan = StockPlan()
        plan.click('calculate')
        plan.reload()

        self.assertEqual(len(plan.lines), 2)
        source_line, = [
            line for line in plan.lines if line.source == source_move]
        self.assertEqual(source_line.quantity, 0.34)
