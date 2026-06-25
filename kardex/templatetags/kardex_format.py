from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django import template


register = template.Library()


@register.filter
def numero(value):
    if value is None or value == '':
        return '0.00'
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return value
    return f'{decimal_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP):,.2f}'


@register.filter
def fecha_corta(value):
    if not value:
        return ''
    try:
        return value.strftime('%d/%m/%Y')
    except AttributeError:
        return value
