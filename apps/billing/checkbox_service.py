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

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_goods(self, invoice) -> list:
        goods = []
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

            if line.discount and line.discount > 0:
                if line.discount_type == 'percent':
                    discount_value = round(float(line.total) * float(line.discount) / 100 * 100)
                else:
                    discount_value = round(float(line.discount) * 100)
                item['discounts'] = [{'type': 'DISCOUNT', 'mode': 'VALUE', 'value': discount_value}]

            goods.append(item)
        return goods
