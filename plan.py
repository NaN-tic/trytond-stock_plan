from collections import defaultdict

from sql.conditionals import Coalesce
from sql.operators import And, NotEqual, Null
from trytond.model import ModelSQL, ModelView, fields
from trytond.pool import Pool
from trytond.pyson import Eval
from trytond.transaction import Transaction


# TODO: Add helps
class StockPlan(ModelSQL, ModelView):
    'Stock Plan'
    __name__ = 'stock.plan'

    calculate_excess = fields.Boolean('Calculate Excess',
        help=(
            'If checked, the plan will include all stock from warehouses, '
            'even if they do not have destination.')) # TODO: Subject to change: may be a configuration.
    excess_stock = fields.Function(fields.Integer('Excess Stock', states={
            'invisible': ~Eval('calculate_excess', True)
        }), 'get_excess_stock')
    late_stock = fields.Function(
        fields.Integer('Late Stock'), 'get_late_stock')
    lines = fields.One2Many('stock.plan.line', 'plan', 'Lines')
    total_lines = fields.Function(
        # If you show 'lines' in the view, you will also load the lines, not only the count.
        fields.Integer('Total Lines'), 'get_total_lines')
    without_stock = fields.Function(
        fields.Integer('Without Stock'), 'get_without_stock')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._buttons.update({
            'recalculate': {}
        })

    @staticmethod
    def default_calculate_excess():
        return True

    def get_excess_stock(self, name):
        if not self.calculate_excess:
            return
        return len([line for line in self.lines if not line.destination])

    def get_late_stock(self, name):
        lates = [
            line for line in self.lines
            if line.origin and line.destination and (
                line.day_difference is None or line.day_difference < 0)]
        return len(lates)

    def get_total_lines(self, name):
        return len(self.lines)

    def get_without_stock(self, name):
        return len([line for line in self.lines if not line.origin])

    @classmethod
    @ModelView.button
    def recalculate(cls, plans):
        for plan in plans:
            cls._recalculate(plan)

    @classmethod
    def _recalculate(cls, plan):
        pool = Pool()
        Product = pool.get('product.product')
        StockMove = pool.get('stock.move')
        StockLocation = pool.get('stock.location')
        StockPlanLine = pool.get('stock.plan.line')

        transaction = Transaction()

        warehouses = StockLocation.search([
            ('type', '=', 'warehouse')
        ])
        moves = StockMove.search([
            ('state', 'not in', ('done', 'cancelled')),
        ], order=[
            ('effective_date', 'ASC NULLS LAST'),
            ('planned_date', 'ASC NULLS LAST'),
            ('id', 'ASC'),
        ])
        lines = []
        today = StockPlanLine._default_date()

        outgoing = defaultdict(list)
        incoming = defaultdict(list)
        needed_products = defaultdict(set)

        for move in moves:
            from_warehouse = move.from_location.warehouse
            to_warehouse = move.to_location.warehouse

            if from_warehouse == to_warehouse:
                continue

            if from_warehouse and from_warehouse != to_warehouse:
                outgoing[from_warehouse].append(move)
                if not plan.calculate_excess:
                    needed_products[from_warehouse.id].add(move.product.id)

            if to_warehouse and from_warehouse != to_warehouse:
                key = (to_warehouse.id, move.product.id)
                incoming[key].append({ 'ref': move, 'quantity': move.internal_quantity })

        for warehouse in warehouses:
            products_filter = needed_products.get(warehouse.id, None)
            if products_filter:
                products_filter = (list(products_filter), )

            with transaction.set_context(stock_date_end=today):
                stocks = Product.products_by_location(
                    [warehouse.id],
                    with_childs=True,
                    grouping_filter=products_filter)

            for key in list(stocks.keys()):
                if stocks[key] <= 0:
                    stocks.pop(key)

            moves = outgoing[warehouse]
            for move in moves:
                key = (warehouse.id, move.product.id)
                remain_quantity = move.internal_quantity

                if key in stocks:
                    quantity = min(remain_quantity, stocks[key])
                    remain_quantity -= quantity
                    stocks[key] -= quantity
                    if stocks[key] <= 0:
                        stocks.pop(key)

                    lines.append(
                        StockPlanLine(plan=plan, quantity=quantity,
                            origin=warehouse, destination=move,
                            product=move.product, origin_date=today,
                            destination_date=(
                                move.effective_date or move.planned_date
                            )))

                if remain_quantity == 0:
                    continue

                while len(incoming[key]) > 0:
                    if remain_quantity == 0:
                        break
                    income = incoming[key][0]

                    quantity = min(remain_quantity, income['quantity'])
                    remain_quantity -= quantity
                    income['quantity'] -= quantity
                    if income['quantity'] <= 0:
                        incoming[key].remove(income)

                    ref = income['ref']
                    lines.append(
                        StockPlanLine(plan=plan, quantity=quantity,
                            origin=ref, destination=move,
                            product=move.product,
                            origin_date=(
                                ref.effective_date or ref.planned_date
                            ),
                            destination_date=(
                                move.effective_date or move.planned_date
                            )))

                # WITHOUT STOCK: Move without destination
                if remain_quantity > 0:
                    lines.append(
                        StockPlanLine(plan=plan, quantity=remain_quantity,
                            destination=move, product=move.product,
                            destination_date=(
                                move.effective_date or move.planned_date
                            )))

            # EXCESS STOCK: Create for each existing stock at warehouse
            if plan.calculate_excess:
                lines.extend([
                    StockPlanLine(plan=plan, quantity=stock_quantity,
                        origin=warehouse, product=Product(key[1]),
                        origin_date=today)
                    for key, stock_quantity in stocks.items()
                    if key[0] == warehouse.id
                ])

        # EXCESS STOCK: Create for each existing incomes
        if plan.calculate_excess:
            lines.extend([
                StockPlanLine(plan=plan, quantity=income['quantity'],
                    origin=income['ref'], product=income['ref'].product,
                    origin_date=income['ref'].effective_date or income['ref'].planned_date)
                for incomes in incoming.values()
                for income in incomes
            ])

        StockPlanLine.save(lines)
        plan.lines = lines
        cls.save([plan])


