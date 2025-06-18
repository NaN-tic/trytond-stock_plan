from datetime import timedelta
from trytond.transaction import Transaction
from trytond.model import ModelSQL, ModelView, fields
from trytond.pool import Pool
from collections import defaultdict, namedtuple


# TODO: Dos camps, no fields.Reference -> Seguro¿ Quiero decir, al fin y al cabo se seguirá haciendo un 'if' como: if line.origin elif line.origin_location
class StockPlan(ModelSQL, ModelView):
    'Stock Plan'
    __name__ = 'stock.plan'

    lines = fields.One2Many('stock.plan.line', 'plan', 'Lines')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._buttons.update({
            'recalculate': {}
        })

    @classmethod
    @ModelView.button
    def recalculate(cls, plans):
        pool = Pool()
        Date = pool.get('ir.date')
        Product = pool.get('product.product')
        StockLocation = pool.get('stock.location')
        StockMove = pool.get('stock.move')
        StockPlanLine = pool.get('stock.plan.line')
        Income = namedtuple('Income', ['move', 'quantity'])

        transaction = Transaction()

        plan = plans[0] # TODO: for plan in plans:
        lines = []

        moves = StockMove.search([
            ('state', 'not in', ('done', 'cancelled')),
        ], order=[
            ('effective_date', 'ASC NULLS LAST'),
            ('planned_date', 'ASC NULLS LAST'),
            ('id', 'ASC'),
        ])

        outgoing = defaultdict(list)
        incoming = defaultdict(list)
        needed_products = defaultdict(set)

        for move in moves:
            from_warehouse = move.from_location.warehouse
            to_warehouse = move.to_location.warehouse

            if from_warehouse == to_warehouse:
                continue
            if from_warehouse and from_warehouse != to_warehouse:
                outgoing[from_warehouse].append(move) # TODO:
                needed_products[from_warehouse.id].add(move.product.id)

            if to_warehouse and from_warehouse != to_warehouse:
                key = (to_warehouse.id, move.product.id)
                incoming[key].append(Income(move, move.quantity))

        for warehouse_id, moves in outgoing.items():
            with transaction.set_context(stock_date_end=Date.today()):
                stocks = Product.products_by_location([warehouse_id], with_childs=True, grouping_filter=(list(needed_products[warehouse_id]), ))
            warehouse = StockLocation(warehouse_id)

            for move in moves:
                key = (warehouse_id, move.product.id)
                stock_quantity = stocks.get(key, 0)
                move_quantity = move.quantity

                if stock_quantity > 0: # TODO: key in stocks
                    quantity = min(move_quantity, stock_quantity) # TODO: stocks[key]

                    lines.append(StockPlanLine(plan=plan, quantity=quantity, origin=warehouse, destination=move))
                    move_quantity -= quantity

                    if quantity == stocks[key]:
                        stocks.pop(key)
                    else:
                        stocks[key] -= quantity

                if move_quantity <= 0: # FIXME: ==
                    continue

                while len(incoming[key]) > 0:
                    if move_quantity <= 0: # FIXME: ==
                        break

                    income = incoming[key][0]

                    quantity = min(move_quantity, income.quantity)

                    lines.append(StockPlanLine(plan=plan, quantity=quantity, origin=income.move, destination=move))
                    move_quantity -= quantity

                    income.quantity -= quantity
                    if income.quantity <= 0:
                        incoming[key].remove(income)

                if move_quantity > 0:
                    lines.append(StockPlanLine(plan=plan, quantity=move_quantity, destination=move)) # TODO: Void line: Without origin

            lines.extend([
                StockPlanLine(plan=plan, quantity=stock_quantity, origin=warehouse) # TODO: Void line: Without destination
                for key, stock_quantity in stocks.items()
                if key[0] == warehouse_id # TODO: can have 0 quantity
            ])

        lines.extend([
            StockPlanLine(plan=plan, quantity=income.quantity, origin=income.move) # TODO: Void line: Without destination
            for income in incoming.values()
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
    difference = fields.Function(
        fields.TimeDelta('Difference'), 'get_difference')
    origin = fields.Reference('Origin Move', 'get_origin')
    plan = fields.Many2One('stock.plan', 'Stock Plan',
        required=True, ondelete='CASCADE')
    product = fields.Function(
        fields.Many2One('product.product', 'Product'), 'get_product')
    quantity = fields.Integer('Quantity', required=True)
    # TODO: UOM

#    def get_rec_name(self, name): # FIXME:
#        return f"{self.origin.rec_name} -> {self.destination.rec_name} ({self.product.rec_name})"

    @classmethod
    def get_origin(cls):
        pool = Pool()
        Model = pool.get('ir.model')
        models = Model.search([ ('model', 'in', cls._get_origin()) ])
        return [
            (model.model, model.name)
            for model in models
        ]

    @classmethod
    def _get_origin(cls):
        return ['stock.move', 'stock.location']

    def get_difference(self, name):
        return timedelta(0)
        destination = timedelta(0)
        origin = timedelta(0)

        if self.destination:
            destination = self.destination.effective_date or self.destination.planned_date or timedelta(0)

        if self.origin and self.origin.__name__ == 'stock.move':
            origin = self.origin.effective_date or self.origin.planned_date or timedelta(0)

        return destination - origin

    def get_product(self, name):
        if self.destination:
            return self.destination.product
        elif self.origin and hasattr(self.origin, 'product'):
            return self.origin.product
        else:
            return None


# class StockMove(metaclass=PoolMeta):
#     __name__ = 'stock.move'

#     def get_rec_name(self, name):
#         return f"{self.from_location.rec_name} -> {self.to_location.rec_name} ({self.product.rec_name})"
