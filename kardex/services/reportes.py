from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import models

from kardex.models import Documento, EmpresaPrincipal, MovimientoKardex, Producto


@dataclass
class StockActualItem:
    producto: Producto
    cantidad: Decimal
    costo_unitario_promedio: Decimal
    costo_total: Decimal
    ultimo_movimiento: MovimientoKardex | None = None

    @property
    def costo_promedio(self):
        return self.costo_unitario_promedio


def obtener_stock_actual():
    items = []
    productos = Producto.objects.filter(activo=True, controla_stock=True).order_by("nombre")
    for producto in productos:
        ultimo = (
            MovimientoKardex.objects.filter(producto=producto)
            .order_by("-fecha", "-id")
            .first()
        )
        if not ultimo:
            continue
        items.append(
            StockActualItem(
                producto=producto,
                cantidad=ultimo.stock_cantidad,
                costo_unitario_promedio=ultimo.stock_costo_unitario_promedio,
                costo_total=ultimo.stock_costo_total,
                ultimo_movimiento=ultimo,
            )
        )
    return items


def obtener_stock_valorizado_total():
    return sum((item.costo_total for item in obtener_stock_actual()), Decimal("0"))


def obtener_movimientos_producto(producto_id=None):
    qs = MovimientoKardex.objects.select_related("producto", "documento_origen", "entidad").order_by("fecha", "id")
    if producto_id:
        qs = qs.filter(producto_id=producto_id)
    return qs


def obtener_documentos_importados():
    return Documento.objects.select_related("entidad_emisor", "entidad_receptor", "proveedor", "cliente").order_by("-fecha_emision", "-id")


@dataclass
class DocumentoMensualItem:
    anio: int
    mes: int
    mes_nombre: str
    facturas_venta: int = 0
    facturas_compra: int = 0
    liquidaciones_compra: int = 0
    total_ventas: Decimal = Decimal("0")
    total_compras: Decimal = Decimal("0")
    total_liquidaciones: Decimal = Decimal("0")

    @property
    def total_documentos(self):
        return self.facturas_venta + self.facturas_compra + self.liquidaciones_compra

    @property
    def total_general(self):
        return self.total_ventas + self.total_compras + self.total_liquidaciones


MESES_NOMBRE = {
    1: "Enero",
    2: "Febrero",
    3: "Marzo",
    4: "Abril",
    5: "Mayo",
    6: "Junio",
    7: "Julio",
    8: "Agosto",
    9: "Septiembre",
    10: "Octubre",
    11: "Noviembre",
    12: "Diciembre",
}


def obtener_documentos_mensual(fecha_desde=None, fecha_hasta=None, tipo_operacion=None, tipo_documento=None, entidad_id=None, estado=None):
    documentos = _documentos_mensual_queryset(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        tipo_operacion=tipo_operacion,
        tipo_documento=tipo_documento,
        entidad_id=entidad_id,
        estado=estado,
    )
    agrupado = {}
    for doc in documentos:
        key = (doc.fecha_emision.year, doc.fecha_emision.month)
        item = agrupado.setdefault(key, DocumentoMensualItem(doc.fecha_emision.year, doc.fecha_emision.month, MESES_NOMBRE[doc.fecha_emision.month]))
        if _es_factura_venta(doc):
            item.facturas_venta += 1
            item.total_ventas += doc.total
        elif _es_factura_compra(doc):
            item.facturas_compra += 1
            item.total_compras += doc.total
        elif _es_liquidacion_compra(doc):
            item.liquidaciones_compra += 1
            item.total_liquidaciones += doc.total

    for key in _meses_rango(fecha_desde, fecha_hasta):
        agrupado.setdefault(key, DocumentoMensualItem(key[0], key[1], MESES_NOMBRE[key[1]]))

    return [agrupado[key] for key in sorted(agrupado)]


def obtener_documentos_mensual_detalle(anio, mes, fecha_desde=None, fecha_hasta=None, tipo_operacion=None, tipo_documento=None, entidad_id=None, estado=None):
    return _documentos_mensual_queryset(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        tipo_operacion=tipo_operacion,
        tipo_documento=tipo_documento,
        entidad_id=entidad_id,
        estado=estado,
    ).filter(fecha_emision__year=anio, fecha_emision__month=mes).prefetch_related("detalles")


