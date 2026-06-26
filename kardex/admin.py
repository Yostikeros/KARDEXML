from django.contrib import admin

from .models import (
    Auditoria,
    Documento,
    DocumentoDetalle,
    EmpresaPrincipal,
    Entidad,
    MovimientoKardex,
    ProcesoProductivo,
    ProcesoProductoObtenido,
    Producto,
    ProductoEquivalencia,
    TipoCambioSunat,
    UnidadConversion,
)


@admin.register(EmpresaPrincipal)
class EmpresaPrincipalAdmin(admin.ModelAdmin):
    list_display = ("ruc", "razon_social", "moneda_principal", "unidad_base_inventario", "activo")
    search_fields = ("ruc", "razon_social", "nombre_comercial")
    list_filter = ("activo",)


@admin.register(Entidad)
class EntidadAdmin(admin.ModelAdmin):
    list_display = ("numero_documento", "razon_social", "tipo_documento_identidad", "es_cliente", "es_proveedor", "activo")
    search_fields = ("numero_documento", "razon_social", "nombre_comercial")
    list_filter = ("tipo_documento_identidad", "es_cliente", "es_proveedor", "activo")


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ("codigo_interno", "nombre", "tipo_producto", "unidad_base", "controla_stock", "afecta_kardex", "activo")
    search_fields = ("codigo_interno", "nombre", "categoria")
    list_filter = ("tipo_producto", "controla_stock", "afecta_kardex", "activo")


@admin.register(UnidadConversion)
class UnidadConversionAdmin(admin.ModelAdmin):
    list_display = ("unidad_origen", "unidad_destino", "factor", "descripcion")
    search_fields = ("unidad_origen", "unidad_destino", "descripcion")


@admin.register(ProductoEquivalencia)
class ProductoEquivalenciaAdmin(admin.ModelAdmin):
    list_display = ("descripcion_xml", "codigo_producto_xml", "unidad_medida_xml", "producto", "entidad", "factor_conversion", "activo")
    search_fields = ("descripcion_xml", "codigo_producto_xml", "producto__nombre", "entidad__razon_social")
    list_filter = ("activo", "unidad_medida_xml")
    autocomplete_fields = ("entidad", "producto")


class DocumentoDetalleInline(admin.TabularInline):
    model = DocumentoDetalle
    extra = 0
    fields = (
        "codigo_producto_xml",
        "descripcion_xml",
        "unidad_medida_xml",
        "cantidad",
        "producto",
        "factor_conversion",
        "cantidad_base",
        "afecta_kardex",
        "estado_clasificacion",
    )
    autocomplete_fields = ("producto",)


@admin.register(Documento)
class DocumentoAdmin(admin.ModelAdmin):
    list_display = ("fecha_emision", "tipo_documento", "serie", "numero", "tipo_operacion", "estado", "total")
    search_fields = ("serie", "numero", "entidad_emisor__razon_social", "entidad_receptor__razon_social")
    list_filter = ("estado", "tipo_operacion", "tipo_documento", "fecha_emision")
    date_hierarchy = "fecha_emision"
    autocomplete_fields = ("entidad_emisor", "entidad_receptor", "proveedor", "cliente", "usuario_creacion")
    inlines = (DocumentoDetalleInline,)


@admin.register(DocumentoDetalle)
class DocumentoDetalleAdmin(admin.ModelAdmin):
    list_display = ("documento", "descripcion_xml", "unidad_medida_xml", "cantidad", "producto", "estado_clasificacion", "afecta_kardex")
    search_fields = ("descripcion_xml", "codigo_producto_xml", "documento__serie", "documento__numero", "producto__nombre")
    list_filter = ("estado_clasificacion", "afecta_kardex", "unidad_medida_xml")
    autocomplete_fields = ("documento", "producto")


@admin.register(MovimientoKardex)
class MovimientoKardexAdmin(admin.ModelAdmin):
    list_display = ("fecha", "producto", "tipo_movimiento", "cantidad_entrada", "cantidad_salida", "stock_cantidad", "stock_costo_total")
    search_fields = ("producto__nombre", "documento_origen__serie", "documento_origen__numero", "entidad__razon_social")
    list_filter = ("tipo_movimiento", "fecha")
    date_hierarchy = "fecha"
    autocomplete_fields = ("producto", "documento_origen", "proceso_origen", "entidad", "usuario_creacion")


@admin.register(ProcesoProductivo)
class ProcesoProductivoAdmin(admin.ModelAdmin):
    list_display = ("fecha", "tipo_proceso", "producto_consumido", "cantidad_consumida", "costo_proceso_usd", "tipo_cambio_fecha_proceso", "costo_total_proceso", "confirmado", "anulado")
    search_fields = ("producto_consumido__nombre", "observaciones")
    list_filter = ("tipo_proceso", "confirmado", "anulado", "fecha")
    autocomplete_fields = ("producto_consumido", "usuario_creacion")


@admin.register(ProcesoProductoObtenido)
class ProcesoProductoObtenidoAdmin(admin.ModelAdmin):
    list_display = ("proceso", "producto", "es_principal", "cantidad_obtenida", "valor_mercado_unitario", "costo_asignado")
    autocomplete_fields = ("proceso", "producto")


@admin.register(Auditoria)
class AuditoriaAdmin(admin.ModelAdmin):
    list_display = ("fecha_hora", "accion", "modelo_afectado", "registro_id", "usuario")
    search_fields = ("accion", "modelo_afectado", "registro_id", "descripcion", "usuario__username")
    list_filter = ("accion", "modelo_afectado", "fecha_hora")
    readonly_fields = ("fecha_hora",)


@admin.register(TipoCambioSunat)
class TipoCambioSunatAdmin(admin.ModelAdmin):
    list_display = ("anio", "mes", "dia", "compra", "venta")
    search_fields = ("anio", "mes")
    list_filter = ("anio", "mes")
