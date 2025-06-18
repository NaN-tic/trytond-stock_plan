import unittest
from datetime import datetime
from proteus import Model
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules
from trytond.modules.company.tests.tools import create_company, get_company
from decimal import Decimal


class Test(unittest.TestCase):

    def setUp(self):
        drop_db()

    def tearDown(self):
        drop_db()

    def test(self):
        config = activate_modules(['stock'])

        ProductUom = Model.get('product.uom')
        ProductTemplate = Model.get('product.template')
        StockLocation = Model.get('stock.location')
        StockMove = Model.get('stock.move')
        StockPlan = Model.get('stock.plan')

        # Global variables
        today = datetime.now()

        # Create company
        create_company()
        company = get_company()

        # Get product UOMs
        unit, = ProductUom.find([('name', '=', 'Unit')])
        gram, = ProductUom.find([('name', '=', 'Gram')])

        # Create product templates
        eggs_template = ProductTemplate(
            name='Huevo',
            default_uom=unit,
            type='goods',
            list_price=Decimal('0.50'),
            cost_price_method='average')

        salt_template = ProductTemplate(
            name='Sal',
            default_uom=gram,
            type='goods',
            list_price=Decimal('0.10'),
            cost_price_method='average')

        # Create products (or product variants) from templates
        eggs, = eggs_template.products
        eggs.code = 'Large'
        eggs.cost_price = Decimal('0.20')
        eggs_template.save()
        eggs, = eggs_template.products

        salt, = salt_template.products
        salt.code = 'Thin'
        salt.cost_price = Decimal('0.05')
        salt_template.save()
        salt, = salt_template.products

        # Get locations
        supplier_location, = StockLocation.find([('code', '=', 'SUP')])
        storage_location, = StockLocation.find([('code', '=', 'STO')])
        customer_location, = StockLocation.find([('code', '=', 'CUS')])
        warehouse_location, = StockLocation.find([('code', '=', 'WH')])

        # Create drafted stock moves to storage
        salt_move_draft = StockMove(
            product=salt,
            quantity=100,
            from_location=supplier_location,
            to_location=storage_location,
            unit_price=Decimal('0.2'),
            currency=company.currency)
        salt_move_draft.save()

        eggs_move_draft = StockMove(
            product=eggs,
            quantity=2,
            from_location=supplier_location,
            to_location=storage_location,
            unit_price=Decimal('0.8'),
            currency=company.currency)
        eggs_move_draft.save()

        # Create finalized stock moves to storage
        eggs_move = StockMove(
            product=eggs,
            quantity=2,
            from_location=supplier_location,
            to_location=storage_location,
            unit_price=Decimal('0.8'),
            currency=company.currency)
        eggs_move.click('do')
        eggs_move.reload()

        # Create drafted stock moves to customer
        eggs_move_customer = StockMove(
            product=eggs,
            quantity=4,
            from_location=storage_location,
            to_location=customer_location,
            unit_price=Decimal('0.8'),
            currency=company.currency)
        eggs_move_customer.save()

        #
        plan = StockPlan() # TODO:
        plan.click('recalculate')
        plan.reload()
