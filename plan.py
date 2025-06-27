from collections import defaultdict

from trytond.model import ModelSQL, ModelView, fields
from trytond.pool import Pool
from trytond.pyson import Eval
from trytond.transaction import Transaction
from trytond.exceptions import UserError
from trytond.i18n import gettext
from trytond.pyson import PYSONEncoder


# TODO: Add helps
# TODO: Optimize fields.Functions
class StockPlan(ModelSQL, ModelView):
    'Stock Plan'
    __name__ = 'stock.plan'

    calculate_excess = fields.Boolean('Calculate Excess',
        help=(
            'If checked, the plan will include all stock from warehouses, '
            'even if they do not have destination.')) # TODO: Subject to change: may be a configuration.
    company = fields.Many2One('company.company', 'Company',
        required=True, ondelete='CASCADE',
        help='The company for which the stock plan is created.')
    lines = fields.One2Many('stock.plan.line', 'plan', 'Lines')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('computed', 'Computed'),
        ('active', 'Active'),
        ('deprecated', 'Deprecated'),
    ], 'State', required=True, readonly=True)
    # Counts of lines
    correct_lines = fields.Function(
        fields.Integer('Correct Lines'), 'get_lines_count')
    excess_stock = fields.Function(fields.Integer('Excess Stock',
            states={ 'invisible': ~Eval('calculate_excess', True) }),
        'get_lines_count')
    late_stock = fields.Function(
        fields.Integer('Late Stock'), 'get_lines_count')
    # If you show 'lines' in the view, you will also load the lines, not only the count.
    total_lines = fields.Function(
        fields.Integer('Total Lines'), 'get_lines_count')
    without_stock = fields.Function(
        fields.Integer('Without Stock'), 'get_lines_count')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._buttons.update({
            'recalculate': {}
        })

    @staticmethod
    def default_company():
        transaction = Transaction()
        return transaction.context.get('company')

    @staticmethod
    def default_state():
        return 'draft'

    @classmethod
    def get_lines_count(cls, plans, names):
        pool = Pool()
        StockPlanLine = pool.get('stock.plan.line')

        result = {}
        for name in names:
            result[name] = {}
            for plan in plans:
                result[name][plan.id] = 0

                if name == 'correct_lines':
                    result[name][plan.id] = StockPlanLine.search_count([
                        ('plan', '=', plan.id),
                        ('source', '!=', None),
                        ('destination', '!=', None),
                        ['OR',
                            ('day_difference', '>', 0),
                            ('source', 'like', 'stock.location,%'),
                        ]
                    ])
                if name == 'excess_stock':
                    result[name][plan.id] = StockPlanLine.search_count([
                        ('plan', '=', plan.id),
                        ('destination', '=', None),
                    ])
                if name == 'late_stock':
                    result[name][plan.id] = StockPlanLine.search_count([
                        ('plan', '=', plan.id),
                        ('source', 'like', 'stock.move,%'),
                        ('destination', '!=', None),
                        ['OR',
                            ('day_difference', '=', None),
                            ('day_difference', '<', '0'),
                        ]
                    ])
                if name == 'total_lines':
                    result[name][plan.id] = len(plan.lines)
                if name == 'without_stock':
                    result[name][plan.id] = StockPlanLine.search_count([
                        ('plan', '=', plan.id),
                        ('source', '=', None),
                    ])

        return result

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

        warehouses = StockLocation.search([
            ('type', '=', 'warehouse')
        ])
        moves = StockMove.search([
            ('state', 'not in', ('done', 'cancelled')),
            ('company', '=', plan.company.id),
        ], order=[
            ('effective_date', 'ASC NULLS LAST'),
            ('planned_date', 'ASC NULLS LAST'),
            ('id', 'ASC'),
        ])
        lines = []
        today = Date.today()

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
                            source=warehouse, destination=move,
                            product=move.product,
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
                            source=ref, destination=move,
                            product=move.product,
                            source_date=(
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
                        source=warehouse, product=Product(key[1]))
                    for key, stock_quantity in stocks.items()
                    if key[0] == warehouse.id
                ])

        # EXCESS STOCK: Create for each existing incomes
        if plan.calculate_excess:
            lines.extend([
                StockPlanLine(plan=plan, quantity=income['quantity'],
                    source=income['ref'], product=income['ref'].product,
                    source_date=income['ref'].effective_date or income['ref'].planned_date)
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
    destination_date = fields.Date('Destination Date', readonly=True)
    destination_document = fields.Function(
        fields.Reference('Destination Document', 'get_document_refs'),
        'get_document')
    day_difference = fields.Function(fields.Integer('Day Difference'),
        'get_day_difference', searcher='search_day_difference')
    source = fields.Reference('Source', 'get_source')
    source_date = fields.Date('Source Date', readonly=True)
    source_document = fields.Function(
        fields.Reference('Source Document', 'get_document_refs'),
        'get_document')
    plan = fields.Many2One('stock.plan', 'Stock Plan',
        required=True, ondelete='CASCADE')
    product = fields.Many2One('product.product', 'Product',
        required=True, ondelete='CASCADE')
    quantity = fields.Integer('Quantity', required=True)
    uom = fields.Function(fields.Many2One('product.uom', 'UoM',
        help='The Unit of Measure for the quantities.'), 'get_uom')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls.__access__.add('plan')
        cls._buttons.update({
            'destination_relate': {},
            'source_relate': {},
        })

    @classmethod
    def get_document_refs(cls):
        pool = Pool()
        Model = pool.get('ir.model')
        StockMove = pool.get('stock.move')

        models = StockMove._get_document_origin() + StockMove._get_document()
        models = Model.search([
            ('model', 'in', models),
        ])
        return [(None, '')] + [(m.model, m.name) for m in models]

    @classmethod
    def get_source(cls):
        pool = Pool()
        Model = pool.get('ir.model')
        models = Model.search([ ('model', 'in', cls._get_source()) ])
        return [('', '')] + [(model.model, model.name) for model in models]

    @classmethod
    def _get_source(cls):
        return ['stock.move', 'stock.location']

    def get_document(self, name):
        if name == 'destination_document':
            field = self.destination
        elif name == 'source_document':
            field = self.source
        if not (field and hasattr(field, 'document')
                and hasattr(field, 'document_origin')):
            return
        return field.document or field.document_origin

    def get_day_difference(self, name):
        if not self.source_date or not self.destination_date:
            return
        day_difference = self.destination_date - self.source_date
        return day_difference.total_seconds() // (24 * 3600)

    def get_uom(self, name):
        if not self.product:
            return
        return self.product.default_uom

    @classmethod
    @ModelView.button
    def destination_relate(cls, lines):
        pool = Pool()
        Action = pool.get('ir.action')
        ModelData = pool.get('ir.model.data')

        encoder = PYSONEncoder()
        line = lines[0]

        if not line.destination:
            raise UserError(
                gettext('stock_plan.warn_line_without_destination'))

        view_id = ModelData.get_id('stock_plan', 'act_stock_plan_line')
        action = Action(view_id).get_action_value()

        action['name'] = gettext('stock_plan.title_destination_relate',
            destination=line.destination.rec_name)
        action['pyson_domain'] = encoder.encode([
            ('plan', '=', line.plan.id),
            ('destination', '=', line.destination.id),
        ])
        return action

    @classmethod
    @ModelView.button
    def source_relate(cls, lines):
        pool = Pool()
        Action = pool.get('ir.action')
        ModelData = pool.get('ir.model.data')

        encoder = PYSONEncoder()
        line = lines[0]

        if not line.source:
            raise UserError(
                gettext('stock_plan.warn_line_without_source'))

        view_id = ModelData.get_id('stock_plan', 'act_stock_plan_line')
        action = Action(view_id).get_action_value()

        action['name'] = gettext('stock_plan.title_source_relate',
            source=line.source.rec_name)
        action['pyson_domain'] = encoder.encode([
            ('plan', '=', line.plan.id),
            ('source', '=', line.source.id),
        ])
        return action

    @classmethod
    def search_day_difference(cls, name, clause):
        table = cls.__table__()

        _field, operator, value = clause
        Operator = fields.SQL_OPERATORS[operator]

        day_difference = table.destination_date - table.source_date

        query = (
            table.select(table.id, where=(Operator(day_difference, value))))
        return [('id', 'in', query)]
