"""WayForPay payment gateway helper."""
import hashlib
import hmac
import time

from django.conf import settings

WAYFORPAY_URL = 'https://secure.wayforpay.com/pay'
MERCHANT_DOMAIN = 'crm.kizuna.com.ua'

PLANS = {
    'start': {
        'label': 'Старт',
        'price': 990,
        'product_name': 'Kizuna CRM — Тариф Старт (1 місяць)',
    },
    'clinic': {
        'label': 'Клініка',
        'price': 1990,
        'product_name': 'Kizuna CRM — Тариф Клініка (1 місяць)',
    },
    'network': {
        'label': 'Мережа',
        'price': 3990,
        'product_name': 'Kizuna CRM — Тариф Мережа (1 місяць)',
    },
}


def _sign(data: str) -> str:
    key = settings.WAYFORPAY_SECRET.encode('utf-8')
    return hmac.new(key, data.encode('utf-8'), hashlib.md5).hexdigest()


def build_payment_fields(plan_key: str, org_id: int, return_url: str, callback_url: str) -> dict:
    plan = PLANS[plan_key]
    order_ref = f'kizuna-{org_id}-{plan_key}-{int(time.time())}'
    order_date = int(time.time())
    amount = str(plan['price'])
    currency = 'UAH'
    product_name = plan['product_name']

    sig_parts = ';'.join([
        settings.WAYFORPAY_MERCHANT,
        MERCHANT_DOMAIN,
        order_ref,
        str(order_date),
        amount,
        currency,
        product_name,
        '1',
        amount,
    ])

    return {
        'merchantAccount': settings.WAYFORPAY_MERCHANT,
        'merchantDomainName': MERCHANT_DOMAIN,
        'merchantSignature': _sign(sig_parts),
        'orderReference': order_ref,
        'orderDate': str(order_date),
        'amount': amount,
        'currency': currency,
        'productName[]': product_name,
        'productCount[]': '1',
        'productPrice[]': amount,
        'returnUrl': return_url,
        'serviceUrl': callback_url,
        'language': 'UA',
    }


def verify_callback(data: dict) -> bool:
    sig_parts = ';'.join([
        str(data.get('merchantAccount', '')),
        str(data.get('orderReference', '')),
        str(data.get('amount', '')),
        str(data.get('currency', '')),
        str(data.get('authCode', '')),
        str(data.get('cardPan', '')),
        str(data.get('transactionStatus', '')),
        str(data.get('reasonCode', '')),
    ])
    expected = _sign(sig_parts)
    received = str(data.get('merchantSignature', ''))
    return hmac.compare_digest(expected, received)


def accept_response(order_ref: str) -> dict:
    now = int(time.time())
    sig = _sign(f'{order_ref};accept;{now}')
    return {'orderReference': order_ref, 'status': 'accept', 'time': now, 'signature': sig}
