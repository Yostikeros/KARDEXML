from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q

from kardex.services.unidades import inferir_cantidad_kg_descripcion


class TimeStampedModel(models.Model):
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class EmpresaPrincipal(TimeStampedModel):
    ruc = models.CharField(max_length=11, unique=True)
    razon_social = models.CharField(max_length=255)
    nombre_comercial = models.CharField(max_length=255, blank=True)
    direccion = models.CharField(max_length=255, blank=True)
    moneda_principal = models.CharField(max_length=3, default='PEN')
    unidad_base_inventario = models.CharField(max_length=20, default='KG')
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'empresa principal'
        verbose_name_plural = 'empresas principales'

    def __str__(self):
        return f'{self.ruc} - {self.razon_social}'


class Entidad(TimeStampedModel):
    RUC = 'RUC'
    DNI = 'DNI'
    CE = 'CE'
    OTRO = 'OTRO'

    TIPO_DOCUMENTO_IDENTIDAD_CHOICES = [
        (RUC, 'RUC'),
        (DNI, 'DNI'),
        (CE, 'Carnet de extranjeria'),
        (OTRO, 'Otro'),
    ]

    tipo_documento_identidad = models.CharField(
        max_length=10,
        choices=TIPO_DOCUMENTO_IDENTIDAD_CHOICES,
        default=RUC,
    )
    numero_documento = models.CharField(max_length=20, unique=True)
    razon_social = models.CharField(max_length=255)
    nombre_comercial = models.CharField(max_length=255, blank=True)
    direccion = models.CharField(max_length=255, blank=True)
    ubigeo = models.CharField(max_length=10, blank=True)
    departamento = models.CharField(max_length=100, blank=True)
    provincia = models.CharField(max_length=100, blank=True)
    distrito = models.CharField(max_length=100, blank=True)
    pais = models.CharField(max_length=100, blank=True, default='PE')
    telefono = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    es_cliente = models.BooleanField(default=False)
    es_proveedor = models.BooleanField(default=False)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'entidad'
        verbose_name_plural = 'entidades'
        indexes = [
            models.Index(fields=['numero_documento']),
            models.Index(fields=['razon_social']),
            models.Index(fields=['es_cliente', 'es_proveedor']),
        ]

    def __str__(self):
        return f'{self.numero_documento} - {self.razon_social}'


class Producto(TimeStampedModel):
    MATERIA_PRIMA = 'materia_prima'
    PRODUCTO_TERMINADO = 'producto_terminado'
    SUBPRODUCTO = 'subproducto'
    SUMINISTRO = 'suministro'
    SERVICIO = 'servicio'
    GASTO = 'gasto'

    TIPO_PRODUCTO_CHOICES = [
        (MATERIA_PRIMA, 'Materia prima'),
        (PRODUCTO_TERMINADO, 'Producto terminado'),
        (SUBPRODUCTO, 'Subproducto'),
        (SUMINISTRO, 'Suministro'),
        (SERVICIO, 'Servicio'),
        (GASTO, 'Gasto'),
    ]

    codigo_interno = models.CharField(max_length=50, unique=True)
    nombre = models.CharField(max_length=255)
    categoria = models.CharField(max_length=100, blank=True)
    tipo_producto = models.CharField(max_length=30, choices=TIPO_PRODUCTO_CHOICES)
    unidad_base = models.CharField(max_length=20, default='KG')
    controla_stock = models.BooleanField(default=True)
    afecta_kardex = models.BooleanField(default=True)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'producto'
        verbose_name_plural = 'productos'
        indexes = [
            models.Index(fields=['codigo_interno']),
            models.Index(fields=['nombre']),
            models.Index(fields=['tipo_producto']),
        ]

    def __str__(self):
        return f'{self.codigo_interno} - {self.nombre}'


class UnidadConversion(models.Model):
    unidad_origen = models.CharField(max_length=20)
    unidad_destino = models.CharField(max_length=20)
    factor = models.DecimalField(max_digits=18, decimal_places=6)
    descripcion = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = 'unidad de conversion'
        verbose_name_plural = 'unidades de conversion'
        constraints = [
            models.UniqueConstraint(
                fields=['unidad_origen', 'unidad_destino'],
                name='uq_unidad_conversion_origen_destino',
            ),
        ]

    def __str__(self):
        return f'{self.unidad_origen} a {self.unidad_destino} = {self.factor}'