def _documentos_mensual_queryset(fecha_desde=None, fecha_hasta=None, tipo_operacion=None, tipo_documento=None, entidad_id=None, estado=None):
    qs = Documento.objects.select_related("entidad_emisor", "entidad_receptor", "proveedor", "cliente").order_by("fecha_emision", "id")
    if fecha_desde:
        qs = qs.filter(fecha_emision__gte=fecha_desde)
    if fecha_hasta:
        qs = qs.filter(fecha_emision__lte=fecha_hasta)
    if tipo_operacion == Documento.COMPRA:
        qs = qs.filter(
            models.Q(tipo_operacion=Documento.COMPRA)
            | models.Q(tipo_documento=Documento.LIQUIDACION_COMPRA, tipo_operacion=Documento.OTRO)
        )
    elif tipo_operacion:
        qs = qs.filter(tipo_operacion=tipo_operacion)
    if tipo_documento:
        qs = qs.filter(tipo_documento=tipo_documento)
    if entidad_id:
        qs = qs.filter(
            models.Q(proveedor_id=entidad_id)
            | models.Q(cliente_id=entidad_id)
            | models.Q(entidad_emisor_id=entidad_id)
            | models.Q(entidad_receptor_id=entidad_id)
        )
    if estado:
        qs = qs.filter(estado=estado)
    else:
        qs = qs.exclude(estado=Documento.ANULADO)
    return qs


def _meses_rango(fecha_desde, fecha_hasta):
    if not fecha_desde or not fecha_hasta:
        return []
    current = date(fecha_desde.year, fecha_desde.month, 1)
    end = date(fecha_hasta.year, fecha_hasta.month, 1)
    keys = []
    while current <= end:
        keys.append((current.year, current.month))
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    return keys


def _es_factura_venta(documento):
    return documento.tipo_operacion_efectiva == Documento.VENTA and documento.tipo_documento == Documento.FACTURA


def _es_factura_compra(documento):
    return documento.tipo_operacion_efectiva == Documento.COMPRA and documento.tipo_documento == Documento.FACTURA


def _es_liquidacion_compra(documento):
    return documento.tipo_operacion_efectiva == Documento.COMPRA and documento.tipo_documento == Documento.LIQUIDACION_COMPRA


def entidad_documento_reporte(documento):
    return documento.proveedor or documento.cliente or documento.entidad_emisor


def obtener_movimientos_documento(
    documento_id=None,
    fecha_desde=None,
    fecha_hasta=None,
    tipo_documento=None,
    moneda=None,
    ordering=None,
):
    qs = MovimientoKardex.objects.select_related("producto", "documento_origen", "entidad").order_by("fecha", "id")
    if documento_id:
        qs = qs.filter(documento_origen_id=documento_id)
    if fecha_desde:
        qs = qs.filter(fecha__gte=fecha_desde)
    if fecha_hasta:
        qs = qs.filter(fecha__lte=fecha_hasta)
    if tipo_documento:
        qs = qs.filter(documento_origen__tipo_documento=tipo_documento)
    if moneda:
        qs = qs.filter(documento_origen__moneda=moneda)
    if ordering:
        qs = qs.order_by(*ordering)
    return qs


@dataclass
class KardexSunatRow:
    movimiento: MovimientoKardex
    tipo_documento: str
    serie: str
    numero: str
    tipo_operacion: str


def obtener_kardex_sunat_producto(producto, fecha_inicio=None, fecha_fin=None):
    qs = MovimientoKardex.objects.select_related("producto", "documento_origen", "entidad").filter(producto=producto)
    if fecha_inicio:
        qs = qs.filter(fecha__gte=fecha_inicio)
    if fecha_fin:
        qs = qs.filter(fecha__lte=fecha_fin)

    return [
        KardexSunatRow(
            movimiento=movimiento,
            tipo_documento=_tipo_documento_sunat(movimiento),
            serie=_serie_documento(movimiento),
            numero=_numero_documento(movimiento),
            tipo_operacion=_tipo_operacion_sunat(movimiento),
        )
        for movimiento in qs.order_by("fecha", "id")
    ]


def obtener_empresa_principal():
    return EmpresaPrincipal.objects.filter(activo=True).order_by("id").first()


def _tipo_documento_sunat(movimiento):
    if movimiento.documento_origen:
        return movimiento.documento_origen.tipo_documento
    return "00"


def _serie_documento(movimiento):
    if movimiento.documento_origen:
        return movimiento.documento_origen.serie
    return "-"


def _numero_documento(movimiento):
    if movimiento.documento_origen:
        return movimiento.documento_origen.numero
    return "-"


def _tipo_operacion_sunat(movimiento):
    if movimiento.documento_origen:
        tipo_operacion = movimiento.documento_origen.tipo_operacion_efectiva
        if tipo_operacion in [Documento.COMPRA, Documento.LIQUIDACION_COMPRA_OP]:
            return "02 - Compra"
        if tipo_operacion == Documento.VENTA:
            return "01 - Venta"
        if tipo_operacion == Documento.NOTA_CREDITO_COMPRA:
            return "06 - Devolucion al proveedor"
        if tipo_operacion == Documento.NOTA_CREDITO_VENTA:
            return "05 - Devolucion recibida"

    if movimiento.documento_origen_id is None and movimiento.tipo_movimiento == MovimientoKardex.AJUSTE_ENTRADA:
        return "16 - Saldo inicial"
    if movimiento.tipo_movimiento in [MovimientoKardex.AJUSTE_ENTRADA, MovimientoKardex.AJUSTE_SALIDA]:
        return "99 - Otros"
    return movimiento.get_tipo_movimiento_display()
