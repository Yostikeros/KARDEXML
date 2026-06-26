from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from kardex.models import Auditoria, MovimientoKardex, ProcesoProductivo, ProcesoProductoObtenido
from kardex.services.kardex import KardexError


def _money(value):
    return Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _unit(value):
    return Decimal(value).quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP)


@transaction.atomic
def crear_proceso_trillado(data, user=None):
    proceso = ProcesoProductivo.objects.create(
        tipo_proceso=ProcesoProductivo.TRILLADO,
        fecha=data['fecha'],
        producto_consumido=data['producto_consumido'],
        cantidad_consumida=data['cantidad_consumida'],
        merma=data.get('merma') or Decimal('0'),
        costo_proceso_usd=data.get('costo_proceso_usd') or Decimal('0'),
        tipo_cambio_fecha_proceso=data['tipo_cambio_fecha_proceso'],
        observaciones=data.get('observaciones') or '',
        usuario_creacion=user if getattr(user, 'is_authenticated', False) else None,
    )
    ProcesoProductoObtenido.objects.create(
        proceso=proceso,
        producto=data['producto_exportable'],
        es_principal=True,
        cantidad_obtenida=data['cantidad_exportable'],
    )
    for item in _subproductos_from_data(data):
        ProcesoProductoObtenido.objects.create(
            proceso=proceso,
            producto=item['producto'],
            es_principal=False,
            cantidad_obtenida=item['cantidad'],
            valor_mercado_unitario=item['valor_mercado_unitario'],
        )
    return proceso


@transaction.atomic
def actualizar_proceso_trillado(proceso, data):
    proceso = ProcesoProductivo.objects.select_for_update().get(pk=proceso.pk)
    if proceso.confirmado:
        raise KardexError('No se puede editar un proceso confirmado. Anula y registra un nuevo proceso.')

    proceso.fecha = data['fecha']
    proceso.producto_consumido = data['producto_consumido']
    proceso.cantidad_consumida = data['cantidad_consumida']
    proceso.merma = data.get('merma') or Decimal('0')
    proceso.costo_proceso_usd = data.get('costo_proceso_usd') or Decimal('0')
    proceso.tipo_cambio_fecha_proceso = data['tipo_cambio_fecha_proceso']
    proceso.costo_proceso_soles = Decimal('0')
    proceso.costo_pergamino_consumido = Decimal('0')
    proceso.costo_total_proceso = Decimal('0')
    proceso.costo_exportable = Decimal('0')
    proceso.costo_unitario_exportable = Decimal('0')
    proceso.observaciones = data.get('observaciones') or ''
    proceso.save()

    proceso.productos_obtenidos.all().delete()
    ProcesoProductoObtenido.objects.create(
        proceso=proceso,
        producto=data['producto_exportable'],
        es_principal=True,
        cantidad_obtenida=data['cantidad_exportable'],
    )
    for item in _subproductos_from_data(data):
        ProcesoProductoObtenido.objects.create(
            proceso=proceso,
            producto=item['producto'],
            es_principal=False,
            cantidad_obtenida=item['cantidad'],
            valor_mercado_unitario=item['valor_mercado_unitario'],
        )
    return proceso