class ProductoEquivalencia(TimeStampedModel):
    entidad = models.ForeignKey(
        Entidad,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='equivalencias_producto',
    )
    codigo_producto_xml = models.CharField(max_length=100, blank=True)
    descripcion_xml = models.CharField(max_length=500)
    unidad_medida_xml = models.CharField(max_length=20)
    producto = models.ForeignKey(
        Producto,
        on_delete=models.PROTECT,
        related_name='equivalencias_xml',
    )
    factor_conversion = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        default=Decimal('1'),
    )
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'equivalencia XML'
        verbose_name_plural = 'equivalencias XML'
        indexes = [
            models.Index(fields=['codigo_producto_xml', 'unidad_medida_xml']),
            models.Index(fields=['descripcion_xml']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    'entidad',
                    'codigo_producto_xml',
                    'descripcion_xml',
                    'unidad_medida_xml',
                ],
                condition=Q(activo=True),
                name='uq_equivalencia_xml_activa_por_entidad',
            ),
        ]

    def __str__(self):
        return f'{self.descripcion_xml} -> {self.producto}'

class TipoCambioSunat(models.Model):
    MES_CHOICES = [
        ('enero', 'Enero'),
        ('febrero', 'Febrero'),
        ('marzo', 'Marzo'),
        ('abril', 'Abril'),
        ('mayo', 'Mayo'),
        ('junio', 'Junio'),
        ('julio', 'Julio'),
        ('agosto', 'Agosto'),
        ('septiembre', 'Septiembre'),
        ('octubre', 'Octubre'),
        ('noviembre', 'Noviembre'),
        ('diciembre', 'Diciembre'),
    ]

    mes = models.CharField(max_length=20, choices=MES_CHOICES)
    anio = models.PositiveIntegerField()
    dia = models.PositiveSmallIntegerField()
    compra = models.DecimalField(max_digits=12, decimal_places=6)
    venta = models.DecimalField(max_digits=12, decimal_places=6)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'tipo de cambio SUNAT'
        verbose_name_plural = 'tipos de cambio SUNAT'
        constraints = [
            models.UniqueConstraint(
                fields=['mes', 'anio', 'dia'],
                name='uq_tipo_cambio_sunat_fecha',
            ),
        ]
        indexes = [
            models.Index(fields=['anio', 'mes', 'dia'], name='kardex_tipo_anio_90a065_idx'),
        ]

    def __str__(self):
        return f'{self.dia:02d} {self.mes} {self.anio} - C {self.compra} / V {self.venta}'

