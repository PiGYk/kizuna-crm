"""Вивантаження таблиць без формул (Ревізор, №870, 27.11.2026).

Excel виконує як формулу комірку CSV, що починається з = + - @ (або таба чи CR), а openpyxl сам робить формулою текст,
що починається з =. Назва, яку хтось увів як «=HYPERLINK(...)», у вивантаженні мусить лишитись текстом (OWASP «CSV
Injection»).
"""
import csv
import re

_NEBEZPECHNI = ('=', '+', '-', '@', '\t', '\r')
_CHYSLO = re.compile(r'^[+-]?\d+(?:[.,]\d+)?$')


def bezpechna_komirka(v):
    """Текст, що почався б формулою, — з апострофом спереду; числа (і «-5» рядком) — як є."""
    if isinstance(v, str) and v[:1] in _NEBEZPECHNI and not _CHYSLO.match(v):
        return "'" + v
    return v


class _Pysar:
    def __init__(self, f, **kw):
        self._w = csv.writer(f, **kw)

    def writerow(self, row):
        return self._w.writerow([bezpechna_komirka(v) for v in row])

    def writerows(self, rows):
        for row in rows:
            self.writerow(row)


def csv_writer(f, **kw):
    """Як csv.writer, але кожна комірка проходить bezpechna_komirka."""
    return _Pysar(f, **kw)
