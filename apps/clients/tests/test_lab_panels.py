from django.test import SimpleTestCase

from apps.clients.lab_panels import learn_norms, template_rows

# свій бланк клініки з показником, якого нема серед типових (Катя 22.11: білірубін прямий, MID/GRA)
TPL = {'biochemistry': {'dog': [
    {'code': 'glu', 'name': 'Глюкоза', 'unit': 'ммоль/л', 'low': '3.1', 'high': '6.5', 'group': ''},
    {'code': 'dbil', 'name': 'Білірубін прямий', 'unit': 'мкмоль/л', 'low': '0', 'high': '1.7', 'group': ''},
]}}


class LearnNormsTest(SimpleTestCase):
    def test_template_only_code_is_remembered(self):
        rows = [{'code': 'dbil', 'name': 'Білірубін прямий', 'value': '0.3', 'low': '0', 'high': '2'}]
        self.assertEqual(learn_norms(rows, 'cat', {}, TPL), {'cat': {'dbil': ['0', '2']}})

    def test_unknown_code_without_template_is_ignored(self):
        rows = [{'code': 'dbil', 'value': '0.3', 'low': '0', 'high': '2'}]
        self.assertIsNone(learn_norms(rows, 'cat', {}))

    def test_row_without_code_is_ignored(self):
        rows = [{'code': '', 'name': 'Т4', 'value': '20', 'low': '15', 'high': '50'}]
        self.assertIsNone(learn_norms(rows, 'cat', {}, TPL))

    def test_clearing_template_only_norm_forgets_it(self):
        rows = [{'code': 'dbil', 'value': '0.3', 'low': '', 'high': ''}]
        self.assertEqual(learn_norms(rows, 'dog', {'dog': {'dbil': ['0', '2']}}, TPL), {'dog': {}})


class TemplateRowsTest(SimpleTestCase):
    def test_clinic_template_order_and_norms(self):
        rows = template_rows('biochemistry', 'dog', {}, TPL)
        self.assertEqual([r['code'] for r in rows], ['glu', 'dbil'])
        self.assertEqual((rows[1]['low'], rows[1]['high']), ('0', '1.7'))

    def test_other_species_takes_layout_with_own_norms(self):
        rows = template_rows('biochemistry', 'cat', {'cat': {'glu': ['3.5', '6.3']}}, TPL)
        self.assertEqual([r['code'] for r in rows], ['glu', 'dbil'])
        self.assertEqual(tuple(rows[0][k] for k in ('low', 'high')), ('3.5', '6.3'))
        self.assertEqual(tuple(rows[1][k] for k in ('low', 'high')), ('', ''))