class Documento(TimeStampedModel):
    FACTURA = '01'
    BOLETA = '03'
    NOTA_CREDITO = '07'
    NOTA_DEBITO = '08'
    LIQUIDACION_COMPRA = '04'

    TIPO_DOCUMENTO_LABELS = {
        FACTURA: 'Factura',
        BOLETA: 'Boleta',
        NOTA_CREDITO: 'Nota de credito',
        NOTA_DEBITO: 'Nota de debito',
        LIQUIDACION_COMPRA: 'Liquidacion de compra',
    }

    COMPRA = 'compra'
    VENTA = 'venta'
    LIQUIDACION_COMPRA_OP = 'liquidacion_compra'
    NOTA_CREDITO_COMPRA = 'nota_credito_compra'
    NOTA_CREDITO_VENTA = 'nota_credito_venta'
    OTRO = 'otro'

    IMPORTADO = 'importado'
    PENDIENTE_CLASIFICACION = 'pendiente_clasificacion'
    PRE_KARDEX = 'pre_kardex'
    CONFIRMADO = 'confirmado'
    ANULADO = 'anulado'

    TIPO_OPERACION_CHOICES = [
        (COMPRA, 'Compra'),
        (VENTA, 'Venta'),
        (LIQUIDACION_COMPRA_OP, 'Liquidacion de compra'),
        (NOTA_CREDITO_COMPRA, 'Nota de credito de compra'),
        (NOTA_CREDITO_VENTA, 'Nota de credito de venta'),
        (OTRO, 'Otro'),
    ]
    ESTADO_CHOICES = [
        (IMPORTADO, 'Importado'),
        (PENDIENTE_CLASIFICACION, 'Pendiente de clasificacion'),
        (PRE_KARDEX, 'Pre-Kardex'),
        (CONFIRMADO, 'Confirmado'),
        (ANULADO, 'Anulado'),
    ]

    tipo_documento = models.CharField(max_length=5)
    serie = models.CharField(max_length=20)
    numero = models.CharField(max_length=30)
    fecha_emision = models.DateField()
    entidad_emisor = models.ForeignKey(
        Entidad,
        on_delete=models.PROTECT,
        related_name='documentos_emitidos',
    )
    entidad_receptor = models.ForeignKey(
        Entidad,
        on_delete=models.PROTECT,
        related_name='documentos_recibidos',
    )
    proveedor = models.ForeignKey(
        Entidad,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='documentos_como_proveedor',
    )
    cliente = models.ForeignKey(
        Entidad,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='documentos_como_cliente',
    )
    tipo_operacion = models.CharField(
        max_length=30,
        choices=TIPO_OPERACION_CHOICES,
        default=OTRO,
    )
    moneda = models.CharField(max_length=3, default='PEN')
    tipo_cambio = models.DecimalField(
        max_digits=12,
        decimal_places=6,
        null=True,
        blank=True,
    )
    total = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'))
    xml_hash = models.CharField(max_length=64, unique=True)
    estado = models.CharField(max_length=30, choices=ESTADO_CHOICES, default=IMPORTADO)
    usuario_creacion = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='documentos_creados',
    )

    class Meta:
        verbose_name = 'documento'
        verbose_name_plural = 'documentos'
        indexes = [
            models.Index(fields=['tipo_documento', 'serie', 'numero']),
            models.Index(fields=['fecha_emision']),
            models.Index(fields=['estado']),
            models.Index(fields=['tipo_operacion']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    'tipo_documento',
                    'serie',
                    'numero',
                    'entidad_emisor',
                    'entidad_receptor',
                ],
                name='uq_documento_identidad_sunat',
            ),
        ]

    @property
    def tipo_operacion_efectiva(self):
        if self.tipo_documento == self.LIQUIDACION_COMPRA and self.tipo_operacion == self.OTRO:
            return self.COMPRA
        return self.tipo_operacion

    @property
    def tipo_operacion_nombre(self):
        return dict(self.TIPO_OPERACION_CHOICES).get(self.tipo_operacion_efectiva, 'Otro')
    @property
    def tipo_documento_nombre(self):
        return self.TIPO_DOCUMENTO_LABELS.get(self.tipo_documento, 'Documento')

    @property
    def moneda_mostrada(self):
        moneda = (self.moneda or '').strip().upper()
        if moneda in {'PEN', 'USD', 'EUR'}:
            return moneda
        if moneda.startswith('ISO'):
            if self.tipo_documento == self.FACTURA and self.tipo_operacion_efectiva == self.VENTA:
                return 'USD'
            return 'PEN'
        return moneda or 'PEN'

    def __str__(self):
        return f'{self.tipo_documento}-{self.serie}-{self.numero}'