@transaction.atomic
def confirmar_proceso_trillado(proceso, user=None):
    proceso = (
        ProcesoProductivo.objects.select_for_update()
        .prefetch_related('productos_obtenidos__producto')
        .select_related('producto_consumido')
        .get(pk=proceso.pk)
    )
    if proceso.confirmado:
        raise KardexError('El proceso ya esta confirmado.')
    if proceso.anulado:
        raise KardexError('El proceso esta anulado.')
    if proceso.tipo_proceso != ProcesoProductivo.TRILLADO:
        raise KardexError('Solo se puede confirmar un proceso de trillado desde esta pantalla.')
    if proceso.tipo_cambio_fecha_proceso <= 0:
        raise KardexError('El tipo de cambio de la fecha del proceso debe ser mayor que cero.')
    if proceso.costo_proceso_usd < 0:
        raise KardexError('El costo de proceso USD no puede ser negativo.')

    obtenidos = list(proceso.productos_obtenidos.select_related('producto').order_by('id'))
    principales = [item for item in obtenidos if item.es_principal]
    subproductos = [item for item in obtenidos if not item.es_principal]
    if len(principales) != 1:
        raise KardexError('El proceso debe tener un unico producto exportable principal.')

    exportable = principales[0]
    if exportable.cantidad_obtenida <= 0:
        raise KardexError('La cantidad exportable debe ser mayor que cero.')

    cantidad_subproductos = sum((item.cantidad_obtenida for item in subproductos), Decimal('0'))
    total_fisico = exportable.cantidad_obtenida + cantidad_subproductos + proceso.merma
    if total_fisico != proceso.cantidad_consumida:
        raise KardexError('La cantidad de pergamino debe ser igual a exportable + subproductos + merma.')

    productos_afectados = [proceso.producto_consumido_id] + [item.producto_id for item in obtenidos]
    _validar_sin_movimientos_posteriores(productos_afectados, proceso.fecha)

    stock_pergamino = _stock_a_fecha(proceso.producto_consumido, proceso.fecha)
    if proceso.cantidad_consumida > stock_pergamino['cantidad']:
        raise KardexError(
            f'Stock insuficiente para {proceso.producto_consumido}. '
            f'Solicitado: {proceso.cantidad_consumida}; disponible a la fecha: {stock_pergamino["cantidad"]}.'
        )

    costo_pergamino = _money(proceso.cantidad_consumida * stock_pergamino['promedio'])
    costo_proceso_soles = _money(proceso.costo_proceso_usd * proceso.tipo_cambio_fecha_proceso)
    costo_total_proceso = _money(costo_pergamino + costo_proceso_soles)
    costo_total_subproductos = _money(
        sum((item.cantidad_obtenida * item.valor_mercado_unitario for item in subproductos), Decimal('0'))
    )
    if costo_total_subproductos > costo_total_proceso:
        raise KardexError('El costo total de subproductos no puede superar el costo total del proceso.')

    costo_exportable = _money(costo_total_proceso - costo_total_subproductos)
    if costo_exportable < 0:
        raise KardexError('El costo exportable no puede ser negativo.')
    costo_unitario_exportable = _unit(costo_exportable / exportable.cantidad_obtenida)

    _crear_salida_pergamino(proceso, stock_pergamino, costo_pergamino, user=user)
    exportable.costo_asignado = costo_exportable
    exportable.valor_mercado_unitario = Decimal('0')
    exportable.save(update_fields=['costo_asignado', 'valor_mercado_unitario'])
    _crear_entrada_obtenido(proceso, exportable, costo_exportable, user=user)

    for item in subproductos:
        costo_asignado = _money(item.cantidad_obtenida * item.valor_mercado_unitario)
        item.costo_asignado = costo_asignado
        item.save(update_fields=['costo_asignado'])
        _crear_entrada_obtenido(proceso, item, costo_asignado, user=user)

    proceso.costo_pergamino_consumido = costo_pergamino
    proceso.costo_proceso_soles = costo_proceso_soles
    proceso.costo_total_proceso = costo_total_proceso
    proceso.costo_exportable = costo_exportable
    proceso.costo_unitario_exportable = costo_unitario_exportable
    proceso.confirmado = True
    proceso.fecha_confirmacion = timezone.now()
    proceso.save(
        update_fields=[
            'costo_pergamino_consumido',
            'costo_proceso_soles',
            'costo_total_proceso',
            'costo_exportable',
            'costo_unitario_exportable',
            'confirmado',
            'fecha_confirmacion',
            'fecha_actualizacion',
        ]
    )

    Auditoria.objects.create(
        usuario=user if getattr(user, 'is_authenticated', False) else None,
        accion='confirmacion_trillado',
        modelo_afectado='ProcesoProductivo',
        registro_id=str(proceso.id),
        descripcion=f'Confirmado trillado {proceso.id}: {proceso.cantidad_consumida} de {proceso.producto_consumido}.',
    )
    return proceso


