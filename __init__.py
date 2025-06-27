# This file is part stock_plan module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.pool import Pool
from . import plan

def register():
    Pool.register(
        plan.StockPlan,
        plan.StockPlanLine,
        plan.StockMove,
        module='stock_plan', type_='model')
    Pool.register(
        module='stock_plan', type_='wizard')
    Pool.register(
        module='stock_plan', type_='report')
