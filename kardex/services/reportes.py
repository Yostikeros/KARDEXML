from dataclasses import dataclass
from datetime import date, timedelta
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
class ReporteMensualKardexCategoria:
    compras: Decimal = Decimal("0")
    ventas: Decimal = Decimal("0")
    ajuste_positivo: Decimal = Decimal("0")
    ajuste_negativo: Decimal = Decimal("0")
    proc_salida: Decimal = Decimal("0")
    proc_ingreso: Decimal = Decimal("0")
    saldo_final: Decimal = Decimal("0")


@dataclass
class ReporteMensualKardexItem:
    numero: int
    mes: int
    mes_nombre: str
    per: ReporteMensualKardexCategoria
    exp: ReporteMensualKardexCategoria
    sub: ReporteMensualKardexCategoria


def obtener_reporte_mensual_kardex_kg(anio):
    inicio = date(anio, 1, 1)
    fin = date(anio, 12, 31)
    items = [
        ReporteMensualKardexItem(
            numero=mes,
            mes=mes,
            mes_nombre=MESES_NOMBRE[mes],
            per=ReporteMensualKardexCategoria(),
            exp=ReporteMensualKardexCategoria(),
            sub=ReporteMensualKardexCategoria(),
        )
        for mes in range(1, 13)
    ]
    movimientos = list(
        MovimientoKardex.objects.select_related("producto", "documento_origen")
        .filter(producto__controla_stock=True, fecha__lte=fin)
        .order_by("fecha", "id")
    )

    stock_por_producto = {}
    movimiento_index = 0
    for item in items:
        cierre_mes = _ultimo_dia_mes(anio, item.mes)
        while movimiento_index < len(movimientos) and movimientos[movimiento_index].fecha <= cierre_mes:
            movimiento = movimientos[movimiento_index]
            categoria_key = _categoria_reporte_mensual_producto(movimiento.producto)
            if categoria_key and movimiento.fecha >= inicio:
                _sumar_movimiento_reporte_mensual(getattr(item, categoria_key), movimiento, categoria_key)
            if categoria_key:
                stock_por_producto[movimiento.producto_id] = (categoria_key, movimiento.stock_cantidad)
            movimiento_index += 1
        for categoria_key in ["per", "exp", "sub"]:
            getattr(item, categoria_key).saldo_final = sum(
                cantidad for key, cantidad in stock_por_producto.values() if key == categoria_key
            )

    totales = ReporteMensualKardexItem(
        numero=0,
        mes=0,
        mes_nombre="TOTAL",
        per=_total_categoria_mensual([item.per for item in items]),
        exp=_total_categoria_mensual([item.exp for item in items]),
        sub=_total_categoria_mensual([item.sub for item in items]),
    )
    if items:
        totales.per.saldo_final = items[-1].per.saldo_final
        totales.exp.saldo_final = items[-1].exp.saldo_final
        totales.sub.saldo_final = items[-1].sub.saldo_final
    return items, totales


def _categoria_reporte_mensual_producto(producto):
    texto = _normalizar_texto_reporte_mensual(
        " ".join([producto.codigo_interno or "", producto.nombre or "", producto.categoria or ""])
    )
    codigo = _normalizar_texto_reporte_mensual(producto.codigo_interno or "")

    if "EXPORTABLE" in texto or codigo.startswith(("EXP", "CAFX")):
        return "exp"
    if "SUBPRODUCT" in texto or codigo.startswith(("SUB", "CASU")):
        return "sub"
    if "PERGAMINO" in texto or codigo.startswith(("PER", "CAPS")):
        return "per"

    if producto.tipo_producto == Producto.PRODUCTO_TERMINADO:
        return "exp"
    if producto.tipo_producto == Producto.SUBPRODUCTO:
        return "sub"
    if producto.tipo_producto == Producto.MATERIA_PRIMA:
        return "per"
    return None


def _normalizar_texto_reporte_mensual(value):
    replacements = {
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "Á": "A",
        "É": "E",
        "Í": "I",
        "Ó": "O",
        "Ú": "U",
    }
    for source, target in replacements.items():
        value = value.replace(source, target)
    return value.upper()


