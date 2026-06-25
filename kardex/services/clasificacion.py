from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction

from kardex.models import Auditoria, Documento, DocumentoDetalle, MovimientoKardex, ProductoEquivalencia


@transaction.atomic
def clasificar_detalle(
    detalle,
    producto,
    factor_conversion=Decimal("1"),
    guardar_equivalencia=True,
    equivalencia_global=False,
    user=None,
):
    if detalle.documento.estado == Documento.CONFIRMADO:
        raise ValueError("No se puede clasificar un documento confirmado.")

    factor = Decimal(factor_conversion)
    detalle.producto = producto
    detalle.factor_conversion = factor
    detalle.cantidad_base = detalle.cantidad * factor
    detalle.afecta_kardex = producto.afecta_kardex
    detalle.estado_clasificacion = (
        DocumentoDetalle.CLASIFICADO if producto.afecta_kardex else DocumentoDetalle.NO_APLICA
    )
    detalle.save(
        update_fields=[
            "producto",
            "factor_conversion",
            "cantidad_base",
            "afecta_kardex",
            "estado_clasificacion",
            "fecha_actualizacion",
        ]
    )

    if guardar_equivalencia:
        entidad = None if equivalencia_global else _entidad_operacion(detalle.documento)
        ProductoEquivalencia.objects.update_or_create(
            entidad=entidad,
            codigo_producto_xml=detalle.codigo_producto_xml,
            descripcion_xml=detalle.descripcion_xml,
            unidad_medida_xml=detalle.unidad_medida_xml,
            defaults={
                "producto": producto,
                "factor_conversion": factor,
                "activo": True,
            },
        )

    actualizar_estado_documento(detalle.documento)
    Auditoria.objects.create(
        usuario=user if getattr(user, "is_authenticated", False) else None,
        accion="clasificacion_producto",
        modelo_afectado="DocumentoDetalle",
        registro_id=str(detalle.id),
        descripcion=f"Clasificado detalle {detalle.id} como {producto}.",
    )
    return detalle


@transaction.atomic
def clasificar_documentos_bloque(
    documento_ids,
    producto,
    factor_conversion=Decimal("1"),
    guardar_equivalencia=True,
    equivalencia_global=False,
    user=None,
):
    ids = [int(documento_id) for documento_id in documento_ids]
    if not ids:
        raise ValueError("Selecciona al menos un documento para clasificar.")

    documentos = list(Documento.objects.select_for_update().filter(id__in=ids).order_by("id"))
    if len(documentos) != len(set(ids)):
        raise ValueError("Uno o mas documentos seleccionados no existen.")

    clasificados = []
    for documento in documentos:
        detalle_ids = list(
            documento.detalles.filter(estado_clasificacion=DocumentoDetalle.PENDIENTE)
            .values_list("id", flat=True)
        )
        if not detalle_ids:
            continue
        clasificados.extend(
            clasificar_detalles_bloque(
                documento,
                detalle_ids,
                producto,
                factor_conversion,
                guardar_equivalencia,
                equivalencia_global,
                user,
            )
        )

    Auditoria.objects.create(
        usuario=user if getattr(user, "is_authenticated", False) else None,
        accion="clasificacion_documentos_bloque",
        modelo_afectado="Documento",
        registro_id=",".join(str(documento.id) for documento in documentos),
        descripcion=f"Clasificados {len(clasificados)} detalle(s) en {len(documentos)} documento(s) como {producto}.",
    )
    return clasificados


@transaction.atomic
def clasificar_detalles_bloque(
    documento,
    detalle_ids,
    producto,
    factor_conversion=Decimal("1"),
    guardar_equivalencia=True,
    equivalencia_global=False,
    user=None,
):
    if documento.estado == Documento.CONFIRMADO:
        raise ValueError("No se puede clasificar un documento confirmado.")

    ids = [int(detalle_id) for detalle_id in detalle_ids]
    if not ids:
        raise ValueError("Selecciona al menos un detalle para clasificar.")

    detalles = list(
        DocumentoDetalle.objects.select_for_update()
        .filter(documento=documento, id__in=ids)
        .order_by("id")
    )
    if len(detalles) != len(set(ids)):
        raise ValueError("Uno o mas detalles seleccionados no existen o no pertenecen al documento.")

    clasificados = []
    for detalle in detalles:
        clasificados.append(
            clasificar_detalle(
                detalle,
                producto,
                factor_conversion,
                guardar_equivalencia,
                equivalencia_global,
                user,
            )
        )

    Auditoria.objects.create(
        usuario=user if getattr(user, "is_authenticated", False) else None,
        accion="clasificacion_detalles_bloque",
        modelo_afectado="Documento",
        registro_id=str(documento.id),
        descripcion=f"Clasificados {len(clasificados)} detalle(s) del documento {documento} como {producto}.",
    )
    return clasificados