class DocumentoDetalle(TimeStampedModel):
    PENDIENTE = 'pendiente'
    CLASIFICADO = 'clasificado'
    NO_APLICA = 'no_aplica'

    ESTADO_CLASIFICACION_CHOICES = [
        (PENDIENTE, 'Pendiente'),
        (CLASIFICADO, 'Clasificado'),
        (NO_APLICA, 'No aplica'),
    ]

    documento = models.ForeignKey(
        Documento,
        on_delete=models.CASCADE,
        related_name='detalles',
    )
    codigo_producto_xml = models.CharField(max_length=100, blank=True)
    descripcion_xml = models.CharField(max_length=500)
    unidad_medida_xml = models.CharField(max_length=20)
    cantidad = models.DecimalField(max_digits=18, decimal_places=6)
    valor_unitario = models.DecimalField(max_digits=18, decimal_places=6, default=Decimal('0'))
    precio_unitario = models.DecimalField(max_digits=18, decimal_places=6, default=Decimal('0'))
    subtotal = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'))
    igv = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'))
    total = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'))
    producto = models.ForeignKey(
        Producto,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='detalles_documento',
    )
    factor_conversion = models.DecimalField(max_digits=18, decimal_places=6, default=Decimal('1'))
    cantidad_base = models.DecimalField(max_digits=18, decimal_places=6, default=Decimal('0'))
    afecta_kardex = models.BooleanField(default=False)
    estado_clasificacion = models.CharField(
        max_length=20,
        choices=ESTADO_CLASIFICACION_CHOICES,
        default=PENDIENTE,
    )

    class Meta:
        verbose_name = 'detalle de documento'
        verbose_name_plural = 'detalles de documento'
        indexes = [
            models.Index(fields=['estado_clasificacion']),
            models.Index(fields=['codigo_producto_xml', 'unidad_medida_xml']),
        ]

    @property
    def unidad_operativa(self):
        if self.producto_id and self.producto:
            return self.producto.unidad_base
        if self.factor_conversion and self.factor_conversion != Decimal('1'):
            return 'KG'
        if self.unidad_medida_xml == 'KGM':
            return 'KG'
        if self.unidad_medida_xml == 'NIU':
            if self.cantidad_kg_descripcion:
                return 'KG'
            return 'UND'
        return self.unidad_medida_xml

    @property
    def cantidad_operativa(self):
        if self.factor_conversion and self.factor_conversion != Decimal('1'):
            return self.cantidad_base
        if self.unidad_medida_xml == 'NIU' and self.cantidad <= 0:
            cantidad_kg = self.cantidad_kg_descripcion
            if cantidad_kg:
                return cantidad_kg
        return self.cantidad

    @property
    def cantidad_kg_descripcion(self):
        return inferir_cantidad_kg_descripcion(self.descripcion_xml)

    @property
    def unidad_xml_mostrada(self):
        if self.unidad_medida_xml == 'KGM':
            return 'KG'
        if self.unidad_medida_xml == 'NIU':
            if self.cantidad_kg_descripcion:
                return 'KG'
            return 'UND'
        return self.unidad_medida_xml

    def __str__(self):
        return f'{self.documento} - {self.descripcion_xml}'


class MovimientoKardex(models.Model):
    ENTRADA = 'entrada'
    SALIDA = 'salida'
    PROCESO_ENTRADA = 'proceso_entrada'
    PROCESO_SALIDA = 'proceso_salida'
    AJUSTE_ENTRADA = 'ajuste_entrada'
    AJUSTE_SALIDA = 'ajuste_salida'
    REVERSION = 'reversion'

    TIPO_MOVIMIENTO_CHOICES = [
        (ENTRADA, 'Entrada'),
        (SALIDA, 'Salida'),
        (PROCESO_ENTRADA, 'Proceso entrada'),
        (PROCESO_SALIDA, 'Proceso salida'),
        (AJUSTE_ENTRADA, 'Ajuste entrada'),
        (AJUSTE_SALIDA, 'Ajuste salida'),
        (REVERSION, 'Reversion'),
    ]

    fecha = models.DateField()
    producto = models.ForeignKey(
        Producto,
        on_delete=models.PROTECT,
        related_name='movimientos_kardex',
    )
    documento_origen = models.ForeignKey(
        Documento,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='movimientos_kardex',
    )
    proceso_origen = models.ForeignKey(
        'ProcesoProductivo',
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='movimientos_kardex',
    )
    entidad = models.ForeignKey(
        Entidad,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='movimientos_kardex',
    )
    tipo_movimiento = models.CharField(max_length=30, choices=TIPO_MOVIMIENTO_CHOICES)
    cantidad_entrada = models.DecimalField(max_digits=18, decimal_places=6, default=Decimal('0'))
    costo_unitario_entrada = models.DecimalField(max_digits=18, decimal_places=6, default=Decimal('0'))
    costo_total_entrada = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'))
    cantidad_salida = models.DecimalField(max_digits=18, decimal_places=6, default=Decimal('0'))
    costo_unitario_salida = models.DecimalField(max_digits=18, decimal_places=6, default=Decimal('0'))
    costo_total_salida = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'))
    stock_cantidad = models.DecimalField(max_digits=18, decimal_places=6, default=Decimal('0'))
    stock_costo_unitario_promedio = models.DecimalField(max_digits=18, decimal_places=6, default=Decimal('0'))
    stock_costo_total = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'))
    observacion = models.TextField(blank=True)
    usuario_creacion = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='movimientos_kardex_creados',
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'movimiento de Kardex'
        verbose_name_plural = 'movimientos de Kardex'
        ordering = ['fecha', 'id']
        indexes = [
            models.Index(fields=['producto', 'fecha']),
            models.Index(fields=['tipo_movimiento']),
            models.Index(fields=['documento_origen']),
            models.Index(fields=['proceso_origen']),
        ]

    def __str__(self):
        return f'{self.fecha} - {self.producto} - {self.tipo_movimiento}'


