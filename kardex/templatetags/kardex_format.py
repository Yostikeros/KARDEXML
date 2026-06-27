from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django import template


register = template.Library()


@register.filter
def numero(value):
    return _formato_decimal(value, 2)


@register.filter
def numero_6(value):
    return _formato_decimal(value, 6)


@register.filter
def usd(value):
    return f'USD {_formato_decimal(value, 2)}'


@register.filter
def usd_6(value):
    return f'USD {_formato_decimal(value, 6)}'


@register.filter
def soles(value):
    return f'S/ {_formato_decimal(value, 2)}'


@register.filter
def soles_6(value):
    return f'S/ {_formato_decimal(value, 6)}'


def _formato_decimal(value, decimal_places):
    if value is None or value == '':
        value = Decimal('0')
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return value
    quantizer = Decimal(1).scaleb(-decimal_places)
    return f'{decimal_value.quantize(quantizer, rounding=ROUND_HALF_UP):,.{decimal_places}f}'


@register.filter
def fecha_corta(value):
    if not value:
        return ''
    try:
        return value.strftime('%d/%m/%Y')
    except AttributeError:
        return value
