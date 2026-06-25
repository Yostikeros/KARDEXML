import json
import ssl
import urllib.request
from datetime import date
from decimal import Decimal

from kardex.models import TipoCambioSunat

SUNAT_URL = 'https://e-consulta.sunat.gob.pe/cl-at-ittipcam/tcS01Alias'

MESES = {
    'enero': 0,
    'febrero': 1,
    'marzo': 2,
    'abril': 3,
    'mayo': 4,
    'junio': 5,
    'julio': 6,
    'agosto': 7,
    'septiembre': 8,
    'octubre': 9,
    'noviembre': 10,
    'diciembre': 11,
}

MESES_NOMBRE = {v: k for k, v in MESES.items()}
MESES_NUMERO = {v + 1: k for k, v in MESES.items()}


def mes_a_numero(mes: str) -> int:
    mes = str(mes).strip().lower()
    if mes in MESES:
        return MESES[mes]

    n = int(mes)
    if 1 <= n <= 12:
        return n - 1

    raise ValueError('Mes invalido')


def extraer_tipo_cambio_sunat(mes: str, anio: int) -> dict:
    mes_num = mes_a_numero(mes)
    mes_nombre = MESES_NOMBRE[mes_num]

    payload = json.dumps(
        {
            'anio': str(anio),
            'mes': str(mes_num),
            'token': '1234',
        }
    ).encode('utf-8')

    req = urllib.request.Request(
        f'{SUNAT_URL}/listarTipoCambio',
        data=payload,
        headers={
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json',
            'Origin': 'https://e-consulta.sunat.gob.pe',
            'Referer': SUNAT_URL,
        },
        method='POST',
    )

    with urllib.request.urlopen(
        req,
        timeout=15,
        context=ssl.create_default_context(),
    ) as resp:
        if resp.status != 200:
            raise ConnectionError(f'SUNAT respondio con codigo {resp.status}')
        data = json.loads(resp.read().decode('utf-8'))

    por_dia = {}
    for item in data:
        fecha = item.get('fecPublica', '')
        tipo = item.get('codTipo', '')
        valor = Decimal(str(item.get('valTipo', 0)))
        dia = int(fecha.split('/')[0])

        por_dia.setdefault(dia, {})
        if tipo == 'C':
            por_dia[dia]['C'] = valor
        elif tipo == 'V':
            por_dia[dia]['V'] = valor

    exitosos = 0
    errores = 0
    for dia, valores in sorted(por_dia.items()):
        compra = valores.get('C')
        venta = valores.get('V')
        if compra is None or venta is None:
            errores += 1
            continue

        TipoCambioSunat.objects.update_or_create(
            mes=mes_nombre,
            anio=anio,
            dia=dia,
            defaults={
                'compra': compra,
                'venta': venta,
            },
        )
        exitosos += 1

    return {'exitosos': exitosos, 'errores': errores}


def obtener_tc_venta_sunat(fecha):
    if isinstance(fecha, str):
        fecha = date.fromisoformat(fecha[:10])

    mes_nombre = MESES_NUMERO[fecha.month]
    tipo_cambio = TipoCambioSunat.objects.filter(
        anio=fecha.year,
        mes=mes_nombre,
        dia=fecha.day,
    ).first()
    return tipo_cambio.venta if tipo_cambio else None