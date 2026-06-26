from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from kardex.models import Auditoria, Documento, DocumentoDetalle, MovimientoKardex


class KardexError(Exception):
    pass


@transaction.atomic
def registrar_stock_inicial(producto, fecha, cantidad, costo_unitario, observacion='', user=None):
    producto = producto.__class__.objects.select_for_update().get(pk=producto.pk)
    if MovimientoKardex.objects.filter(producto=producto).exists():
        raise KardexError('El producto ya tiene movimientos. Usa un ajuste de Kardex, no stock inicial.')
    if cantidad < 0:
        raise KardexError('La cantidad inicial no puede ser negativa.')
    if costo_unitario < 0:
        raise KardexError('El costo unitario inicial no puede ser negativo.')

    costo_total = _money(cantidad * costo_unitario)
    promedio = _unit(costo_unitario) if cantidad else Decimal('0')
    movimiento = MovimientoKardex.objects.create(
        fecha=fecha,
        producto=producto,
        tipo_movimiento=MovimientoKardex.AJUSTE_ENTRADA,
        cantidad_entrada=cantidad,
        costo_unitario_entrada=promedio,
        costo_total_entrada=costo_total,
        stock_cantidad=cantidad,
        stock_costo_unitario_promedio=promedio,
        stock_costo_total=costo_total,
        observacion=observacion or 'Stock inicial.',
        usuario_creacion=user if getattr(user, 'is_authenticated', False) else None,
    )
    Auditoria.objects.create(
        usuario=user if getattr(user, 'is_authenticated', False) else None,
        accion='stock_inicial',
        modelo_afectado='MovimientoKardex',
        registro_id=str(movimiento.id),
        descripcion=f'Stock inicial de {producto}: {cantidad} a {promedio}.',
    )
    return movimiento


@transaction.atomic
def editar_stock_inicial(movimiento, fecha, cantidad, costo_unitario, observacion='', user=None):
    movimiento = MovimientoKardex.objects.select_for_update().select_related('producto').get(pk=movimiento.pk)
    if not _es_stock_inicial(movimiento):
        raise KardexError('Este movimiento no corresponde a un stock inicial editable.')
    if MovimientoKardex.objects.filter(producto=movimiento.producto).exclude(pk=movimiento.pk).exists():
        raise KardexError('No se puede editar: el producto ya tiene movimientos posteriores.')
    if cantidad < 0:
        raise KardexError('La cantidad inicial no puede ser negativa.')
    if costo_unitario < 0:
        raise KardexError('El costo unitario inicial no puede ser negativo.')

    costo_total = _money(cantidad * costo_unitario)
    promedio = _unit(costo_unitario) if cantidad else Decimal('0')
    movimiento.fecha = fecha
    movimiento.cantidad_entrada = cantidad
    movimiento.costo_unitario_entrada = promedio
    movimiento.costo_total_entrada = costo_total
    movimiento.cantidad_salida = Decimal('0')
    movimiento.costo_unitario_salida = Decimal('0')
    movimiento.costo_total_salida = Decimal('0')
    movimiento.stock_cantidad = cantidad
    movimiento.stock_costo_unitario_promedio = promedio
    movimiento.stock_costo_total = costo_total
    movimiento.observacion = observacion or 'Stock inicial.'
    movimiento.save(
        update_fields=[
            'fecha',
            'cantidad_entrada',
            'costo_unitario_entrada',
            'costo_total_entrada',
            'cantidad_salida',
            'costo_unitario_salida',
            'costo_total_salida',
            'stock_cantidad',
            'stock_costo_unitario_promedio',
            'stock_costo_total',
            'observacion',
        ]
    )

    Auditoria.objects.create(
        usuario=user if getattr(user, 'is_authenticated', False) else None,
        accion='edicion_stock_inicial',
        modelo_afectado='MovimientoKardex',
        registro_id=str(movimiento.id),
        descripcion=f'Editado stock inicial de {movimiento.producto}: {cantidad} a {promedio}.',
    )
    return movimiento


