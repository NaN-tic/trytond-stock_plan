from trytond.transaction import Transaction
from trytond.model import ModelSQL, ModelView, fields
from trytond.pool import Pool
from collections import defaultdict
from trytond.pyson import Eval


class StockPlan(ModelSQL, ModelView):
    'Stock Plan'
    __name__ = 'stock.plan'

    lines = fields.One2Many('stock.plan.line', 'plan', 'Lines')
    # If you show 'lines' in the view, you will also load the lines, not only the count.
    total_lines = fields.Function(
        fields.Integer('Total Lines'), 'get_total_lines')
    without_stock = fields.Function(
        fields.Integer('Without Stock'), 'get_without_stock')
    late_stock = fields.Function(
        fields.Integer('Late Stock'), 'get_late_stock')
    excess_stock = fields.Function(
        fields.Integer('Excess Stock',
            states={ 'invisible': ~Eval('calculate_excess', True) }),
            'get_excess_stock')
    calculate_excess = fields.Boolean('Calculate Excess', help=(
        'If checked, the plan will include all stock from warehouses, '
        'even if they do not have destination.')) # TODO: Subject to change: may be a configuration.

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._buttons.update({
            'recalculate': {}
        })

    @staticmethod
    def default_calculate_excess():
        return True

    def get_total_lines(self, name):
        return len(self.lines)

    def get_without_stock(self, name):
        return len([line for line in self.lines if not line.origin])

    def get_late_stock(self, name):
        return len([line for line in self.lines if line.day_difference < 0])

    def get_excess_stock(self, name):
        # if not self.calculate_excess: TODO:
        #     return 0
        return len([line for line in self.lines if not line.destination])

    @classmethod
    @ModelView.button
    def recalculate(cls, plans):
        for plan in plans:
            cls._recalculate(plan)

    @classmethod
    def _recalculate(cls, plan):
        pool = Pool()
        Date = pool.get('ir.date')
        Product = pool.get('product.product')
        StockMove = pool.get('stock.move')
        StockLocation = pool.get('stock.location')
        StockPlanLine = pool.get('stock.plan.line')

        transaction = Transaction()

        warehouses = StockLocation.search([('type', '=', 'warehouse')])
        moves = StockMove.search([
            ('state', 'not in', ('done', 'cancelled')),
        ], order=[
            ('effective_date', 'ASC NULLS LAST'),
            ('planned_date', 'ASC NULLS LAST'),
            ('id', 'ASC'),
        ])
        lines = []

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
                if plan.calculate_excess:
                    needed_products[from_warehouse.id].add(move.product.id)

            if to_warehouse and from_warehouse != to_warehouse:
                key = (to_warehouse.id, move.product.id)
                incoming[key].append({ 'ref': move, 'quantity': move.quantity })

        for warehouse in warehouses:
            with transaction.set_context(stock_date_end=Date.today()):
                if plan.calculate_excess:
                    stocks = Product.products_by_location([warehouse.id], with_childs=True, grouping_filter=(list(needed_products[warehouse.id]), ))
                else:
                    stocks = Product.products_by_location([warehouse.id], with_childs=True)
                stocks = {
                    key:value
                    for key, value in stocks.items() if value > 0
                }

            moves = outgoing[warehouse]
            for move in moves:
                key = (warehouse.id, move.product.id)
                move_quantity = move.quantity

                if key in stocks:
                    quantity = min(move_quantity, stocks[key])
                    move_quantity -= quantity
                    stocks[key] -= quantity
                    if stocks[key] <= 0:
                        stocks.pop(key)

                    lines.append(StockPlanLine(plan=plan, quantity=quantity, origin=warehouse, destination=move, product=move.product, origin_date=StockPlanLine._default_date(), destination_date=move.effective_date or move.planned_date))

                if (move_quantity - 0) == 0:
                    continue

                while len(incoming[key]) > 0:
                    if (move_quantity - 0) == 0:
                        break
                    income = incoming[key][0]

                    quantity = min(move_quantity, income['quantity'])
                    move_quantity -= quantity
                    income['quantity'] -= quantity
                    if income['quantity'] <= 0:
                        incoming[key].remove(income)

                    lines.append(StockPlanLine(plan=plan, quantity=quantity, origin=income['ref'], destination=move, product=move.product, origin_date=income['ref'].effective_date or income['ref'].planned_date, destination_date=move.effective_date or move.planned_date))

                # WITHOUT STOCK: Move without destination
                if move_quantity > 0:
                    lines.append(StockPlanLine(plan=plan, quantity=move_quantity, destination=move, product=move.product, destination_date=move.effective_date or move.planned_date))

            # EXCESS STOCK: Create for each existing stock at warehouse
            if plan.calculate_excess:
                lines.extend([
                    StockPlanLine(plan=plan, quantity=stock_quantity, origin=warehouse, product=Product(key[1]), origin_date=StockPlanLine._default_date(),)
                    for key, stock_quantity in stocks.items()
                    if key[0] == warehouse.id
                ])

        # EXCESS STOCK: Create for each existing incomes
        if plan.calculate_excess:
            lines.extend([
                StockPlanLine(plan=plan, quantity=income['quantity'], origin=income['ref'], product=income['ref'].product, origin_date=income['ref'].effective_date or income['ref'].planned_date)
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
    origin = fields.Reference('Origin Move', 'get_origin')
    origin_date = fields.Date('Origin Date', readonly=True) # TODO: Domains
    plan = fields.Many2One('stock.plan', 'Stock Plan',
        required=True, ondelete='CASCADE')
    product = fields.Many2One('product.product', 'Product',
        required=True, ondelete='CASCADE')
    quantity = fields.Integer('Quantity', required=True)
#    uom = fields.Many2One('product.uom', 'Quantity UoM',
#        help='The Unit of Measure for the quantities.', required=True)

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
            return 0
        elif self.origin_date and not self.destination_date:
            return 0

        destination_date = self.destination_date or self._default_date()
        origin_date = self.origin_date or self._default_date()

        day_difference = destination_date - origin_date
        return day_difference.total_seconds() // (24 * 3600)

    @classmethod
    def search_day_difference(cls, name, clause):

        from sql.conditionals import Coalesce
        from sql.operators import And, NotEqual, Null

        pool = Pool()
        Date = pool.get('ir.date')

        table = cls.__table__()
        today = Date.today()

        _field, operator, value = clause

        Operator = fields.SQL_OPERATORS[operator]
        query = (
            table
                .select(table.id,
                    where=(And([
                        Operator(
                            Coalesce(table.destination_date, today) - Coalesce(table.origin_date, today),
                            value
                        ),
                        NotEqual(table.destination_date, Null)
                        ])
                    )
                )
        )

        return [('id', 'in', query)]


    # TODO: Probar test
    # TODO: Probar módulo con otras bases de datos
