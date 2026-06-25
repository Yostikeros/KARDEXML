import json
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Sum

from kardex.models import Documento, DocumentoDetalle, MovimientoKardex


ZERO = Decimal("0")


@dataclass
class DashboardAnalytics:
    kpis: dict
    periodos: list[str]
    compras_kg: list[float]
    ventas_kg: list[float]
    stock_final: list[float]
    precio_compra: list[float | None]
    precio_venta: list[float | None]
    margen_unitario: list[float | None]
    valor_comprado: list[float]
    valor_vendido: list[float]
    margen_total: list[float]
    resumen_productos: list[dict]
    filtros: dict
    chart_json: dict
    promedios_comparables: bool


def obtener_analisis_compras_ventas(filtros):
    movimientos = _filtrar_movimientos(filtros)
    movimientos_list = list(movimientos.order_by("fecha", "id"))
    detalle_map = _detalle_map(movimientos_list)
    producto_id = filtros.get("producto") or ""
    promedios_comparables = bool(producto_id)

    period_data = defaultdict(_metricas_base)
    period_stock = defaultdict(dict)
    product_data = defaultdict(_metricas_base)
    product_stock = {}
    product_names = {}

    for movimiento in movimientos_list:
        producto = movimiento.producto
        product_names[producto.id] = str(producto)
        periodo = movimiento.fecha.strftime("%Y-%m")
        detalle = detalle_map.get((movimiento.documento_origen_id, producto.id), {})
        detalle_valor = detalle.get("subtotal") or ZERO
        tipo_operacion = movimiento.documento_origen.tipo_operacion_efectiva if movimiento.documento_origen else None

        if tipo_operacion in [Documento.COMPRA, Documento.LIQUIDACION_COMPRA_OP] and _incluye_compra(movimiento, filtros):
            _sumar_compra(period_data[periodo], movimiento, detalle_valor)
            _sumar_compra(product_data[producto.id], movimiento, detalle_valor)
        elif tipo_operacion == Documento.VENTA and _incluye_venta(movimiento, filtros):
            _sumar_venta(period_data[periodo], movimiento, detalle_valor)
            _sumar_venta(product_data[producto.id], movimiento, detalle_valor)

        period_stock[periodo][producto.id] = movimiento.stock_cantidad
        product_stock[producto.id] = movimiento.stock_cantidad

    periodos = sorted(period_data.keys() | period_stock.keys())
    compras_kg = []
    ventas_kg = []
    stock_final = []
    precio_compra = []
    precio_venta = []
    margen_unitario = []
    valor_comprado = []
    valor_vendido = []
    margen_total = []

    for periodo in periodos:
        data = period_data[periodo]
        compras_kg.append(_float(data["compra_kg"]))
        ventas_kg.append(_float(data["venta_kg"]))
        stock_final.append(_float(sum(period_stock[periodo].values(), ZERO)))
        valor_comprado.append(_float(data["compra_valor"]))
        valor_vendido.append(_float(data["venta_valor"]))
        margen_total.append(_float(data["margen_total"]))
        if promedios_comparables:
            precio_compra.append(_float_or_none(_div(data["compra_valor"], data["compra_kg"])))
            precio_venta_periodo = _div(data["venta_valor"], data["venta_kg"])
            costo_periodo = _div(data["venta_costo"], data["venta_kg"])
            precio_venta.append(_float_or_none(precio_venta_periodo))
            margen_unitario.append(_float_or_none(precio_venta_periodo - costo_periodo if precio_venta_periodo is not None and costo_periodo is not None else None))
        else:
            precio_compra.append(None)
            precio_venta.append(None)
            margen_unitario.append(None)

    resumen_productos = []
    for producto_key, data in sorted(product_data.items(), key=lambda item: product_names.get(item[0], "")):
        precio_compra_producto = _div(data["compra_valor"], data["compra_kg"])
        precio_venta_producto = _div(data["venta_valor"], data["venta_kg"])
        costo_promedio = _div(data["venta_costo"], data["venta_kg"])
        margen_unitario_producto = (
            precio_venta_producto - costo_promedio
            if precio_venta_producto is not None and costo_promedio is not None
            else None
        )
        resumen_productos.append(
            {
                "producto": product_names.get(producto_key, ""),
                "kg_comprados": data["compra_kg"],
                "kg_vendidos": data["venta_kg"],
                "stock_final": product_stock.get(producto_key, ZERO),
                "precio_promedio_compra": precio_compra_producto,
                "precio_promedio_venta": precio_venta_producto,
                "costo_promedio_kardex": costo_promedio,
                "margen_bruto_unitario": margen_unitario_producto,
                "margen_bruto_total": data["margen_total"],
            }
        )

    totales = _sumar_metricas(product_data.values())
    kpis = {
        "kg_comprados": totales["compra_kg"],
        "kg_vendidos": totales["venta_kg"],
        "stock_final": sum(product_stock.values(), ZERO),
        "precio_promedio_compra": _div(totales["compra_valor"], totales["compra_kg"]) if promedios_comparables else None,
        "precio_promedio_venta": _div(totales["venta_valor"], totales["venta_kg"]) if promedios_comparables else None,
        "margen_bruto_unitario": _div(totales["margen_total"], totales["venta_kg"]) if promedios_comparables else None,
        "margen_bruto_total": totales["margen_total"],
    }

    chart_json = {
        "periodos": json.dumps(periodos),
        "compras_kg": json.dumps(compras_kg),
        "ventas_kg": json.dumps(ventas_kg),
        "stock_final": json.dumps(stock_final),
        "precio_compra": json.dumps(precio_compra),
        "precio_venta": json.dumps(precio_venta),
        "margen_unitario": json.dumps(margen_unitario),
        "valor_comprado": json.dumps(valor_comprado),
        "valor_vendido": json.dumps(valor_vendido),
        "margen_total": json.dumps(margen_total),
    }

    return DashboardAnalytics(
        kpis=kpis,
        periodos=periodos,
        compras_kg=compras_kg,
        ventas_kg=ventas_kg,
        stock_final=stock_final,
        precio_compra=precio_compra,
        precio_venta=precio_venta,
        margen_unitario=margen_unitario,
        valor_comprado=valor_comprado,
        valor_vendido=valor_vendido,
        margen_total=margen_total,
        resumen_productos=resumen_productos,
        filtros=filtros,
        chart_json=chart_json,
        promedios_comparables=promedios_comparables,
    )