@transaction.atomic
def excluir_detalle_kardex(detalle, user=None):
    if detalle.documento.estado == Documento.CONFIRMADO:
        raise ValueError("No se puede modificar un documento confirmado.")

    detalle.producto = None
    detalle.factor_conversion = Decimal("1")
    detalle.cantidad_base = Decimal("0")
    detalle.afecta_kardex = False
    detalle.estado_clasificacion = DocumentoDetalle.NO_APLICA
    detalle.save(
        update_fields=[
            "producto",
            "factor_conversion",
            "cantidad_base",
            "afecta_kardex",
            "estado_clasificacion",
            "fecha_actualizacion",
        ]
    )

    actualizar_estado_documento(detalle.documento)
    Auditoria.objects.create(
        usuario=user if getattr(user, "is_authenticated", False) else None,
        accion="exclusion_kardex",
        modelo_afectado="DocumentoDetalle",
        registro_id=str(detalle.id),
        descripcion=f"Detalle {detalle.id} excluido del Kardex: {detalle.descripcion_xml}.",
    )
    return detalle


def actualizar_estado_documento(documento):
    pendientes = documento.detalles.filter(
        estado_clasificacion=DocumentoDetalle.PENDIENTE
    ).exists()
    nuevo_estado = Documento.PENDIENTE_CLASIFICACION if pendientes else Documento.PRE_KARDEX
    if documento.estado != nuevo_estado:
        documento.estado = nuevo_estado
        documento.save(update_fields=["estado", "fecha_actualizacion"])
    return documento


@dataclass
class PreKardexItem:
    documento: Documento
    detalle: DocumentoDetalle
    fecha: object
    entidad: object
    producto: object
    tipo_movimiento: str
    cantidad_xml: object
    unidad_xml: str
    factor_conversion: object
    cantidad_base: object
    costo_precio_unitario: object
    importe_total: object
    observacion: str


def generar_pre_kardex(documento):
    items = []
    for detalle in documento.detalles.select_related("producto").all():
        if detalle.estado_clasificacion == DocumentoDetalle.PENDIENTE:
            items.append(
                _item_pre_kardex(
                    documento,
                    detalle,
                    tipo_movimiento="pendiente",
                    observacion="Detalle pendiente de clasificacion.",
                )
            )
            continue

        if not detalle.afecta_kardex:
            observacion = "Item excluido manualmente del Kardex."
            if detalle.producto:
                observacion = "Producto configurado para no afectar Kardex."
            items.append(
                _item_pre_kardex(
                    documento,
                    detalle,
                    tipo_movimiento="no_aplica",
                    observacion=observacion,
                )
            )
            continue

        items.append(
            _item_pre_kardex(
                documento,
                detalle,
                tipo_movimiento=_tipo_movimiento_pre_kardex(documento),
                observacion="Listo para confirmar Kardex.",
            )
        )
    return items


def _item_pre_kardex(documento, detalle, tipo_movimiento, observacion):
    return PreKardexItem(
        documento=documento,
        detalle=detalle,
        fecha=documento.fecha_emision,
        entidad=_entidad_operacion(documento),
        producto=detalle.producto,
        tipo_movimiento=tipo_movimiento,
        cantidad_xml=detalle.cantidad,
        unidad_xml=detalle.unidad_medida_xml,
        factor_conversion=detalle.factor_conversion,
        cantidad_base=detalle.cantidad_base,
        costo_precio_unitario=detalle.valor_unitario,
        importe_total=detalle.subtotal,
        observacion=observacion,
    )


def _tipo_movimiento_pre_kardex(documento):
    if documento.tipo_operacion_efectiva in (
        Documento.COMPRA,
        Documento.LIQUIDACION_COMPRA_OP,
    ):
        return MovimientoKardex.ENTRADA
    if documento.tipo_operacion_efectiva == Documento.VENTA:
        return MovimientoKardex.SALIDA
    if documento.tipo_operacion_efectiva == Documento.NOTA_CREDITO_COMPRA:
        return MovimientoKardex.AJUSTE_SALIDA
    if documento.tipo_operacion_efectiva == Documento.NOTA_CREDITO_VENTA:
        return MovimientoKardex.AJUSTE_ENTRADA
    return MovimientoKardex.REVERSION


def _entidad_operacion(documento):
    return documento.proveedor or documento.cliente or documento.entidad_emisor