@transaction.atomic
def confirmar_documento_kardex(documento, user=None):
    documento = Documento.objects.select_for_update().get(pk=documento.pk)

    if documento.estado == Documento.CONFIRMADO:
        raise KardexError('El documento ya esta confirmado.')
    if documento.estado != Documento.PRE_KARDEX:
        raise KardexError('El documento debe estar en estado Pre-Kardex para confirmarse.')
    if MovimientoKardex.objects.filter(documento_origen=documento).exists():
        raise KardexError('El documento ya tiene movimientos de Kardex generados.')
    if documento.detalles.filter(estado_clasificacion=DocumentoDetalle.PENDIENTE).exists():
        raise KardexError('El documento aun tiene detalles pendientes de clasificacion.')

    movimientos = []
    detalles = documento.detalles.select_related('producto').filter(afecta_kardex=True).order_by('id')
    producto_ids = {detalle.producto_id for detalle in detalles if detalle.producto_id}
    for detalle in detalles:
        if not detalle.producto:
            continue

        tipo = _tipo_movimiento(documento)
        if tipo in [MovimientoKardex.ENTRADA, MovimientoKardex.AJUSTE_ENTRADA]:
            movimiento = _crear_movimiento_entrada(documento, detalle, tipo, user=user)
        elif tipo in [MovimientoKardex.SALIDA, MovimientoKardex.AJUSTE_SALIDA]:
            movimiento = _crear_movimiento_salida(documento, detalle, tipo, user=user)
        else:
            raise KardexError(f'Tipo de operacion no soportado para Kardex: {documento.tipo_operacion}.')
        movimientos.append(movimiento)

    _recalcular_saldos_productos_desde(producto_ids, documento.fecha_emision)

    documento.estado = Documento.CONFIRMADO
    documento.save(update_fields=['estado', 'fecha_actualizacion'])

    Auditoria.objects.create(
        usuario=user if getattr(user, 'is_authenticated', False) else None,
        accion='confirmacion_kardex',
        modelo_afectado='Documento',
        registro_id=str(documento.id),
        descripcion=f'Confirmado Kardex de {documento} con {len(movimientos)} movimiento(s).',
    )

    return movimientos

@transaction.atomic
def confirmar_documentos_kardex(documento_ids, user=None):
    ids = [int(documento_id) for documento_id in documento_ids]
    if not ids:
        raise KardexError('Selecciona al menos un documento para aprobar.')

    documentos = list(
        Documento.objects.select_for_update().filter(id__in=ids).order_by('fecha_emision', 'id')
    )
    if len(documentos) != len(set(ids)):
        raise KardexError('Uno o mas documentos seleccionados no existen.')

    movimientos = []
    for documento in documentos:
        movimientos.extend(confirmar_documento_kardex(documento, user=user))

    Auditoria.objects.create(
        usuario=user if getattr(user, 'is_authenticated', False) else None,
        accion='confirmacion_kardex_bloque',
        modelo_afectado='Documento',
        registro_id=','.join(str(documento.id) for documento in documentos),
        descripcion=f'Aprobados {len(documentos)} documento(s) Pre-Kardex con {len(movimientos)} movimiento(s).',
    )
    return movimientos


@transaction.atomic
def revertir_pre_kardex(documento, user=None):
    documento = Documento.objects.select_for_update().get(pk=documento.pk)
    if documento.estado != Documento.PRE_KARDEX:
        raise KardexError('Solo se puede revertir un documento en estado Pre-Kardex.')
    if MovimientoKardex.objects.filter(documento_origen=documento).exists():
        raise KardexError('El documento ya tiene movimientos de Kardex. Revierte primero la aprobacion.')

    _limpiar_clasificacion_documento(documento)

    Auditoria.objects.create(
        usuario=user if getattr(user, 'is_authenticated', False) else None,
        accion='reversion_pre_kardex',
        modelo_afectado='Documento',
        registro_id=str(documento.id),
        descripcion=f'Revertido Pre-Kardex de {documento}; detalles devueltos a pendiente.',
    )
    return documento


