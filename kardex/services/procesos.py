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
        lote=data.get('lote') or '',
        factura_relacionada=data.get('factura_relacionada') or '',
        fecha_factura_relacionada=data.get('fecha_factura_relacionada'),
        producto_consumido=data['producto_consumido'],
        cantidad_consumida=data['cantidad_consumida'],
        merma=data.get('merma') or Decimal('0'),
        costo_proceso_usd=data.get('costo_proceso_usd') or Decimal('0'),
        tipo_cambio_fecha_proceso=data['tipo_cambio_fecha_proceso'],
        estado=ProcesoProductivo.BORRADOR,
        observaciones=data.get('observaciones') or '',
        usuario_creacion=user if getattr(user, 'is_authenticated', False) else None,
    )
    _asignar_codigo_proceso(proceso)
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
            valor_mercado_unitario_soles=item['valor_mercado_unitario_soles'],
        )
    _actualizar_costos_proceso(proceso, strict=False)
    return proceso


@transaction.atomic
def actualizar_proceso_trillado(proceso, data):
    proceso = ProcesoProductivo.objects.select_for_update().get(pk=proceso.pk)
    if proceso.confirmado:
        raise KardexError('No se puede editar un proceso confirmado. Anula y registra un nuevo proceso.')

    proceso.fecha = data['fecha']
    proceso.lote = data.get('lote') or ''
    proceso.factura_relacionada = data.get('factura_relacionada') or ''
    proceso.fecha_factura_relacionada = data.get('fecha_factura_relacionada')
    proceso.producto_consumido = data['producto_consumido']
    proceso.cantidad_consumida = data['cantidad_consumida']
    proceso.merma = data.get('merma') or Decimal('0')
    proceso.costo_proceso_usd = data.get('costo_proceso_usd') or Decimal('0')
    proceso.tipo_cambio_fecha_proceso = data['tipo_cambio_fecha_proceso']
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
            valor_mercado_unitario_soles=item['valor_mercado_unitario_soles'],
        )
    _actualizar_costos_proceso(proceso, strict=False)
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

    calculo = _actualizar_costos_proceso(proceso, strict=True)
    obtenidos = calculo['obtenidos']
    exportable = calculo['exportable']
    subproductos = calculo['subproductos']
    stock_pergamino = calculo['stock_pergamino']
    productos_afectados = [proceso.producto_consumido_id] + [item.producto_id for item in obtenidos]

    _crear_salida_pergamino(proceso, stock_pergamino, calculo['costo_pergamino'], user=user)
    _crear_entrada_obtenido(proceso, exportable, calculo['costo_exportable'], user=user)

    for item in subproductos:
        _crear_entrada_obtenido(proceso, item, item.costo_asignado, user=user)

    _recalcular_saldos_productos_desde(productos_afectados, proceso.fecha)

    proceso.confirmado = True
    proceso.estado = ProcesoProductivo.CONFIRMADO
    proceso.fecha_confirmacion = timezone.now()
    proceso.save(
        update_fields=[
            'confirmado',
            'estado',
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
    proceso.estado = ProcesoProductivo.ANULADO
    proceso.fecha_anulacion = timezone.now()
    proceso.save(update_fields=['anulado', 'estado', 'fecha_anulacion', 'fecha_actualizacion'])

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


def _actualizar_costos_proceso(proceso, strict=False):
    proceso = (
        ProcesoProductivo.objects.select_related('producto_consumido')
        .prefetch_related('productos_obtenidos__producto')
        .get(pk=proceso.pk)
    )
    obtenidos = list(proceso.productos_obtenidos.select_related('producto').order_by('id'))
    principales = [item for item in obtenidos if item.es_principal]
    subproductos = [item for item in obtenidos if not item.es_principal]
    if len(principales) != 1:
        raise KardexError('El proceso debe tener un unico producto exportable principal.')

    exportable = principales[0]
    _validar_componentes_proceso(proceso, exportable, subproductos, strict=strict)

    stock_pergamino = _stock_a_fecha(proceso.producto_consumido, proceso.fecha)
    if strict and proceso.cantidad_consumida > stock_pergamino['cantidad']:
        raise KardexError(
            f'Stock insuficiente para {proceso.producto_consumido}. '
            f'Solicitado: {proceso.cantidad_consumida}; disponible a la fecha: {stock_pergamino["cantidad"]}.'
        )

    costo_pergamino = _money(proceso.cantidad_consumida * stock_pergamino['promedio'])
    costo_proceso_soles = _money(proceso.costo_proceso_usd * proceso.tipo_cambio_fecha_proceso)
    costo_total_proceso = _money(costo_pergamino + costo_proceso_soles)
    costo_total_subproductos = _money(
        sum((item.cantidad_obtenida * item.valor_mercado_unitario_soles for item in subproductos), Decimal('0'))
    )
    if strict and costo_total_subproductos > costo_total_proceso:
        raise KardexError('El costo total de subproductos no puede superar el costo total del proceso.')

    costo_exportable = _money(costo_total_proceso - costo_total_subproductos)
    if strict and costo_exportable < 0:
        raise KardexError('El costo exportable no puede ser negativo.')
    costo_unitario_exportable = _unit(costo_exportable / exportable.cantidad_obtenida) if exportable.cantidad_obtenida else Decimal('0')

    exportable.costo_asignado = costo_exportable
    exportable.valor_mercado_unitario_soles = Decimal('0')
    exportable.save(update_fields=['costo_asignado', 'valor_mercado_unitario_soles'])
    for item in subproductos:
        item.costo_asignado = _money(item.cantidad_obtenida * item.valor_mercado_unitario_soles)
        item.save(update_fields=['costo_asignado'])

    proceso.costo_pergamino_consumido = costo_pergamino
    proceso.costo_proceso_soles = costo_proceso_soles
    proceso.costo_total_proceso = costo_total_proceso
    proceso.costo_exportable = costo_exportable
    proceso.costo_unitario_exportable = costo_unitario_exportable
    proceso.save(
        update_fields=[
            'costo_pergamino_consumido',
            'costo_proceso_soles',
            'costo_total_proceso',
            'costo_exportable',
            'costo_unitario_exportable',
            'fecha_actualizacion',
        ]
    )
    return {
        'obtenidos': obtenidos,
        'exportable': exportable,
        'subproductos': subproductos,
        'stock_pergamino': stock_pergamino,
        'costo_pergamino': costo_pergamino,
        'costo_exportable': costo_exportable,
    }


def _validar_componentes_proceso(proceso, exportable, subproductos, strict=False):
    if proceso.fecha is None:
        raise KardexError('La fecha del proceso es obligatoria.')
    if proceso.cantidad_consumida <= 0:
        raise KardexError('La cantidad de pergamino debe ser mayor que cero.')
    if exportable.cantidad_obtenida <= 0:
        raise KardexError('La cantidad exportable debe ser mayor que cero.')
    if proceso.tipo_cambio_fecha_proceso <= 0:
        raise KardexError('El tipo de cambio de la fecha del proceso debe ser mayor que cero.')
    if proceso.costo_proceso_usd < 0:
        raise KardexError('El costo de proceso USD no puede ser negativo.')
    if proceso.merma < 0:
        raise KardexError('La merma no puede ser negativa.')
    for item in subproductos:
        if item.cantidad_obtenida < 0:
            raise KardexError('Las cantidades de subproductos no pueden ser negativas.')
        if item.valor_mercado_unitario_soles < 0:
            raise KardexError('El valor de mercado de subproductos no puede ser negativo.')

    cantidad_subproductos = sum((item.cantidad_obtenida for item in subproductos), Decimal('0'))
    total_fisico = exportable.cantidad_obtenida + cantidad_subproductos + proceso.merma
    if strict and total_fisico != proceso.cantidad_consumida:
        raise KardexError('La cantidad de pergamino debe ser igual a exportable + subproductos + merma.')


def _asignar_codigo_proceso(proceso):
    if proceso.codigo_proceso:
        return
    proceso.codigo_proceso = f'TRI-{proceso.fecha:%Y}-{proceso.id:04d}'
    proceso.save(update_fields=['codigo_proceso', 'fecha_actualizacion'])


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


def _subproductos_from_data(data):
    tipo_cambio = data.get('tipo_cambio_fecha_proceso') or Decimal('0')
    for index in range(1, 4):
        producto = data.get(f'subproducto_{index}')
        cantidad = data.get(f'cantidad_subproducto_{index}')
        valor = data.get(f'valor_mercado_subproducto_{index}')
        if producto and cantidad:
            valor_usd = valor or Decimal('0')
            yield {
                'producto': producto,
                'cantidad': cantidad,
                'valor_mercado_unitario_soles': _unit(valor_usd * tipo_cambio),
            }
