import logging
import re
import time
from decimal import Decimal

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

CHECKBOX_API_URL = getattr(settings, 'CHECKBOX_API_URL', 'https://api.checkbox.in.ua/api/v1')


def _normalize_phone(phone: str) -> str | None:
    digits = re.sub(r'\D', '', phone)
    if digits.startswith('380') and len(digits) == 12:
        return digits
    if digits.startswith('0') and len(digits) == 10:
        return f'38{digits}'
    return None


class CheckboxService:

    def __init__(self, org):
        self.org = org
        self.token = None

    def authenticate(self):
        resp = requests.post(
            f'{CHECKBOX_API_URL}/cashier/signinPinCode',
            json={'pin_code': self.org.checkbox_pin},
            headers={'X-License-Key': self.org.checkbox_license_key},
            timeout=10,
        )
        resp.raise_for_status()
        self.token = resp.json()['access_token']

    def _headers(self):
        return {
            'Authorization': f'Bearer {self.token}',
            'X-License-Key': self.org.checkbox_license_key,
            'Content-Type': 'application/json',
        }

    def get_monobank_terminal_id(self) -> str | None:
        resp = requests.get(
            f'{CHECKBOX_API_URL}/terminals',
            headers=self._headers(),
            timeout=10,
        )
        if resp.status_code == 200:
            for t in resp.json():
                if t.get('type') == 'MONOBANK':
                    return t['id']
        return None

    # ── QR / картка ──────────────────────────────────────────────────────────

    def create_invoice(self, invoice) -> dict:
        """
        Створює Checkbox invoice → Monobank QR термінал отримує суму.
        Клієнт платить → Checkbox сам фіскалізує чек.
        Повертає {id, external_id, status, page_url}.
        """
        terminal_id = self.get_monobank_terminal_id()
        if not terminal_id:
            raise ValueError('Monobank QR термінал не знайдено в Checkbox.')

        goods = self._build_goods(invoice)
        if not goods:
            raise ValueError('Рахунок не містить позицій з ненульовою ціною.')

        payload = {
            'goods': goods,
            'terminal_id': terminal_id,
            'validity': 600,  # 10 хвилин на оплату
        }

        phone = getattr(invoice.client, 'phone', '')
        normalized = _normalize_phone(phone) if phone else None
        if normalized:
            payload['delivery'] = {'phone': normalized}

        resp = requests.post(
            f'{CHECKBOX_API_URL}/invoices',
            json=payload,
            headers=self._headers(),
            timeout=30,
        )
        if not resp.ok:
            logger.error('Checkbox POST /invoices %s: %s', resp.status_code, resp.text)
        resp.raise_for_status()
        return resp.json()

    def get_invoice_status(self, invoice_id: str) -> dict:
        """Повертає поточний стан Checkbox invoice."""
        resp = requests.get(
            f'{CHECKBOX_API_URL}/invoices/{invoice_id}',
            headers=self._headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def cancel_invoice(self, invoice_id: str):
        """Скасовує Checkbox invoice (якщо ще не оплачено)."""
        resp = requests.delete(
            f'{CHECKBOX_API_URL}/invoices/{invoice_id}',
            headers=self._headers(),
            timeout=10,
        )
        resp.raise_for_status()

    # ── Готівка ───────────────────────────────────────────────────────────────

    def ensure_shift_open(self):
        resp = requests.get(
            f'{CHECKBOX_API_URL}/cashier/shift',
            headers=self._headers(),
            timeout=10,
        )
        if resp.status_code == 200:
            shift = resp.json()
            if shift and shift.get('status') == 'OPENED':
                return

        resp = requests.post(
            f'{CHECKBOX_API_URL}/shifts',
            headers=self._headers(),
            timeout=30,
        )
        if resp.status_code not in (200, 201, 400):
            resp.raise_for_status()

        # Checkbox відкриває зміну асинхронно — чекаємо до 30 сек
        for _ in range(10):
            time.sleep(3)
            check = requests.get(
                f'{CHECKBOX_API_URL}/cashier/shift',
                headers=self._headers(),
                timeout=10,
            )
            if check.status_code == 200:
                shift = check.json()
                if shift and shift.get('status') == 'OPENED':
                    return
        raise RuntimeError('Checkbox: зміна не відкрилась за 30 секунд')

    def create_cash_receipt(self, invoice) -> dict:
        """Готівковий чек — підписується одразу."""
        goods = self._build_goods(invoice)
        if not goods:
            raise ValueError('Рахунок не містить позицій з ненульовою ціною.')

        total_kopecks = round(float(invoice.total) * 100)
        payload = {
            'goods': goods,
            'payments': [{'type': 'CASH', 'value': total_kopecks}],
        }

        phone = getattr(invoice.client, 'phone', '')
        normalized = _normalize_phone(phone) if phone else None
        if normalized:
            payload['delivery'] = {'phone': normalized}

        resp = requests.post(
            f'{CHECKBOX_API_URL}/receipts/sell',
            json=payload,
            headers=self._headers(),
            timeout=30,
        )
        if not resp.ok:
            logger.error('Checkbox POST /receipts/sell %s: %s', resp.status_code, resp.text)
        resp.raise_for_status()
        return resp.json()

    def close_shift(self):
        resp = requests.post(
            f'{CHECKBOX_API_URL}/shifts/close',
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()

    # ── Фіскалізація картки після оплати через Monobank QR ──────────────────

    def fiscalize_card_invoice(self, invoice, cb_invoice_data) -> dict:
        """
        Після того як Checkbox invoice отримав статус SUCCESS, треба окремо
        пробити фіскальний чек через /receipts/sell з типом CASHLESS.
        Інакше касир бачить тільки оплату на терміналі, а ДПС-чека немає.
        """
        goods = self._build_goods(invoice)
        if not goods:
            raise ValueError('Рахунок не містить позицій з ненульовою ціною.')

        amount = cb_invoice_data.get('final_amount') or cb_invoice_data.get('amount')
        if not amount:
            amount = round(float(invoice.total) * 100)

        payment = {
            'type': 'CASHLESS',
            'value': amount,
            'label': 'Безготівковий',
        }
        for src, dst in [
            ('transaction_id', 'transaction_id'),
            ('commission', 'commission'),
            ('card_mask', 'card_mask'),
            ('auth_code', 'auth_code'),
            ('rrn', 'rrn'),
            ('terminal_name', 'payment_system'),
        ]:
            v = cb_invoice_data.get(src)
            if v:
                payment[dst] = v

        payload = {
            'goods': goods,
            'payments': [payment],
            'related_invoice_id': cb_invoice_data.get('id'),
        }

        phone = getattr(invoice.client, 'phone', '')
        normalized = _normalize_phone(phone) if phone else None
        if normalized:
            payload['delivery'] = {'phone': normalized}

        self.ensure_shift_open()

        resp = requests.post(
            f'{CHECKBOX_API_URL}/receipts/sell',
            json=payload,
            headers=self._headers(),
            timeout=30,
        )
        if not resp.ok:
            logger.error('Checkbox card fiscalize %s: %s', resp.status_code, resp.text)
        resp.raise_for_status()
        return resp.json()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_goods(self, invoice) -> list:
        from decimal import Decimal

        goods = []
        line_meta = []  # (item_ref, line_total_after_line_discount_kopecks)
        for line in invoice.lines.all():
            if line.unit_price == 0:
                continue
            price_kopecks = round(float(line.unit_price) * 100)
            qty_thousandths = round(float(line.quantity) * 1000)
            line_total_kopecks = round(float(line.unit_price) * float(line.quantity) * 100)

            item = {
                'good': {
                    'code': str(line.service_id or line.product_id or line.pk),
                    'name': line.name[:128],
                    'price': price_kopecks,
                },
                'quantity': qty_thousandths,
                'price': line_total_kopecks,
            }

            line_discount_value = 0
            if line.discount and line.discount > 0:
                # discount_value — сума рядкової знижки в копійках (різниця оригіналу і факту)
                original_kopecks = round(float(line.unit_price) * float(line.quantity) * 100)
                discounted_kopecks = round(float(line.total) * 100)
                line_discount_value = max(0, original_kopecks - discounted_kopecks)
                if line_discount_value > 0:
                    item['discounts'] = [{'type': 'DISCOUNT', 'mode': 'VALUE', 'value': line_discount_value}]

            goods.append(item)
            after_line_disc = round(float(line.total) * 100)  # = (qty*price - line_discount), копійки
            line_meta.append((item, after_line_disc))

        # Знижка на весь чек (Invoice.discount) — розкидаємо пропорційно по позиціях.
        # Інакше Checkbox не знає про неї, і фіскальна сума не збігається з тим, що бачить клієнт.
        if not invoice.discount or invoice.discount <= 0 or not line_meta:
            return goods

        subtotal_kop = sum(t for _, t in line_meta)
        if subtotal_kop <= 0:
            return goods

        if invoice.discount_type == invoice.DiscountType.PERCENT:
            invoice_discount_kop = round(subtotal_kop * float(invoice.discount) / 100)
        else:
            invoice_discount_kop = round(float(invoice.discount) * 100)

        invoice_discount_kop = min(invoice_discount_kop, subtotal_kop)
        if invoice_discount_kop <= 0:
            return goods

        # Пропорційний розподіл, дрібниця округлення йде в останній рядок
        distributed = 0
        for idx, (item, line_total_kop) in enumerate(line_meta):
            if idx == len(line_meta) - 1:
                add = invoice_discount_kop - distributed
            else:
                add = round(invoice_discount_kop * line_total_kop / subtotal_kop)
                distributed += add
            if add <= 0:
                continue
            existing = item.get('discounts', [])
            existing.append({'type': 'DISCOUNT', 'mode': 'VALUE', 'value': add})
            item['discounts'] = existing

        return goods