# TODO: Set domains?
# TODO: destination_desc = fields.Function
class StockPlanLine(ModelSQL, ModelView):
    'Stock Plan Line'
    __name__ = 'stock.plan.line'

    destination = fields.Many2One('stock.move', 'Destination Move')
    destination_date = fields.Date('Destination Date', readonly=True) # TODO: Domains
    day_difference = fields.Function(fields.Integer('Day Difference'),
        'get_day_difference', searcher='search_day_difference')
    origin = fields.Reference('Origin', 'get_origin')
    origin_date = fields.Date('Origin Date', readonly=True) # TODO: Domains
    plan = fields.Many2One('stock.plan', 'Stock Plan',
        required=True, ondelete='CASCADE')
    product = fields.Many2One('product.product', 'Product',
        required=True, ondelete='CASCADE')
    quantity = fields.Integer('Quantity', required=True)
    uom = fields.Function(fields.Many2One('product.uom', 'Quantity UoM',
        help='The Unit of Measure for the quantities.'), 'get_uom')

    @staticmethod
    def _default_date():
        pool = Pool()
        Date = pool.get('ir.date')
        return Date.today()

    @classmethod
    def get_origin(cls):
        pool = Pool()
        Model = pool.get('ir.model')
        models = Model.search([ ('model', 'in', cls._get_origin()) ])
        return [('', '')] + [(model.model, model.name) for model in models]

    @classmethod
    def _get_origin(cls):
        return ['stock.move', 'stock.location']

    def get_day_difference(self, name):
        if not (self.origin_date and self.destination_date):
            return
        elif self.origin_date and not self.destination_date:
            return

        destination_date = self.destination_date or self._default_date()
        origin_date = self.origin_date or self._default_date()

        day_difference = destination_date - origin_date
        return day_difference.total_seconds() // (24 * 3600)

    def get_uom(self, name):
        if not self.product:
            return
        return self.product.default_uom

    @classmethod
    def search_day_difference(cls, name, clause):
        pool = Pool()
        Date = pool.get('ir.date')

        table = cls.__table__()
        today = Date.today()

        _field, operator, value = clause
        Operator = fields.SQL_OPERATORS[operator]

        destination_date = Coalesce(table.destination_date, today)
        origin_date = Coalesce(table.origin_date, today)
        day_difference = destination_date - origin_date

        query = (
            table.select(table.id,
                where=(And([
                    Operator(day_difference,value),
                    NotEqual(table.destination_date, Null)])
                )))
        return [('id', 'in', query)]