@transaction.atomic
def anular_proceso_trillado(proceso, user=None):
    proceso = ProcesoProductivo.objects.select_for_update().get(pk=proceso.pk)
    if not proceso.confirmado:
        raise KardexError('Solo se puede anular un proceso confirmado.')
    if proceso.anulado:
        raise KardexError('El proceso ya esta anulado.')

    movimientos = list(
        MovimientoKardex.objects.select_for_update()
        .filter(proceso_origen=proceso)
        .select_related('producto')
        .order_by('-fecha', '-id')
    )
    originales = [mov for mov in movimientos if mov.tipo_movimiento != MovimientoKardex.REVERSION]
    if not originales:
        raise KardexError('El proceso no tiene movimientos para anular.')

    for movimiento in originales:
        posteriores = MovimientoKardex.objects.filter(producto=movimiento.producto).filter(
            Q(fecha__gt=movimiento.fecha) | Q(fecha=movimiento.fecha, id__gt=movimiento.id)
        ).exclude(proceso_origen=proceso)
        if posteriores.exists():
            raise KardexError(
                f'No se puede anular: {movimiento.producto} tiene movimientos posteriores.'
            )

    for movimiento in originales:
        _crear_reversion_movimiento(proceso, movimiento, user=user)

    proceso.anulado = True
    proceso.fecha_anulacion = timezone.now()
    proceso.save(update_fields=['anulado', 'fecha_anulacion', 'fecha_actualizacion'])

    Auditoria.objects.create(
        usuario=user if getattr(user, 'is_authenticated', False) else None,
        accion='anulacion_trillado',
        modelo_afectado='ProcesoProductivo',
        registro_id=str(proceso.id),
        descripcion=f'Anulado trillado {proceso.id}.',
    )
    return proceso


def _crear_reversion_movimiento(proceso, movimiento, user=None):
    stock = _stock_a_fecha(movimiento.producto, movimiento.fecha)
    if movimiento.cantidad_entrada:
        if movimiento.cantidad_entrada > stock['cantidad']:
            raise KardexError(f'Stock insuficiente para anular entrada de {movimiento.producto}.')
        nuevo_stock_cantidad = stock['cantidad'] - movimiento.cantidad_entrada
        nuevo_stock_costo_total = _money(stock['costo_total'] - movimiento.costo_total_entrada)
        nuevo_promedio = _unit(nuevo_stock_costo_total / nuevo_stock_cantidad) if nuevo_stock_cantidad else Decimal('0')
        return MovimientoKardex.objects.create(
            fecha=movimiento.fecha,
            producto=movimiento.producto,
            proceso_origen=proceso,
            tipo_movimiento=MovimientoKardex.REVERSION,
            cantidad_salida=movimiento.cantidad_entrada,
            costo_unitario_salida=movimiento.costo_unitario_entrada,
            costo_total_salida=movimiento.costo_total_entrada,
            stock_cantidad=nuevo_stock_cantidad,
            stock_costo_unitario_promedio=nuevo_promedio,
            stock_costo_total=nuevo_stock_costo_total,
            observacion=f'Reversion de movimiento {movimiento.id} por anulacion de trillado {proceso.id}.',
            usuario_creacion=user if getattr(user, 'is_authenticated', False) else None,
        )

    nuevo_stock_cantidad = stock['cantidad'] + movimiento.cantidad_salida
    nuevo_stock_costo_total = _money(stock['costo_total'] + movimiento.costo_total_salida)
    nuevo_promedio = _unit(nuevo_stock_costo_total / nuevo_stock_cantidad) if nuevo_stock_cantidad else Decimal('0')
    return MovimientoKardex.objects.create(
        fecha=movimiento.fecha,
        producto=movimiento.producto,
        proceso_origen=proceso,
        tipo_movimiento=MovimientoKardex.REVERSION,
        cantidad_entrada=movimiento.cantidad_salida,
        costo_unitario_entrada=movimiento.costo_unitario_salida,
        costo_total_entrada=movimiento.costo_total_salida,
        stock_cantidad=nuevo_stock_cantidad,
        stock_costo_unitario_promedio=nuevo_promedio,
        stock_costo_total=nuevo_stock_costo_total,
        observacion=f'Reversion de movimiento {movimiento.id} por anulacion de trillado {proceso.id}.',
        usuario_creacion=user if getattr(user, 'is_authenticated', False) else None,
    )