@transaction.atomic
def devolver_documento_a_pendiente(documento, user=None):
    documento = Documento.objects.select_for_update().get(pk=documento.pk)
    if documento.estado == Documento.ANULADO:
        raise KardexError('No se puede devolver a pendiente un documento anulado.')

    producto_ids = set()
    movimientos_eliminados = 0
    if documento.estado == Documento.CONFIRMADO:
        movimientos = list(
            MovimientoKardex.objects.select_for_update()
            .filter(documento_origen=documento)
            .select_related('producto')
        )
        producto_ids = {movimiento.producto_id for movimiento in movimientos if movimiento.producto_id}
        movimientos_eliminados = len(movimientos)
        if movimientos:
            MovimientoKardex.objects.filter(id__in=[movimiento.id for movimiento in movimientos]).delete()
            _recalcular_saldos_productos_desde(producto_ids, documento.fecha_emision)
    elif documento.estado == Documento.PRE_KARDEX:
        if MovimientoKardex.objects.filter(documento_origen=documento).exists():
            raise KardexError('El documento tiene movimientos de Kardex. Revisa la aprobacion antes de continuar.')
    elif documento.estado == Documento.PENDIENTE_CLASIFICACION:
        return documento

    _limpiar_clasificacion_documento(documento)

    Auditoria.objects.create(
        usuario=user if getattr(user, 'is_authenticated', False) else None,
        accion='devolucion_documento_pendiente',
        modelo_afectado='Documento',
        registro_id=str(documento.id),
        descripcion=(
            f'Documento {documento} devuelto a pendiente; '
            f'eliminados {movimientos_eliminados} movimiento(s) de Kardex.'
        ),
    )
    return documento


@transaction.atomic
def revertir_aprobacion_kardex(documento, user=None):
    documento = Documento.objects.select_for_update().get(pk=documento.pk)
    if documento.estado != Documento.CONFIRMADO:
        raise KardexError('Solo se puede revertir un documento confirmado.')

    movimientos = list(
        MovimientoKardex.objects.select_for_update()
        .filter(documento_origen=documento)
        .select_related('producto')
        .order_by('-fecha', '-id')
    )
    for movimiento in movimientos:
        posteriores = MovimientoKardex.objects.filter(producto=movimiento.producto).filter(
            Q(fecha__gt=movimiento.fecha) | Q(fecha=movimiento.fecha, id__gt=movimiento.id)
        ).exclude(documento_origen=documento)
        if posteriores.exists():
            raise KardexError(
                f'No se puede revertir la aprobacion: {movimiento.producto} tiene movimientos posteriores.'
            )

    movimiento_ids = [movimiento.id for movimiento in movimientos]
    if movimiento_ids:
        MovimientoKardex.objects.filter(id__in=movimiento_ids).delete()

    documento.estado = Documento.PRE_KARDEX
    documento.save(update_fields=['estado', 'fecha_actualizacion'])

    Auditoria.objects.create(
        usuario=user if getattr(user, 'is_authenticated', False) else None,
        accion='reversion_aprobacion_kardex',
        modelo_afectado='Documento',
        registro_id=str(documento.id),
        descripcion=f'Revertida aprobacion de {documento}; eliminados {len(movimientos)} movimiento(s).',
    )
    return documento


def _limpiar_clasificacion_documento(documento):
    DocumentoDetalle.objects.select_for_update().filter(documento=documento).update(
        producto=None,
        factor_conversion=Decimal('1'),
        cantidad_base=Decimal('0'),
        afecta_kardex=False,
        estado_clasificacion=DocumentoDetalle.PENDIENTE,
        fecha_actualizacion=timezone.now(),
    )
    documento.estado = Documento.PENDIENTE_CLASIFICACION
    documento.save(update_fields=['estado', 'fecha_actualizacion'])