class ProcesoProductivo(TimeStampedModel):
    TRILLADO = 'trillado'

    TIPO_PROCESO_CHOICES = [
        (TRILLADO, 'Cafe trillado'),
    ]

    tipo_proceso = models.CharField(max_length=30, choices=TIPO_PROCESO_CHOICES, default=TRILLADO)
    fecha = models.DateField()
    producto_consumido = models.ForeignKey(
        Producto,
        on_delete=models.PROTECT,
        related_name='procesos_como_insumo',
    )
    cantidad_consumida = models.DecimalField(max_digits=18, decimal_places=6)
    merma = models.DecimalField(max_digits=18, decimal_places=6, default=Decimal('0'))
    costo_proceso_usd = models.DecimalField(max_digits=18, decimal_places=6, default=Decimal('0'))
    tipo_cambio_fecha_proceso = models.DecimalField(max_digits=12, decimal_places=6, default=Decimal('0'))
    costo_proceso_soles = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'))
    costo_pergamino_consumido = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'))
    costo_total_proceso = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'))
    costo_exportable = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'))
    costo_unitario_exportable = models.DecimalField(max_digits=18, decimal_places=6, default=Decimal('0'))
    observaciones = models.TextField(blank=True)
    confirmado = models.BooleanField(default=False)
    anulado = models.BooleanField(default=False)
    fecha_confirmacion = models.DateTimeField(null=True, blank=True)
    fecha_anulacion = models.DateTimeField(null=True, blank=True)
    usuario_creacion = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='procesos_productivos_creados',
    )

    class Meta:
        verbose_name = 'proceso productivo'
        verbose_name_plural = 'procesos productivos'
        indexes = [
            models.Index(fields=['fecha']),
            models.Index(fields=['confirmado']),
        ]

    def __str__(self):
        return f'Proceso {self.id} - {self.fecha}'


class ProcesoProductoObtenido(models.Model):
    proceso = models.ForeignKey(
        ProcesoProductivo,
        on_delete=models.CASCADE,
        related_name='productos_obtenidos',
    )
    producto = models.ForeignKey(
        Producto,
        on_delete=models.PROTECT,
        related_name='procesos_como_resultado',
    )
    es_principal = models.BooleanField(default=False)
    cantidad_obtenida = models.DecimalField(max_digits=18, decimal_places=6)
    valor_mercado_unitario = models.DecimalField(max_digits=18, decimal_places=6, default=Decimal('0'))
    costo_asignado = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'))

    class Meta:
        verbose_name = 'producto obtenido de proceso'
        verbose_name_plural = 'productos obtenidos de proceso'
        constraints = [
            models.UniqueConstraint(
                fields=['proceso', 'producto'],
                name='uq_proceso_producto_obtenido',
            ),
        ]

    def __str__(self):
        return f'{self.proceso} - {self.producto}'


class Auditoria(models.Model):
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='auditorias',
    )
    fecha_hora = models.DateTimeField(auto_now_add=True)
    accion = models.CharField(max_length=100)
    modelo_afectado = models.CharField(max_length=100)
    registro_id = models.CharField(max_length=50, blank=True)
    descripcion = models.TextField(blank=True)

    class Meta:
        verbose_name = 'auditoria'
        verbose_name_plural = 'auditorias'
        ordering = ['-fecha_hora']
        indexes = [
            models.Index(fields=['fecha_hora']),
            models.Index(fields=['accion']),
            models.Index(fields=['modelo_afectado', 'registro_id']),
        ]

    def __str__(self):
        return f'{self.fecha_hora} - {self.accion} - {self.modelo_afectado}'
