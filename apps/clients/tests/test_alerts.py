from datetime import date
from decimal import Decimal
from types import SimpleNamespace as NS

from django.test import SimpleTestCase

from apps.clients.alerts import invoice_alert, vaccine_alerts, weight_alert

TODAY = date(2026, 10, 31)


class VaccineAlertsTest(SimpleTestCase):
    def test_repeated_vaccine_old_record_does_not_alarm(self):
        # торішнє щеплення прострочене, але його вже повторили — тривоги нема
        vs = [NS(name='Nobivac DHPPi', date=date(2025, 9, 1), next_date=date(2026, 9, 1)),
              NS(name='nobivac dhppi ', date=date(2026, 9, 5), next_date=date(2027, 9, 5))]
        self.assertEqual(vaccine_alerts(vs, TODAY), [])

    def test_overdue_latest_is_danger(self):
        vs = [NS(name='Сказ', date=date(2025, 10, 1), next_date=date(2026, 10, 1))]
        a = vaccine_alerts(vs, TODAY)
        self.assertEqual([x['level'] for x in a], ['danger'])
        self.assertIn('01.10.2026', a[0]['text'])

    def test_due_soon_is_warning_and_far_is_silent(self):
        vs = [NS(name='A', date=date(2025, 11, 20), next_date=date(2026, 11, 20)),
              NS(name='B', date=date(2026, 6, 1), next_date=date(2027, 6, 1)),
              NS(name='C', date=date(2026, 6, 1), next_date=None)]
        self.assertEqual([x['level'] for x in vaccine_alerts(vs, TODAY)], ['warning'])


class WeightAlertTest(SimpleTestCase):
    def test_thresholds(self):
        w = lambda *kg: [NS(weight=Decimal(str(x))) for x in kg]
        self.assertIsNone(weight_alert(w(4.0)))
        self.assertIsNone(weight_alert(w(4.0, 4.5)))                       # 12,5% — тихо
        self.assertEqual(weight_alert(w(4.0, 4.8))['level'], 'warning')    # 20%
        self.assertEqual(weight_alert(w(4.0, 3.0))['level'], 'danger')     # −25%
        self.assertIn('4 → 3 кг', weight_alert(w(4.0, 3.0))['text'])


class InvoiceAlertTest(SimpleTestCase):
    def test_only_drafts(self):
        invs = [NS(pk=1, status='paid', total=Decimal('100')), NS(pk=2, status='draft', total=Decimal('250.5'))]
        a = invoice_alert(invs)
        self.assertEqual(a['pk'], 2)
        self.assertIn('250,5', a['text'])
        self.assertIsNone(invoice_alert(invs[:1]))