def _crear_movimiento_entrada(documento, detalle, tipo, user=None):
    stock = _stock_a_fecha(detalle.producto, documento.fecha_emision)
    cantidad = _cantidad_base(detalle)
    costo_total_entrada = _money(_costo_total_entrada(detalle))
    costo_unitario_entrada = _unit(costo_total_entrada / cantidad) if cantidad else Decimal('0')

    nuevo_stock_cantidad = stock['cantidad'] + cantidad
    nuevo_stock_costo_total = _money(stock['costo_total'] + costo_total_entrada)
    nuevo_promedio = _unit(nuevo_stock_costo_total / nuevo_stock_cantidad) if nuevo_stock_cantidad else Decimal('0')

    return MovimientoKardex.objects.create(
        fecha=documento.fecha_emision,
        producto=detalle.producto,
        documento_origen=documento,
        entidad=_entidad_operacion(documento),
        tipo_movimiento=tipo,
        cantidad_entrada=cantidad,
        costo_unitario_entrada=costo_unitario_entrada,
        costo_total_entrada=costo_total_entrada,
        stock_cantidad=nuevo_stock_cantidad,
        stock_costo_unitario_promedio=nuevo_promedio,
        stock_costo_total=nuevo_stock_costo_total,
        observacion=f'Confirmado desde {documento}.',
        usuario_creacion=user if getattr(user, 'is_authenticated', False) else None,
    )


def _crear_movimiento_salida(documento, detalle, tipo, user=None):
    stock = _stock_a_fecha(detalle.producto, documento.fecha_emision)
    cantidad = _cantidad_base(detalle)
    if cantidad > stock['cantidad']:
        raise KardexError(
            f'Stock insuficiente para {detalle.producto}. '
            f'Solicitado: {cantidad}; disponible: {stock["cantidad"]}.'
        )

    costo_unitario_salida = stock['promedio']
    costo_total_salida = _money(cantidad * costo_unitario_salida)
    nuevo_stock_cantidad = stock['cantidad'] - cantidad
    nuevo_stock_costo_total = _money(stock['costo_total'] - costo_total_salida)
    nuevo_promedio = _unit(nuevo_stock_costo_total / nuevo_stock_cantidad) if nuevo_stock_cantidad else Decimal('0')

    return MovimientoKardex.objects.create(
        fecha=documento.fecha_emision,
        producto=detalle.producto,
        documento_origen=documento,
        entidad=_entidad_operacion(documento),
        tipo_movimiento=tipo,
        cantidad_salida=cantidad,
        costo_unitario_salida=costo_unitario_salida,
        costo_total_salida=costo_total_salida,
        stock_cantidad=nuevo_stock_cantidad,
        stock_costo_unitario_promedio=nuevo_promedio,
        stock_costo_total=nuevo_stock_costo_total,
        observacion=f'Confirmado desde {documento}.',
        usuario_creacion=user if getattr(user, 'is_authenticated', False) else None,
    )


def _stock_actual(producto):
    ultimo = MovimientoKardex.objects.filter(producto=producto).order_by('-fecha', '-id').first()
    if not ultimo:
        return {
            'cantidad': Decimal('0'),
            'promedio': Decimal('0'),
            'costo_total': Decimal('0'),
        }
    return {
        'cantidad': ultimo.stock_cantidad,
        'promedio': ultimo.stock_costo_unitario_promedio,
        'costo_total': ultimo.stock_costo_total,
    }


def _stock_a_fecha(producto, fecha):
    ultimo = MovimientoKardex.objects.filter(producto=producto, fecha__lte=fecha).order_by('-fecha', '-id').first()
    if not ultimo:
        return {
            'cantidad': Decimal('0'),
            'promedio': Decimal('0'),
            'costo_total': Decimal('0'),
        }
    return {
        'cantidad': ultimo.stock_cantidad,
        'promedio': ultimo.stock_costo_unitario_promedio,
        'costo_total': ultimo.stock_costo_total,
    }


def _recalcular_saldos_productos_desde(producto_ids, fecha):
    for producto_id in set(producto_ids):
        _recalcular_saldos_producto_desde(producto_id, fecha)


