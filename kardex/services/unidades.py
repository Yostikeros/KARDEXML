import re
from decimal import Decimal, InvalidOperation

_NUM = r'(?P<value>\d+(?:[.,]\d+)?)'
_KG_RE = re.compile(rf'{_NUM}\s*(?:KG|KGM|KILOS?|KILOGRAMOS?)\b', re.IGNORECASE)
_BAGS_RE = re.compile(
    r'(?P<bags>\d+(?:[.,]\d+)?)\s*(?:BAGS?|SACOS?)\s*(?:OF|DE)?\s*'
    r'(?P<kg>\d+(?:[.,]\d+)?)\s*(?:KG|KGM|KILOS?|KILOGRAMOS?)\b',
    re.IGNORECASE,
)


def normalizar_unidad(value):
    value = (value or '').strip().upper()
    if value == 'KGM':
        return 'KG'
    if value in {'LBR', 'LB', 'LBS'}:
        return 'LBR'
    return value or 'NIU'


def inferir_cantidad_kg_descripcion(descripcion):
    descripcion = descripcion or ''
    candidates = []

    for match in _KG_RE.finditer(descripcion):
        value = _to_decimal(match.group('value'))
        if value is not None:
            candidates.append(value)

    for match in _BAGS_RE.finditer(descripcion):
        bags = _to_decimal(match.group('bags'))
        kg = _to_decimal(match.group('kg'))
        if bags is not None and kg is not None:
            candidates.append(bags * kg)

    if not candidates:
        return None
    return max(candidates)


def _to_decimal(value):
    try:
        return Decimal(str(value).replace(',', '.'))
    except (InvalidOperation, TypeError):
        return None

