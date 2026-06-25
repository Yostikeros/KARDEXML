from dataclasses import dataclass
from decimal import Decimal

from kardex.models import Documento, EmpresaPrincipal, MovimientoKardex, Producto


@dataclass
class StockActualItem:
    producto: Producto
    cantidad: Decimal
    costo_unitario_promedio: Decimal
    costo_total: Decimal

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


def obtener_movimientos_documento(documento_id=None):
    qs = MovimientoKardex.objects.select_related("producto", "documento_origen", "entidad").order_by("fecha", "id")
    if documento_id:
        qs = qs.filter(documento_origen_id=documento_id)
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