def _recalcular_saldos_producto_desde(producto_id, fecha):
    anterior = (
        MovimientoKardex.objects.filter(producto_id=producto_id, fecha__lt=fecha)
        .order_by('-fecha', '-id')
        .first()
    )
    stock_cantidad = anterior.stock_cantidad if anterior else Decimal('0')
    stock_costo_total = anterior.stock_costo_total if anterior else Decimal('0')
    stock_promedio = anterior.stock_costo_unitario_promedio if anterior else Decimal('0')

    movimientos = (
        MovimientoKardex.objects.select_for_update()
        .filter(producto_id=producto_id, fecha__gte=fecha)
        .order_by('fecha', 'id')
    )
    for movimiento in movimientos:
        if movimiento.cantidad_entrada:
            costo_total_entrada = _money(movimiento.costo_total_entrada)
            costo_unitario_entrada = (
                _unit(costo_total_entrada / movimiento.cantidad_entrada)
                if movimiento.cantidad_entrada
                else Decimal('0')
            )
            stock_cantidad += movimiento.cantidad_entrada
            stock_costo_total = _money(stock_costo_total + costo_total_entrada)
            stock_promedio = _unit(stock_costo_total / stock_cantidad) if stock_cantidad else Decimal('0')
            movimiento.costo_unitario_entrada = costo_unitario_entrada
            movimiento.costo_total_entrada = costo_total_entrada

        if movimiento.cantidad_salida:
            if movimiento.cantidad_salida > stock_cantidad:
                raise KardexError(
                    f'Stock insuficiente al recalcular {movimiento.producto} '
                    f'en movimiento {movimiento.id}.'
                )
            costo_unitario_salida = stock_promedio
            costo_total_salida = _money(movimiento.cantidad_salida * costo_unitario_salida)
            stock_cantidad -= movimiento.cantidad_salida
            stock_costo_total = _money(stock_costo_total - costo_total_salida)
            if stock_cantidad:
                stock_promedio = _unit(stock_costo_total / stock_cantidad)
            else:
                stock_costo_total = Decimal('0')
                stock_promedio = Decimal('0')
            movimiento.costo_unitario_salida = costo_unitario_salida
            movimiento.costo_total_salida = costo_total_salida

        movimiento.stock_cantidad = stock_cantidad
        movimiento.stock_costo_unitario_promedio = stock_promedio
        movimiento.stock_costo_total = stock_costo_total
        movimiento.save(
            update_fields=[
                'costo_unitario_entrada',
                'costo_total_entrada',
                'costo_unitario_salida',
                'costo_total_salida',
                'stock_cantidad',
                'stock_costo_unitario_promedio',
                'stock_costo_total',
            ]
        )


def _costo_total_entrada(detalle):
    if detalle.subtotal:
        return detalle.subtotal
    if detalle.cantidad_base and detalle.valor_unitario:
        return detalle.cantidad_base * detalle.valor_unitario
    return Decimal('0')


def _cantidad_base(detalle):
    if detalle.cantidad_base:
        return detalle.cantidad_base
    return detalle.cantidad * detalle.factor_conversion


def _tipo_movimiento(documento):
    if documento.tipo_operacion_efectiva in [Documento.COMPRA, Documento.LIQUIDACION_COMPRA_OP]:
        return MovimientoKardex.ENTRADA
    if documento.tipo_operacion_efectiva == Documento.VENTA:
        return MovimientoKardex.SALIDA
    if documento.tipo_operacion_efectiva == Documento.NOTA_CREDITO_COMPRA:
        return MovimientoKardex.AJUSTE_SALIDA
    if documento.tipo_operacion_efectiva == Documento.NOTA_CREDITO_VENTA:
        return MovimientoKardex.AJUSTE_ENTRADA
    return None


def _entidad_operacion(documento):
    return documento.proveedor or documento.cliente or documento.entidad_emisor


def _validar_sin_movimientos_posteriores(documento, detalles):
    producto_ids = {detalle.producto_id for detalle in detalles if detalle.producto_id}
    if not producto_ids:
        return
    posterior = (
        MovimientoKardex.objects.filter(producto_id__in=producto_ids, fecha__gt=documento.fecha_emision)
        .select_related('producto')
        .order_by('fecha', 'id')
        .first()
    )
    if posterior:
        raise KardexError(
            f'No se puede confirmar el documento con fecha {documento.fecha_emision}: '
            f'{posterior.producto} tiene movimientos posteriores.'
        )


def _money(value):
    return Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _unit(value):
    return Decimal(value).quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP)


def _es_stock_inicial(movimiento):
    return (
        movimiento.tipo_movimiento == MovimientoKardex.AJUSTE_ENTRADA
        and movimiento.documento_origen_id is None
        and movimiento.cantidad_salida == 0
    )