def _sumar_movimiento_reporte_mensual(categoria, movimiento, categoria_key):
    if movimiento.tipo_movimiento == MovimientoKardex.ENTRADA:
        categoria.compras += movimiento.cantidad_entrada
    elif movimiento.tipo_movimiento == MovimientoKardex.SALIDA:
        categoria.ventas += movimiento.cantidad_salida
    elif movimiento.tipo_movimiento == MovimientoKardex.AJUSTE_ENTRADA:
        categoria.ajuste_positivo += movimiento.cantidad_entrada
    elif movimiento.tipo_movimiento == MovimientoKardex.AJUSTE_SALIDA:
        categoria.ajuste_negativo += movimiento.cantidad_salida
    elif movimiento.tipo_movimiento == MovimientoKardex.PROCESO_SALIDA and categoria_key == "per":
        categoria.proc_salida += movimiento.cantidad_salida
    elif movimiento.tipo_movimiento == MovimientoKardex.PROCESO_ENTRADA and categoria_key in {"exp", "sub"}:
        categoria.proc_ingreso += movimiento.cantidad_entrada
    elif movimiento.tipo_movimiento == MovimientoKardex.REVERSION:
        categoria.ajuste_positivo += movimiento.cantidad_entrada
        categoria.ajuste_negativo += movimiento.cantidad_salida


def _total_categoria_mensual(categorias):
    return ReporteMensualKardexCategoria(
        compras=sum((categoria.compras for categoria in categorias), Decimal("0")),
        ventas=sum((categoria.ventas for categoria in categorias), Decimal("0")),
        ajuste_positivo=sum((categoria.ajuste_positivo for categoria in categorias), Decimal("0")),
        ajuste_negativo=sum((categoria.ajuste_negativo for categoria in categorias), Decimal("0")),
        proc_salida=sum((categoria.proc_salida for categoria in categorias), Decimal("0")),
        proc_ingreso=sum((categoria.proc_ingreso for categoria in categorias), Decimal("0")),
    )


def _ultimo_dia_mes(anio, mes):
    if mes == 12:
        return date(anio, 12, 31)
    return date(anio, mes + 1, 1) - timedelta(days=1)


@dataclass
class KardexSunatRow:
    movimiento: MovimientoKardex | object
    tipo_documento: str
    serie: str
    numero: str
    tipo_operacion: str


@dataclass
class KardexSunatSaldoArrastre:
    fecha: date
    cantidad_entrada: Decimal = Decimal("0")
    costo_unitario_entrada: Decimal = Decimal("0")
    costo_total_entrada: Decimal = Decimal("0")
    cantidad_salida: Decimal = Decimal("0")
    costo_unitario_salida: Decimal = Decimal("0")
    costo_total_salida: Decimal = Decimal("0")
    stock_cantidad: Decimal = Decimal("0")
    stock_costo_unitario_promedio: Decimal = Decimal("0")
    stock_costo_total: Decimal = Decimal("0")


def obtener_kardex_sunat_producto(producto, fecha_inicio=None, fecha_fin=None):
    qs = MovimientoKardex.objects.select_related("producto", "documento_origen", "entidad").filter(producto=producto)
    if fecha_inicio:
        qs = qs.filter(fecha__gte=fecha_inicio)
    if fecha_fin:
        qs = qs.filter(fecha__lte=fecha_fin)

    filas = [
        KardexSunatRow(
            movimiento=movimiento,
            tipo_documento=_tipo_documento_sunat(movimiento),
            serie=_serie_documento(movimiento),
            numero=_numero_documento(movimiento),
            tipo_operacion=_tipo_operacion_sunat(movimiento),
        )
        for movimiento in qs.order_by("fecha", "id")
    ]
    if filas:
        return filas
    if fecha_inicio:
        saldo_arrastre = _saldo_arrastre_kardex_sunat(producto, fecha_inicio)
        if saldo_arrastre:
            return [saldo_arrastre]
    return []


def _saldo_arrastre_kardex_sunat(producto, fecha_inicio):
    movimiento_anterior = (
        MovimientoKardex.objects.filter(producto=producto, fecha__lt=fecha_inicio)
        .order_by("-fecha", "-id")
        .first()
    )
    if not movimiento_anterior:
        return None

    return KardexSunatRow(
        movimiento=KardexSunatSaldoArrastre(
            fecha=fecha_inicio,
            stock_cantidad=movimiento_anterior.stock_cantidad,
            stock_costo_unitario_promedio=movimiento_anterior.stock_costo_unitario_promedio,
            stock_costo_total=movimiento_anterior.stock_costo_total,
        ),
        tipo_documento="00",
        serie="-",
        numero="-",
        tipo_operacion="16 - Saldo inicial",
    )


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
