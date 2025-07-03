# This file is part stock_plan module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.modules.company.tests import CompanyTestMixin
from trytond.tests.test_tryton import ModuleTestCase

class StockPlanTestCase(ModuleTestCase, CompanyTestMixin):
    'Test Stock Plan module'
    module = 'stock_plan'

del ModuleTestCase
