import re
from decimal import Decimal, InvalidOperation

FACTOR_LIBRA_A_KG = Decimal('0.453592')
TOLERANCIA_REDONDEO_KG = Decimal('0.0001')

_NUM = r'(?P<value>\d+(?:[.,]\d+)?)'
_KG_RE = re.compile(rf'{_NUM}\s*(?:KG|KGM|KILOS?|KILOGRAMOS?)\b', re.IGNORECASE)
_BAGS_RE = re.compile(
    r'(?P<bags>\d+(?:[.,]\d+)?)\s*(?:BAGS?|SACOS?)\s*(?:OF|DE)?\s*'
    r'(?P<kg>\d+(?:[.,]\d+)?)\s*(?:KG|KGM|KILOS?|KILOGRAMOS?)\b',
    re.IGNORECASE,
)
_QQ_KG_RE = re.compile(
    r'\b(?:QQ|QQL|QUINTALES?)\s*/?\s*(?:DE\s*)?(?P<kg>\d+(?:[.,]\d+)?)\s*'
    r'(?:KG|KGM|KILOS?|KILOGRAMOS?)\b',
    re.IGNORECASE,
)


def normalizar_unidad(value):
    value = (value or '').strip().upper()
    if value == 'KGM':
        return 'KG'
    if value in {'LBR', 'LB', 'LBS'}:
        return 'LBR'
    return value or 'NIU'


def resolver_factor_conversion(unidad_xml, unidad_destino, factor_conversion=None, descripcion=None):
    factor = Decimal(str(factor_conversion if factor_conversion is not None else '1'))
    unidad_xml = normalizar_unidad(unidad_xml)
    unidad_destino = normalizar_unidad(unidad_destino)
    if unidad_xml == 'LBR' and unidad_destino == 'KG' and factor == Decimal('1'):
        return FACTOR_LIBRA_A_KG
    if unidad_xml in {'NIU', 'UND'} and unidad_destino == 'KG' and factor == Decimal('1'):
        factor_quintal = inferir_factor_quintal_kg(descripcion)
        if factor_quintal:
            return factor_quintal
    return factor


def inferir_factor_quintal_kg(descripcion):
    match = _QQ_KG_RE.search(descripcion or '')
    if not match:
        return None
    return _to_decimal(match.group('kg'))


def inferir_cantidad_quintal_kg(descripcion, cantidad):
    factor = inferir_factor_quintal_kg(descripcion)
    if not factor:
        return None
    try:
        return normalizar_cantidad_kg(Decimal(cantidad) * factor)
    except (InvalidOperation, TypeError):
        return None


def normalizar_cantidad_kg(cantidad):
    cantidad = Decimal(cantidad)
    entero = cantidad.quantize(Decimal('1'))
    if abs(cantidad - entero) <= TOLERANCIA_REDONDEO_KG:
        return entero
    return cantidad


def inferir_cantidad_kg_descripcion(descripcion):
    descripcion = descripcion or ''
    candidates = []
    quintal_spans = [match.span() for match in _QQ_KG_RE.finditer(descripcion)]

    for match in _KG_RE.finditer(descripcion):
        if any(start <= match.start() < end for start, end in quintal_spans):
            continue
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