def _filtrar_movimientos(filtros):
    qs = MovimientoKardex.objects.select_related("producto", "documento_origen", "entidad")
    if filtros.get("producto"):
        qs = qs.filter(producto_id=filtros["producto"])
    if filtros.get("categoria"):
        qs = qs.filter(producto__categoria=filtros["categoria"])
    if filtros.get("fecha_desde"):
        qs = qs.filter(fecha__gte=filtros["fecha_desde"])
    if filtros.get("fecha_hasta"):
        qs = qs.filter(fecha__lte=filtros["fecha_hasta"])
    if filtros.get("tipo_documento"):
        qs = qs.filter(documento_origen__tipo_documento=filtros["tipo_documento"])
    return qs


def _incluye_compra(movimiento, filtros):
    proveedor_id = filtros.get("proveedor")
    if proveedor_id and str(movimiento.documento_origen.proveedor_id or "") != str(proveedor_id):
        return False
    return True


def _incluye_venta(movimiento, filtros):
    cliente_id = filtros.get("cliente")
    if cliente_id and str(movimiento.documento_origen.cliente_id or "") != str(cliente_id):
        return False
    return True


def _detalle_map(movimientos):
    doc_ids = {mov.documento_origen_id for mov in movimientos if mov.documento_origen_id}
    product_ids = {mov.producto_id for mov in movimientos}
    if not doc_ids or not product_ids:
        return {}
    rows = (
        DocumentoDetalle.objects.filter(documento_id__in=doc_ids, producto_id__in=product_ids)
        .values("documento_id", "producto_id")
        .annotate(cantidad=Sum("cantidad_base"), subtotal=Sum("subtotal"))
    )
    return {
        (row["documento_id"], row["producto_id"]): {
            "cantidad": row["cantidad"] or ZERO,
            "subtotal": row["subtotal"] or ZERO,
        }
        for row in rows
    }


def _metricas_base():
    return {
        "compra_kg": ZERO,
        "venta_kg": ZERO,
        "compra_valor": ZERO,
        "venta_valor": ZERO,
        "venta_costo": ZERO,
        "margen_total": ZERO,
    }


def _sumar_compra(data, movimiento, detalle_valor):
    data["compra_kg"] += movimiento.cantidad_entrada
    data["compra_valor"] += detalle_valor or movimiento.costo_total_entrada


def _sumar_venta(data, movimiento, detalle_valor):
    data["venta_kg"] += movimiento.cantidad_salida
    data["venta_valor"] += detalle_valor
    data["venta_costo"] += movimiento.costo_total_salida
    data["margen_total"] += detalle_valor - movimiento.costo_total_salida


def _sumar_metricas(metricas):
    total = _metricas_base()
    for data in metricas:
        for key in total:
            total[key] += data[key]
    return total


def _div(numerator, denominator):
    if not denominator:
        return None
    return numerator / denominator


def _float(value):
    return float(value or ZERO)


def _float_or_none(value):
    return float(value) if value is not None else None
