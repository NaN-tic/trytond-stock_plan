import unittest
from datetime import datetime
from proteus import Model
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules
from trytond.modules.company.tests.tools import create_company, get_company
from trytond.modules.stock.exceptions import MoveOriginWarning
from decimal import Decimal


class Test(unittest.TestCase):

    def setUp(self):
        drop_db()

    def tearDown(self):
        drop_db()

    def test(self):
        config = activate_modules(['stock', 'stock_plan'])

        ProductUom = Model.get('product.uom')
        ProductTemplate = Model.get('product.template')
        StockLocation = Model.get('stock.location')
        StockMove = Model.get('stock.move')
        StockPlan = Model.get('stock.plan')
        StockPlanLine = Model.get('stock.plan.line')
        Warning = Model.get('res.user.warning')

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

        # Create stock plan
        plan = StockPlan(include_excess_stock=True)

        def click_do(move):
            try:
                move.click('do')
            except MoveOriginWarning as warning:
                _, (key, *_) = warning.args
                Warning(user=config.user, name=key).save()
                move.click('do')

        # CASE 1: Testing source as stock moves.
        # Incoming Moves (x1): 1 egg
        # Storage: None
        # Customer: 1 egg
        eggs_move_draft = StockMove(
            product=eggs,
            quantity=1,
            from_location=supplier_location,
            to_location=storage_location,
            currency=company.currency,
            unit_price=eggs.cost_price,)
        eggs_move_draft.save()

        customer_move = StockMove(
            product=eggs,
            quantity=1,
            from_location=storage_location,
            to_location=customer_location,
            currency=company.currency,
            unit_price=Decimal('1.00'),)
        customer_move.save()

        plan.click('recalculate')
        plan.reload()

        self.assertEqual(len(plan.lines), 1)
        self.assertEqual(plan.lines[0].product, eggs)
        self.assertEqual(plan.lines[0].quantity, 1)
        self.assertEqual(plan.lines[0].source, eggs_move_draft)
        self.assertEqual(plan.lines[0].destination, customer_move)

        eggs_move_draft.click('cancel')
        customer_move.click('cancel')

        # CASE 2: Testing source as storage.
        # Incoming Moves: None
        # Storage: 1 egg
        # Customer: 1 egg
        eggs_storage = StockMove(
            product=eggs,
            quantity=1,
            from_location=supplier_location,
            to_location=storage_location,
            currency=company.currency,
            unit_price=eggs.cost_price)
        eggs_storage.save()
        click_do(eggs_storage)

        customer_move = StockMove(
            product=eggs,
            quantity=1,
            from_location=storage_location,
            to_location=customer_location,
            currency=company.currency,
            unit_price=Decimal('1.00'),)
        customer_move.save()

        plan.click('recalculate')
        plan.reload()

        self.assertEqual(len(plan.lines), 1)
        self.assertEqual(plan.lines[0].product, eggs)
        self.assertEqual(plan.lines[0].quantity, 1)
        self.assertEqual(plan.lines[0].source, warehouse_location)
        self.assertEqual(plan.lines[0].destination, customer_move)

        click_do(customer_move)

        # CASE 3: Testing mixed source.
        # Incoming Moves (x1): 1 egg, 100g salt
        # Storage: 1 egg, 100g salt
        # Customer: 2 egg, 200g salt
            # Create incoming moves
        eggs_move_draft = StockMove(
            product=eggs,
            quantity=1,
            from_location=supplier_location,
            to_location=storage_location,
            currency=company.currency,
            unit_price=eggs.cost_price,)
        eggs_move_draft.save()

        salt_move_draft = StockMove(
            product=salt,
            quantity=100,
            from_location=supplier_location,
            to_location=storage_location,
            currency=company.currency,
            unit_price=salt.cost_price,)
        salt_move_draft.save()

            # Create storage moves
        eggs_storage = StockMove(
            product=eggs,
            quantity=1,
            from_location=supplier_location,
            to_location=storage_location,
            currency=company.currency,
            unit_price=eggs.cost_price,)
        eggs_storage.save()
        click_do(eggs_storage)

        salt_storage = StockMove(
            product=salt,
            quantity=100,
            from_location=supplier_location,
            to_location=storage_location,
            currency=company.currency,
            unit_price=salt.cost_price,)
        salt_storage.save()
        click_do(salt_storage)

            # Create customer moves
        customer_move_eggs = StockMove(
            product=eggs,
            quantity=2,
            from_location=storage_location,
            to_location=customer_location,
            currency=company.currency,
            unit_price=Decimal('1.00'),)
        customer_move_eggs.save()

        customer_move_salt = StockMove(
            product=salt,
            quantity=200,
            from_location=storage_location,
            to_location=customer_location,
            currency=company.currency,
            unit_price=Decimal('0.40'),)
        customer_move_salt.save()

        plan.click('recalculate')
        plan.reload()

        self.assertEqual(len(plan.lines), 4)

            # Check plan lines for incoming moves
        eggs_move_line = StockPlanLine.find([
            ('source', '=', eggs_move_draft),
            ('destination', '=', customer_move_eggs.id),
            ('product', '=', eggs.id),
        ])
        salt_move_line = StockPlanLine.find([
            ('source', '=', salt_move_draft),
            ('destination', '=', customer_move_salt.id),
            ('product', '=', salt.id),
        ])

        self.assertEqual(len(eggs_move_line), 1)
        self.assertEqual(eggs_move_line[0].quantity, 1)

        self.assertEqual(len(salt_move_line), 1)
        self.assertEqual(salt_move_line[0].quantity, 100)

            # Check plan lines for storage moves
        eggs_storage_line = StockPlanLine.find([
            ('source', '=', warehouse_location),
            ('destination', '=', customer_move_eggs.id),
            ('product', '=', eggs.id),
        ])
        salt_storage_line = StockPlanLine.find([
            ('source', '=', warehouse_location),
            ('destination', '=', customer_move_salt.id),
            ('product', '=', salt.id),
        ])

        self.assertEqual(len(eggs_storage_line), 1)
        self.assertEqual(eggs_storage_line[0].quantity, 1)

        self.assertEqual(len(salt_storage_line), 1)
        self.assertEqual(salt_storage_line[0].quantity, 100)

        click_do(eggs_move_draft)
        click_do(salt_move_draft)
        click_do(customer_move_eggs)
        click_do(customer_move_salt)

        # CASE 4: Testing mixed source with excess stock.
        # Incoming Moves (x2): 4 eggs, 400g salt
        # Storage: 1 eggs, 50g salt
        # Customer: 4 eggs, 400g salt
            # Create incoming moves
        eggs_move_draft = StockMove(
            product=eggs,
            quantity=2,
            from_location=supplier_location,
            to_location=storage_location,
            currency=company.currency,
            unit_price=eggs.cost_price,)
        eggs_move_draft.save()

        salt_move_draft = StockMove(
            product=salt,
            quantity=200,
            from_location=supplier_location,
            to_location=storage_location,
            currency=company.currency,
            unit_price=salt.cost_price,)
        salt_move_draft.save()

        eggs_move_draft_copy, = eggs_move_draft.duplicate()
        salt_move_draft_copy, = salt_move_draft.duplicate()

            # Create storage moves
        eggs_storage = StockMove(
            product=eggs,
            quantity=1,
            from_location=supplier_location,
            to_location=storage_location,
            currency=company.currency,
            unit_price=eggs.cost_price,)
        eggs_storage.save()
        click_do(eggs_storage)

        salt_storage = StockMove(
            product=salt,
            quantity=50,
            from_location=supplier_location,
            to_location=storage_location,
            currency=company.currency,
            unit_price=salt.cost_price,)
        salt_storage.save()
        click_do(salt_storage)

            # Create customer moves
        customer_move_eggs = StockMove(
            product=eggs,
            quantity=4,
            from_location=storage_location,
            to_location=customer_location,
            currency=company.currency,
            unit_price=Decimal('1.00'),)
        customer_move_eggs.save()

        customer_move_salt = StockMove(
            product=salt,
            quantity=400,
            from_location=storage_location,
            to_location=customer_location,
            currency=company.currency,
            unit_price=Decimal('0.40'),)
        customer_move_salt.save()

        plan.click('recalculate')
        plan.reload()

        self.assertEqual(len(plan.lines), 8)

            # Check plan lines for incoming moves
        eggs_move_lines = StockPlanLine.find([
            ('source', 'in', (eggs_move_draft, eggs_move_draft_copy)),
            ('destination', '=', customer_move_eggs.id),
            ('product', '=', eggs.id),
        ], order=[('quantity', 'DESC')])
        salt_move_lines = StockPlanLine.find([
            ('source', 'in', (salt_move_draft, salt_move_draft_copy)),
            ('destination', '=', customer_move_salt.id),
            ('product', '=', salt.id),
        ], order=[('quantity', 'DESC')])

        self.assertEqual(len(eggs_move_lines), 2)
        self.assertEqual(eggs_move_lines[0].quantity, 2)
        self.assertEqual(eggs_move_lines[0].source, eggs_move_draft)
        self.assertEqual(eggs_move_lines[1].quantity, 1)
        self.assertEqual(eggs_move_lines[1].source, eggs_move_draft_copy)

        self.assertEqual(len(salt_move_lines), 2)
        self.assertEqual(salt_move_lines[0].quantity, 200)
        self.assertEqual(salt_move_lines[0].source, salt_move_draft)
        self.assertEqual(salt_move_lines[1].quantity, 150)
        self.assertEqual(salt_move_lines[1].source, salt_move_draft_copy)

            # Check plan lines for stock moves
        eggs_storage_line = StockPlanLine.find([
            ('source', '=', warehouse_location),
            ('destination', '=', customer_move_eggs.id),
            ('product', '=', eggs.id),
        ])
        salt_storage_line = StockPlanLine.find([
            ('source', '=', warehouse_location),
            ('destination', '=', customer_move_salt.id),
            ('product', '=', salt.id),
        ])

        self.assertEqual(len(eggs_storage_line), 1)
        self.assertEqual(eggs_storage_line[0].quantity, 1)

        self.assertEqual(len(salt_storage_line), 1)
        self.assertEqual(salt_storage_line[0].quantity, 50)

            # Check for excess stock
        excess_eggs = StockPlanLine.find([
            ('source', '=', eggs_move_draft_copy),
            ('destination', '=', None),
            ('product', '=', eggs.id),
        ])
        excess_salt = StockPlanLine.find([
            ('source', '=', salt_move_draft_copy),
            ('destination', '=', None),
            ('product', '=', salt.id),
        ])

        self.assertEqual(len(excess_eggs), 1)
        self.assertEqual(excess_eggs[0].quantity, 1)

        self.assertEqual(len(excess_salt), 1)
        self.assertEqual(excess_salt[0].quantity, 50)

        click_do(eggs_move_draft)
        click_do(eggs_move_draft_copy)
        click_do(salt_move_draft)
        click_do(salt_move_draft_copy)
        click_do(customer_move_eggs)
        click_do(customer_move_salt)

            # Remove excess stock
        excess_eggs_customer = StockMove(
            product=eggs,
            quantity=1,
            from_location=storage_location,
            to_location=customer_location,
            currency=company.currency,
            unit_price=eggs.cost_price,)
        excess_eggs_customer.save()
        click_do(excess_eggs_customer)

        excess_salt_customer = StockMove(
            product=salt,
            quantity=50,
            from_location=storage_location,
            to_location=customer_location,
            currency=company.currency,
            unit_price=salt.cost_price,)
        excess_salt_customer.save()
        click_do(excess_salt_customer)

        # CASE 5: Testing no stock.
        # Incoming Moves: None
        # Storage: None
        # Customer: 1 egg
        customer_move = StockMove(
            product=eggs,
            quantity=1,
            from_location=storage_location,
            to_location=customer_location,
            currency=company.currency,
            unit_price=Decimal('1.00'),)
        customer_move.save()

        plan.click('recalculate')
        plan.reload()

        self.assertEqual(len(plan.lines), 1)
        self.assertEqual(plan.lines[0].product, eggs)
        self.assertEqual(plan.lines[0].quantity, 1)
        self.assertEqual(plan.lines[0].destination, customer_move)
        self.assertIsNone(plan.lines[0].source)

        customer_move.click('cancel')

        # CASE 6: Testing late stock (with date variations).
        # Incoming Moves: 1 egg
        # Storage: None
        # Customer: 1 egg
        eggs_move_draft = StockMove(
            product=eggs,
            quantity=1,
            from_location=supplier_location,
            to_location=storage_location,
            currency=company.currency,
            unit_price=eggs.cost_price,)
        eggs_move_draft.save()

        customer_move = StockMove(
            product=eggs,
            quantity=1,
            from_location=storage_location,
            to_location=customer_location,
            currency=company.currency,
            unit_price=Decimal('1.00'),)
        customer_move.save()

        def late_date_check(lines):
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0].product, eggs)
            self.assertEqual(lines[0].quantity, 1)
            self.assertEqual(lines[0].source, eggs_move_draft)
            self.assertEqual(lines[0].destination, customer_move)

        late_date = datetime(year=2034, month=10, day=19).date()
        today = datetime.now().date()

            # Check with effective_date on both records.
        eggs_move_draft.effective_date = late_date
        eggs_move_draft.planned_date = None
        eggs_move_draft.save()

        customer_move.effective_date = today
        customer_move.planned_date = None
        customer_move.save()

        plan.click('recalculate')
        plan.reload()

        late_date_check(plan.lines)
        self.assertLess(plan.lines[0].day_difference, 0)

            # The same, but with planned_date.
        eggs_move_draft.effective_date = None
        eggs_move_draft.planned_date = late_date
        eggs_move_draft.save()

        customer_move.effective_date = None
        customer_move.planned_date = today
        customer_move.save()

        plan.click('recalculate')
        plan.reload()

        late_date_check(plan.lines)
        self.assertLess(plan.lines[0].day_difference, 0)

            # The same, but with effective_date and planned_date.
        eggs_move_draft.effective_date = late_date
        eggs_move_draft.planned_date = None
        eggs_move_draft.save()

        customer_move.effective_date = None
        customer_move.planned_date = today
        customer_move.save()

        plan.click('recalculate')
        plan.reload()

        late_date_check(plan.lines)
        self.assertLess(plan.lines[0].day_difference, 0)

            # The same, but with effective_date and None.
        eggs_move_draft.effective_date = late_date
        eggs_move_draft.planned_date = None
        eggs_move_draft.save()

        customer_move.effective_date = None
        customer_move.planned_date = None
        customer_move.save()

        plan.click('recalculate')
        plan.reload()

        late_date_check(plan.lines)
        self.assertEqual(plan.lines[0].day_difference, None)

            # The same, but with planned_date and None.
        eggs_move_draft.effective_date = None
        eggs_move_draft.planned_date = late_date
        eggs_move_draft.save()

        customer_move.effective_date = None
        customer_move.planned_date = None
        customer_move.save()

        plan.click('recalculate')
        plan.reload()

        late_date_check(plan.lines)
        self.assertEqual(plan.lines[0].day_difference, None)

        click_do(eggs_move_draft)
        click_do(customer_move)

        # CASE 7: Testing mixed storage.
        # Incoming Moves (from Storage 1): 1 egg
        # Storage 2: None
        # Customer: 1 egg
        warehouse_copy, = warehouse_location.duplicate()
        storage_copy, = StockLocation.find([
            ('id', '!=', storage_location.id),
            ('code', '=', 'STO'),
        ])

        eggs_move_draft = StockMove(
            product=eggs,
            quantity=1,
            from_location=supplier_location,
            to_location=storage_copy,
            currency=company.currency,
            unit_price=eggs.cost_price,)
        eggs_move_draft.save()

        eggs_warehouse_draft = StockMove(
            product=eggs,
            quantity=1,
            from_location=storage_copy,
            to_location=storage_location,)
        eggs_warehouse_draft.save()

        customer_move = StockMove(
            product=eggs,
            quantity=1,
            from_location=storage_location,
            to_location=customer_location,
            currency=company.currency,
            unit_price=Decimal('1.00'),)
        customer_move.save()

        plan.click('recalculate')
        plan.reload()
        self.assertEqual(len(plan.lines), 2)

        eggs_move_line = StockPlanLine.find([
            ('source', '=', eggs_move_draft),
        ])

        self.assertEqual(len(eggs_move_line), 1)
        self.assertEqual(eggs_move_line[0].product, eggs)
        self.assertEqual(eggs_move_line[0].quantity, 1)
        self.assertEqual(eggs_move_line[0].destination, eggs_warehouse_draft)

        customer_move_line = StockPlanLine.find([
            ('destination', '=', customer_move),
        ])

        self.assertEqual(len(customer_move_line), 1)
        self.assertEqual(customer_move_line[0].product, eggs)
        self.assertEqual(customer_move_line[0].quantity, 1)
        self.assertEqual(customer_move_line[0].source, eggs_warehouse_draft)

        click_do(eggs_move_draft)
        click_do(eggs_warehouse_draft)
        click_do(customer_move)

        # CASE 8: Testing excess stock (with include_excess_stock enabled)
        # Incoming Moves: 1 egg
        # Storage: 100g salt
        # Customer: None
        eggs_move_draft = StockMove(
            product=eggs,
            quantity=1,
            from_location=supplier_location,
            to_location=storage_location,
            currency=company.currency,
            unit_price=eggs.cost_price,)
        eggs_move_draft.save()

        salt_storage = StockMove(
            product=salt,
            quantity=100,
            from_location=supplier_location,
            to_location=storage_location,
            currency=company.currency,
            unit_price=salt.cost_price,)
        salt_storage.save()
        click_do(salt_storage)

        plan.click('recalculate')
        plan.reload()

        self.assertEqual(len(plan.lines), 2)

        eggs_move_line = StockPlanLine.find([
            ('product', '=', eggs.id),
        ])

        self.assertEqual(len(eggs_move_line), 1)
        self.assertEqual(eggs_move_line[0].quantity, 1)
        self.assertEqual(eggs_move_line[0].source, eggs_move_draft)
        self.assertIsNone(eggs_move_line[0].destination)

        salt_line = StockPlanLine.find([
            ('product', '=', salt.id),
        ])

        self.assertEqual(len(salt_line), 1)
        self.assertEqual(salt_line[0].quantity, 100)
        self.assertEqual(salt_line[0].source, warehouse_location)
        self.assertIsNone(salt_line[0].destination)

        # CASE 9: Testing excess stock (with include_excess_stock disabled)
        # Incoming Moves: 1 egg
        # Storage: 100g salt
        # Customer: None

        plan.include_excess_stock = False
        plan.save()
        plan.click('recalculate')
        plan.reload()

        self.assertEqual(len(plan.lines), 0)

        click_do(eggs_move_draft)

        excess_salt_customer = StockMove(
            product=salt,
            quantity=100,
            from_location=storage_location,
            to_location=customer_location,
            currency=company.currency,
            unit_price=salt.cost_price,)
        excess_salt_customer.save()
        click_do(excess_salt_customer)