def _crear_salida_pergamino(proceso, stock, costo_total_salida, user=None):
    nuevo_stock_cantidad = stock['cantidad'] - proceso.cantidad_consumida
    nuevo_stock_costo_total = _money(stock['costo_total'] - costo_total_salida)
    nuevo_promedio = _unit(nuevo_stock_costo_total / nuevo_stock_cantidad) if nuevo_stock_cantidad else Decimal('0')
    return MovimientoKardex.objects.create(
        fecha=proceso.fecha,
        producto=proceso.producto_consumido,
        proceso_origen=proceso,
        tipo_movimiento=MovimientoKardex.PROCESO_SALIDA,
        cantidad_salida=proceso.cantidad_consumida,
        costo_unitario_salida=stock['promedio'],
        costo_total_salida=costo_total_salida,
        stock_cantidad=nuevo_stock_cantidad,
        stock_costo_unitario_promedio=nuevo_promedio,
        stock_costo_total=nuevo_stock_costo_total,
        observacion=f'Salida por trillado {proceso.id}.',
        usuario_creacion=user if getattr(user, 'is_authenticated', False) else None,
    )


def _crear_entrada_obtenido(proceso, item, costo_asignado, user=None):
    stock = _stock_a_fecha(item.producto, proceso.fecha)
    costo_unitario = _unit(costo_asignado / item.cantidad_obtenida) if item.cantidad_obtenida else Decimal('0')
    nuevo_stock_cantidad = stock['cantidad'] + item.cantidad_obtenida
    nuevo_stock_costo_total = _money(stock['costo_total'] + costo_asignado)
    nuevo_promedio = _unit(nuevo_stock_costo_total / nuevo_stock_cantidad) if nuevo_stock_cantidad else Decimal('0')
    return MovimientoKardex.objects.create(
        fecha=proceso.fecha,
        producto=item.producto,
        proceso_origen=proceso,
        tipo_movimiento=MovimientoKardex.PROCESO_ENTRADA,
        cantidad_entrada=item.cantidad_obtenida,
        costo_unitario_entrada=costo_unitario,
        costo_total_entrada=costo_asignado,
        stock_cantidad=nuevo_stock_cantidad,
        stock_costo_unitario_promedio=nuevo_promedio,
        stock_costo_total=nuevo_stock_costo_total,
        observacion=f'Entrada por trillado {proceso.id}.',
        usuario_creacion=user if getattr(user, 'is_authenticated', False) else None,
    )


def _stock_a_fecha(producto, fecha):
    ultimo = MovimientoKardex.objects.filter(producto=producto, fecha__lte=fecha).order_by('-fecha', '-id').first()
    if not ultimo:
        return {'cantidad': Decimal('0'), 'promedio': Decimal('0'), 'costo_total': Decimal('0')}
    return {
        'cantidad': ultimo.stock_cantidad,
        'promedio': ultimo.stock_costo_unitario_promedio,
        'costo_total': ultimo.stock_costo_total,
    }


def _validar_sin_movimientos_posteriores(producto_ids, fecha):
    posteriores = MovimientoKardex.objects.filter(producto_id__in=producto_ids).filter(
        Q(fecha__gt=fecha)
    ).select_related('producto').order_by('fecha', 'id')
    if posteriores.exists():
        movimiento = posteriores.first()
        raise KardexError(
            f'No se puede confirmar el proceso con fecha {fecha}: '
            f'{movimiento.producto} tiene movimientos posteriores.'
        )


def _subproductos_from_data(data):
    for index in range(1, 4):
        producto = data.get(f'subproducto_{index}')
        cantidad = data.get(f'cantidad_subproducto_{index}')
        valor = data.get(f'valor_mercado_subproducto_{index}')
        if producto and cantidad:
            yield {
                'producto': producto,
                'cantidad': cantidad,
                'valor_mercado_unitario': valor or Decimal('0'),
            }
