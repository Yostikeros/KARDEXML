from calendar import monthrange
from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.http import FileResponse
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from .forms import (
    ClasificarBloqueForm,
    ClasificarDetalleForm,
    EntidadForm,
    ImportarXMLLoteForm,
    ProductoEquivalenciaForm,
    ProductoForm,
    ProcesoTrilladoForm,
    RestaurarBaseDatosForm,
    StockInicialForm,
    TipoCambioSunatImportForm,
)
from .models import Documento, DocumentoDetalle, Entidad, MovimientoKardex, ProcesoProductivo, Producto, ProductoEquivalencia, TipoCambioSunat
from .services.clasificacion import (
    clasificar_detalle,
    clasificar_detalles_bloque,
    clasificar_documentos_bloque,
    excluir_detalle_kardex,
    generar_pre_kardex,
)
from .services.dashboard import obtener_analisis_compras_ventas
from .services.database_maintenance import (
    DatabaseMaintenanceError,
    crear_backup_base_datos,
    restaurar_base_datos,
)
from .services.excel import generar_excel_response
from .services.kardex import (
    KardexError,
    confirmar_documento_kardex,
    confirmar_documentos_kardex,
    devolver_documento_a_pendiente,
    editar_stock_inicial,
    registrar_stock_inicial,
    revertir_aprobacion_kardex,
    revertir_pre_kardex,
)
from .services.procesos import (
    anular_proceso_trillado,
    actualizar_detalles_proceso_trillado,
    actualizar_proceso_trillado,
    confirmar_proceso_trillado,
    crear_proceso_trillado,
)
from .services.reportes import (
    MESES_NOMBRE,
    entidad_documento_reporte,
    obtener_empresa_principal,
    obtener_documentos_importados,
    obtener_documentos_mensual,
    obtener_documentos_mensual_detalle,
    obtener_kardex_sunat_producto,
    obtener_movimientos_documento,
    obtener_movimientos_producto,
    obtener_reporte_mensual_kardex_kg,
    obtener_stock_actual,
    obtener_stock_valorizado_total,
)
from .services.tipo_cambio import extraer_tipo_cambio_sunat
from .services.xml_importer import importar_xml_lote


@login_required(login_url="/admin/login/")
def dashboard(request):
    filtros_analisis = {
        "producto": request.GET.get("producto") or "",
        "categoria": request.GET.get("categoria") or "",
        "fecha_desde": request.GET.get("fecha_desde") or "",
        "fecha_hasta": request.GET.get("fecha_hasta") or "",
        "proveedor": request.GET.get("proveedor") or "",
        "cliente": request.GET.get("cliente") or "",
        "almacen": request.GET.get("almacen") or "principal",
        "tipo_documento": request.GET.get("tipo_documento") or "",
    }
    analisis = obtener_analisis_compras_ventas(filtros_analisis)
    context = {
        "productos_activos": Producto.objects.filter(activo=True).count(),
        "clientes": Entidad.objects.filter(es_cliente=True, activo=True).count(),
        "proveedores": Entidad.objects.filter(es_proveedor=True, activo=True).count(),
        "documentos_importados": Documento.objects.count(),
        "documentos_pendientes": Documento.objects.filter(estado=Documento.PENDIENTE_CLASIFICACION).count(),
        "stock_valorizado_total": obtener_stock_valorizado_total(),
        "ultimos_movimientos": MovimientoKardex.objects.select_related("producto").order_by("-fecha", "-id")[:10],
        "analisis": analisis,
        "productos_filtro": Producto.objects.filter(activo=True, controla_stock=True).order_by("nombre"),
        "categorias_filtro": Producto.objects.exclude(categoria="").values_list("categoria", flat=True).distinct().order_by("categoria"),
        "proveedores_filtro": Entidad.objects.filter(activo=True, es_proveedor=True).order_by("razon_social"),
        "clientes_filtro": Entidad.objects.filter(activo=True, es_cliente=True).order_by("razon_social"),
        "tipos_documento_filtro": Documento.TIPO_DOCUMENTO_LABELS.items(),
    }
    return render(request, "kardex/dashboard.html", context)


@login_required(login_url="/admin/login/")
def importar_xml_lote_view(request):
    resultados = None
    if request.method == "POST":
        form = ImportarXMLLoteForm(request.POST, request.FILES)
        if form.is_valid():
            resultados = importar_xml_lote(request.FILES.getlist("archivos"), user=request.user)
            importados = sum(1 for resultado in resultados if resultado.ok)
            errores = [resultado for resultado in resultados if not resultado.ok]
            if importados:
                messages.success(request, f"Importacion XML: {importados} importado(s).")
            if errores:
                messages.error(request, f"No se importaron {len(errores)} archivo(s). Revisa el detalle abajo.")
    else:
        form = ImportarXMLLoteForm()
    return render(request, "kardex/importar_xml_lote.html", {"form": form, "resultados": resultados})


@login_required(login_url="/admin/login/")
def productos_lista_view(request):
    productos = Producto.objects.order_by("nombre")
    return render(request, "kardex/productos_lista.html", {"productos": productos})


@login_required(login_url="/admin/login/")
def producto_crear_view(request):
    form = ProductoForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Producto creado correctamente.")
        return redirect("kardex:productos_lista")
    return render(request, "kardex/producto_form.html", {"form": form})


@login_required(login_url="/admin/login/")
def producto_editar_view(request, producto_id):
    producto = get_object_or_404(Producto, pk=producto_id)
    form = ProductoForm(request.POST or None, instance=producto)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Producto actualizado correctamente.")
        return redirect("kardex:productos_lista")
    return render(request, "kardex/producto_form.html", {"form": form, "producto": producto})


@login_required(login_url="/admin/login/")
def entidades_lista_view(request):
    entidades = Entidad.objects.order_by("razon_social")
    q = request.GET.get("q")
    rol = request.GET.get("rol")
    estado = request.GET.get("estado")
    if q:
        entidades = entidades.filter(Q(razon_social__icontains=q) | Q(numero_documento__icontains=q))
    if rol == "clientes":
        entidades = entidades.filter(es_cliente=True)
    elif rol == "proveedores":
        entidades = entidades.filter(es_proveedor=True)
    elif rol == "ambos":
        entidades = entidades.filter(es_cliente=True, es_proveedor=True)
    if estado == "activos":
        entidades = entidades.filter(activo=True)
    elif estado == "inactivos":
        entidades = entidades.filter(activo=False)
    return render(request, "kardex/entidades_lista.html", {"entidades": entidades})


@login_required(login_url="/admin/login/")
def entidad_crear_view(request):
    form = EntidadForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Entidad creada correctamente.")
        return redirect("kardex:entidades_lista")
    return render(request, "kardex/entidad_form.html", {"form": form})


@login_required(login_url="/admin/login/")
def entidad_editar_view(request, entidad_id):
    entidad = get_object_or_404(Entidad, pk=entidad_id)
    form = EntidadForm(request.POST or None, instance=entidad)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Entidad actualizada correctamente.")
        return redirect("kardex:entidades_lista")
    return render(request, "kardex/entidad_form.html", {"form": form, "entidad": entidad})


@login_required(login_url="/admin/login/")
@require_POST
def entidad_toggle_view(request, entidad_id):
    entidad = get_object_or_404(Entidad, pk=entidad_id)
    entidad.activo = not entidad.activo
    entidad.save(update_fields=["activo", "fecha_actualizacion"])
    return redirect("kardex:entidades_lista")


@login_required(login_url="/admin/login/")
def equivalencias_xml_lista_view(request):
    equivalencias = ProductoEquivalencia.objects.select_related("entidad", "producto").order_by("descripcion_xml")
    return render(request, "kardex/equivalencias_xml_lista.html", {"equivalencias": equivalencias})


@login_required(login_url="/admin/login/")
def equivalencia_xml_crear_view(request):
    form = ProductoEquivalenciaForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("kardex:equivalencias_xml_lista")
    return render(request, "kardex/equivalencia_xml_form.html", {"form": form})


@login_required(login_url="/admin/login/")
def equivalencia_xml_editar_view(request, equivalencia_id):
    equivalencia = get_object_or_404(ProductoEquivalencia, pk=equivalencia_id)
    form = ProductoEquivalenciaForm(request.POST or None, instance=equivalencia)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("kardex:equivalencias_xml_lista")
    return render(request, "kardex/equivalencia_xml_form.html", {"form": form, "equivalencia": equivalencia})


@login_required(login_url="/admin/login/")
@require_POST
def equivalencia_xml_toggle_view(request, equivalencia_id):
    equivalencia = get_object_or_404(ProductoEquivalencia, pk=equivalencia_id)
    equivalencia.activo = not equivalencia.activo
    equivalencia.save(update_fields=["activo", "fecha_actualizacion"])
    return redirect("kardex:equivalencias_xml_lista")


@login_required(login_url="/admin/login/")
def documentos_lista_view(request):
    documentos = obtener_documentos_importados()
    orden = request.GET.get("orden") or "fecha"
    tipo_documento = request.GET.get("tipo_documento") or ""
    estado = request.GET.get("estado") or ""
    documento_busqueda = (request.GET.get("documento") or "").strip()
    if tipo_documento:
        documentos = documentos.filter(tipo_documento=tipo_documento)
    if estado:
        documentos = documentos.filter(estado=estado)
    if documento_busqueda:
        documentos = documentos.filter(
            Q(serie__icontains=documento_busqueda)
            | Q(numero__icontains=documento_busqueda)
            | Q(tipo_documento__icontains=documento_busqueda)
        )
    ordenamientos = {
        "fecha": ("-fecha_emision", "-id"),
        "tipo_documento": ("tipo_documento", "serie", "numero", "-fecha_emision", "-id"),
        "estado": ("estado", "-fecha_emision", "-id"),
    }
    documentos = documentos.order_by(*ordenamientos.get(orden, ordenamientos["fecha"]))
    form = ClasificarBloqueForm()
    return render(
        request,
        "kardex/documentos_lista.html",
        {
            "documentos": documentos,
            "form": form,
            "orden": orden,
            "tipo_documento": tipo_documento,
            "estado": estado,
            "documento_busqueda": documento_busqueda,
            "tipos_documento": Documento.TIPO_DOCUMENTO_LABELS.items(),
            "estados": Documento.ESTADO_CHOICES,
        },
    )


def _post_list(request, *names):
    for name in names:
        values = request.POST.getlist(name)
        if values:
            return values
    return []


@login_required(login_url="/admin/login/")
@require_POST
def clasificar_documentos_bloque_view(request):
    form = ClasificarBloqueForm(request.POST)
    documento_ids = _post_list(request, "documento_ids", "documentos")
    if form.is_valid():
        try:
            clasificar_documentos_bloque(documento_ids, user=request.user, **form.cleaned_data)
            messages.success(request, "Documentos clasificados correctamente.")
        except ValueError as exc:
            messages.error(request, str(exc))
    else:
        messages.error(request, "Revisa los datos del formulario de clasificacion.")
    return redirect("kardex:documentos_lista")


@login_required(login_url="/admin/login/")
def documentos_pendientes_view(request):
    documentos = Documento.objects.prefetch_related("detalles").filter(estado=Documento.PENDIENTE_CLASIFICACION).order_by("-fecha_emision", "-id")
    return render(request, "kardex/documentos_pendientes.html", {"documentos": documentos})


@login_required(login_url="/admin/login/")
def clasificar_documento_view(request, documento_id):
    documento = get_object_or_404(Documento, pk=documento_id)
    detalles = documento.detalles.select_related("producto").order_by("id")
    pendientes = detalles.filter(estado_clasificacion=DocumentoDetalle.PENDIENTE).count()
    form = ClasificarBloqueForm()
    return render(
        request,
        "kardex/clasificar_documento.html",
        {"documento": documento, "detalles": detalles, "pendientes": pendientes, "form": form},
    )


@login_required(login_url="/admin/login/")
@require_POST
def clasificar_detalles_bloque_view(request, documento_id):
    documento = get_object_or_404(Documento, pk=documento_id)
    form = ClasificarBloqueForm(request.POST)
    detalle_ids = _post_list(request, "detalle_ids", "detalles")
    if form.is_valid():
        try:
            clasificar_detalles_bloque(documento, detalle_ids, user=request.user, **form.cleaned_data)
            messages.success(request, "Detalles clasificados correctamente.")
        except ValueError as exc:
            messages.error(request, str(exc))
    else:
        messages.error(request, "Revisa los datos del formulario de clasificacion.")
    return redirect("kardex:clasificar_documento", documento_id=documento.id)


@login_required(login_url="/admin/login/")
def comprobante_documento_view(request, documento_id):
    documento = get_object_or_404(
        Documento.objects.prefetch_related(Prefetch("detalles", queryset=DocumentoDetalle.objects.select_related("producto"))),
        pk=documento_id,
    )
    detalles = documento.detalles.all()
    subtotal = sum((detalle.subtotal for detalle in detalles), Decimal("0"))
    igv = sum((detalle.igv for detalle in detalles), Decimal("0"))
    return render(
        request,
        "kardex/comprobante_documento.html",
        {
            "documento": documento,
            "detalles": detalles,
            "subtotal": subtotal,
            "igv": igv,
        },
    )


@login_required(login_url="/admin/login/")
def clasificar_detalle_view(request, detalle_id):
    detalle = get_object_or_404(DocumentoDetalle.objects.select_related("documento", "producto"), pk=detalle_id)
    documento = detalle.documento

    initial = {"factor_conversion": detalle.factor_conversion, "producto": detalle.producto}
    form = ClasificarDetalleForm(request.POST or None, initial=initial)

    if request.method == "POST" and form.is_valid():
        try:
            clasificar_detalle(detalle, user=request.user, **form.cleaned_data)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("kardex:clasificar_documento", documento_id=documento.id)
        return redirect("kardex:clasificar_documento", documento_id=documento.id)

    return render(request, "kardex/clasificar_detalle.html", {
        "detalle": detalle,
        "documento": documento,
        "form": form
    })


@login_required(login_url="/admin/login/")
@require_POST
def excluir_detalle_kardex_view(request, detalle_id):
    detalle = get_object_or_404(DocumentoDetalle, pk=detalle_id)
    try:
        excluir_detalle_kardex(detalle, user=request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("kardex:clasificar_documento", documento_id=detalle.documento_id)


@login_required(login_url="/admin/login/")
def pre_kardex_lista_view(request):
    documentos = Documento.objects.prefetch_related("detalles").filter(estado=Documento.PRE_KARDEX).order_by("-fecha_emision", "-id")
    return render(request, "kardex/pre_kardex_lista.html", {"documentos": documentos})


@login_required(login_url="/admin/login/")
@require_POST
def confirmar_kardex_bloque_view(request):
    documento_ids = _post_list(request, "documento_ids", "documentos")
    try:
        confirmar_documentos_kardex(documento_ids, user=request.user)
        messages.success(request, "Pre-Kardex confirmado correctamente.")
    except KardexError as exc:
        messages.error(request, str(exc))
    return redirect("kardex:pre_kardex_lista")


@login_required(login_url="/admin/login/")
def pre_kardex_documento_view(request, documento_id):
    documento = get_object_or_404(Documento, pk=documento_id)
    items = generar_pre_kardex(documento)
    return render(request, "kardex/pre_kardex_documento.html", {"documento": documento, "items": items})


@login_required(login_url="/admin/login/")
@require_POST
def confirmar_kardex_documento_view(request, documento_id):
    documento = get_object_or_404(Documento, pk=documento_id)
    try:
        confirmar_documento_kardex(documento, user=request.user)
        messages.success(request, "Documento confirmado en Kardex.")
    except KardexError as exc:
        messages.error(request, str(exc))
    return redirect("kardex:pre_kardex_documento", documento_id=documento.id)


@login_required(login_url="/admin/login/")
@require_POST
def revertir_pre_kardex_view(request, documento_id):
    documento = get_object_or_404(Documento, pk=documento_id)
    try:
        revertir_pre_kardex(documento, user=request.user)
        messages.success(request, "Documento quitado de Pre-Kardex y devuelto a pendientes.")
        if request.POST.get("next") == "pre_kardex_lista":
            return redirect("kardex:pre_kardex_lista")
        return redirect("kardex:clasificar_documento", documento_id=documento.id)
    except KardexError as exc:
        messages.error(request, str(exc))
    return redirect("kardex:pre_kardex_documento", documento_id=documento.id)


@login_required(login_url="/admin/login/")
@require_POST
def revertir_aprobacion_kardex_view(request, documento_id):
    documento = get_object_or_404(Documento, pk=documento_id)
    try:
        revertir_aprobacion_kardex(documento, user=request.user)
        messages.success(request, "Aprobacion de Kardex revertida. El documento vuelve a Pre-Kardex.")
    except KardexError as exc:
        messages.error(request, str(exc))
    return redirect("kardex:pre_kardex_documento", documento_id=documento.id)


@login_required(login_url="/admin/login/")
@require_POST
def devolver_documento_pendiente_view(request, documento_id):
    documento = get_object_or_404(Documento, pk=documento_id)
    try:
        devolver_documento_a_pendiente(documento, user=request.user)
        messages.success(request, "Documento devuelto al estado pendiente de clasificacion.")
        return redirect("kardex:clasificar_documento", documento_id=documento.id)
    except KardexError as exc:
        messages.error(request, str(exc))
    return redirect("kardex:pre_kardex_documento", documento_id=documento.id)


@login_required(login_url="/admin/login/")
def stock_inicial_view(request):
    form = StockInicialForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            registrar_stock_inicial(user=request.user, **form.cleaned_data)
            messages.success(request, "Stock inicial registrado correctamente.")
            return redirect("kardex:stock_inicial")
        except KardexError as exc:
            messages.error(request, str(exc))
    stocks_iniciales = MovimientoKardex.objects.select_related("producto").filter(
        documento_origen__isnull=True,
        tipo_movimiento=MovimientoKardex.AJUSTE_ENTRADA,
        cantidad_salida=0,
    ).order_by("-fecha", "-id")
    return render(request, "kardex/stock_inicial.html", {"form": form, "stocks_iniciales": stocks_iniciales})


@login_required(login_url="/admin/login/")
def procesos_trillado_lista_view(request):
    procesos = (
        ProcesoProductivo.objects.select_related("producto_consumido")
        .prefetch_related("productos_obtenidos__producto")
        .filter(tipo_proceso=ProcesoProductivo.TRILLADO)
        .order_by("-fecha", "-id")
    )
    return render(request, "kardex/procesos_trillado_lista.html", {"procesos": procesos})


@login_required(login_url="/admin/login/")
def proceso_trillado_crear_view(request):
    form = ProcesoTrilladoForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        proceso = crear_proceso_trillado(form.cleaned_data, user=request.user)
        messages.success(request, "Proceso de trillado registrado. Revisa los calculos y confirma para afectar Kardex.")
        return redirect("kardex:proceso_trillado_detalle", proceso_id=proceso.id)
    return render(
        request,
        "kardex/proceso_trillado_form.html",
        {"form": form, "tipos_cambio_fecha": _tipos_cambio_fecha_json(), "saldos_producto": _saldos_producto_json()},
    )


@login_required(login_url="/admin/login/")
def proceso_trillado_editar_view(request, proceso_id):
    proceso = get_object_or_404(
        ProcesoProductivo.objects.prefetch_related("productos_obtenidos__producto"),
        pk=proceso_id,
        tipo_proceso=ProcesoProductivo.TRILLADO,
    )
    if proceso.anulado:
        messages.error(request, "No se pueden editar detalles de un proceso anulado.")
        return redirect("kardex:proceso_trillado_detalle", proceso_id=proceso.id)

    form = ProcesoTrilladoForm(
        request.POST or None,
        initial=_initial_proceso_trillado(proceso),
        tipo_cambio_proceso=proceso.tipo_cambio_fecha_proceso,
        fecha_proceso=proceso.fecha,
        solo_detalles=proceso.confirmado,
    )
    if request.method == "POST" and form.is_valid():
        try:
            if proceso.confirmado:
                actualizar_detalles_proceso_trillado(proceso, form.cleaned_data)
                messages.success(request, "Detalles del proceso de trillado actualizados.")
            else:
                fecha_cambio = form.cleaned_data["fecha"] != proceso.fecha
                if not fecha_cambio:
                    form.cleaned_data["tipo_cambio_fecha_proceso"] = proceso.tipo_cambio_fecha_proceso
                actualizar_proceso_trillado(proceso, form.cleaned_data)
                messages.success(request, "Proceso de trillado actualizado.")
            return redirect("kardex:proceso_trillado_detalle", proceso_id=proceso.id)
        except KardexError as exc:
            messages.error(request, str(exc))
    return render(
        request,
        "kardex/proceso_trillado_form.html",
        {
            "form": form,
            "proceso": proceso,
            "solo_detalles": proceso.confirmado,
            "tipos_cambio_fecha": _tipos_cambio_fecha_json(),
            "saldos_producto": _saldos_producto_json(),
        },
    )


@login_required(login_url="/admin/login/")
def proceso_trillado_detalle_view(request, proceso_id):
    proceso = get_object_or_404(
        ProcesoProductivo.objects.select_related("producto_consumido", "usuario_creacion", "cliente_destino_entidad")
        .prefetch_related("productos_obtenidos__producto", "movimientos_kardex__producto"),
        pk=proceso_id,
        tipo_proceso=ProcesoProductivo.TRILLADO,
    )
    return render(request, "kardex/proceso_trillado_detalle.html", {"proceso": proceso})


@login_required(login_url="/admin/login/")
@require_POST
def confirmar_proceso_trillado_view(request, proceso_id):
    proceso = get_object_or_404(ProcesoProductivo, pk=proceso_id, tipo_proceso=ProcesoProductivo.TRILLADO)
    try:
        confirmar_proceso_trillado(proceso, user=request.user)
        messages.success(request, "Proceso de trillado confirmado y Kardex actualizado.")
    except KardexError as exc:
        messages.error(request, str(exc))
    return redirect("kardex:proceso_trillado_detalle", proceso_id=proceso.id)


@login_required(login_url="/admin/login/")
@require_POST
def anular_proceso_trillado_view(request, proceso_id):
    proceso = get_object_or_404(ProcesoProductivo, pk=proceso_id, tipo_proceso=ProcesoProductivo.TRILLADO)
    try:
        anular_proceso_trillado(proceso, user=request.user)
        messages.success(request, "Proceso de trillado anulado con movimientos de reversion.")
    except KardexError as exc:
        messages.error(request, str(exc))
    return redirect("kardex:proceso_trillado_detalle", proceso_id=proceso.id)


def _initial_proceso_trillado(proceso):
    initial = {
        "fecha": proceso.fecha,
        "lote": proceso.lote,
        "factura_destino": proceso.factura_destino,
        "contrato_destino": proceso.contrato_destino,
        "cliente_destino_entidad": proceso.cliente_destino_entidad,
        "factura_relacionada": proceso.factura_relacionada,
        "fecha_factura_relacionada": proceso.fecha_factura_relacionada,
        "valor_total_destino_usd": proceso.valor_total_destino_usd,
        "tipo_cambio_destino": proceso.tipo_cambio_destino,
        "valor_total_destino_soles": proceso.valor_total_destino_soles,
        "producto_consumido": proceso.producto_consumido,
        "cantidad_consumida": proceso.cantidad_consumida,
        "kg_por_quintal": proceso.kg_por_quintal,
        "quintales_procesados": proceso.quintales_procesados,
        "costo_servicio_por_quintal_usd": proceso.costo_servicio_por_quintal_usd,
        "costo_proceso_usd": proceso.costo_proceso_usd,
        "tipo_cambio_fecha_proceso": proceso.tipo_cambio_fecha_proceso,
        "costo_proceso_soles": proceso.costo_proceso_soles,
        "costo_servicio_por_kg_usd": proceso.costo_servicio_por_kg_usd,
        "costo_servicio_por_kg_soles": proceso.costo_servicio_por_kg_soles,
        "merma": proceso.merma,
        "observaciones": proceso.observaciones,
    }
    principal = proceso.productos_obtenidos.filter(es_principal=True).first()
    if principal:
        initial["producto_exportable"] = principal.producto
        initial["cantidad_exportable"] = principal.cantidad_obtenida
        if proceso.tipo_cambio_fecha_proceso:
            initial["valor_mercado_exportable"] = (
                principal.valor_mercado_unitario_soles / proceso.tipo_cambio_fecha_proceso
            )
        else:
            initial["valor_mercado_exportable"] = principal.valor_mercado_unitario_soles
    for index, item in enumerate(proceso.productos_obtenidos.filter(es_principal=False).order_by("id")[:3], start=1):
        initial[f"subproducto_{index}"] = item.producto
        initial[f"cantidad_subproducto_{index}"] = item.cantidad_obtenida
        if proceso.tipo_cambio_fecha_proceso:
            initial[f"valor_mercado_subproducto_{index}"] = item.valor_mercado_unitario_soles / proceso.tipo_cambio_fecha_proceso
        else:
            initial[f"valor_mercado_subproducto_{index}"] = item.valor_mercado_unitario_soles
    return initial


def _tipos_cambio_fecha_json():
    return {
        f"{tipo.anio:04d}-{_mes_numero(tipo.mes):02d}-{tipo.dia:02d}": str(tipo.venta)
        for tipo in TipoCambioSunat.objects.all()
    }


def _saldos_producto_json():
    saldos = {}
    movimientos = MovimientoKardex.objects.order_by("producto_id", "fecha", "id").values(
        "producto_id",
        "fecha",
        "id",
        "stock_cantidad",
        "stock_costo_unitario_promedio",
        "stock_costo_total",
    )
    for movimiento in movimientos:
        saldos.setdefault(str(movimiento["producto_id"]), []).append(
            {
                "fecha": movimiento["fecha"].isoformat(),
                "id": movimiento["id"],
                "cantidad": str(movimiento["stock_cantidad"]),
                "promedio": str(movimiento["stock_costo_unitario_promedio"]),
                "costo_total": str(movimiento["stock_costo_total"]),
            }
        )
    return saldos


def _mes_numero(mes):
    meses = {
        "enero": 1,
        "febrero": 2,
        "marzo": 3,
        "abril": 4,
        "mayo": 5,
        "junio": 6,
        "julio": 7,
        "agosto": 8,
        "septiembre": 9,
        "octubre": 10,
        "noviembre": 11,
        "diciembre": 12,
    }
    return meses[mes]


@login_required(login_url="/admin/login/")
def tipo_cambio_sunat_view(request):
    form = TipoCambioSunatImportForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            resultado = extraer_tipo_cambio_sunat(form.cleaned_data["mes"], form.cleaned_data["anio"])
            messages.success(request, f"Tipo de cambio importado: {resultado.get('exitosos', 0)} dia(s).")
            return redirect("kardex:tipo_cambio_sunat")
        except Exception as exc:
            messages.error(request, f"No se pudo importar el tipo de cambio SUNAT: {exc}")
    tipos_cambio = TipoCambioSunat.objects.order_by("-anio", "-id")[:90]
    return render(request, "kardex/tipo_cambio_sunat.html", {"form": form, "tipos_cambio": tipos_cambio})


@staff_member_required(login_url="/admin/login/")
def mantenimiento_db_view(request):
    form = RestaurarBaseDatosForm()
    return render(request, "kardex/mantenimiento_db.html", {"form": form})


@staff_member_required(login_url="/admin/login/")
@require_POST
def backup_db_view(request):
    try:
        backup_path = crear_backup_base_datos()
    except DatabaseMaintenanceError as exc:
        messages.error(request, str(exc))
        return redirect("kardex:mantenimiento_db")

    return FileResponse(
        backup_path.open("rb"),
        as_attachment=True,
        filename=backup_path.name,
        content_type="application/vnd.sqlite3",
    )


@staff_member_required(login_url="/admin/login/")
@require_POST
def restaurar_db_view(request):
    form = RestaurarBaseDatosForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "Selecciona una base valida y confirma la restauracion.")
        return render(request, "kardex/mantenimiento_db.html", {"form": form})

    try:
        backup_path = restaurar_base_datos(form.cleaned_data["archivo"])
    except DatabaseMaintenanceError as exc:
        messages.error(request, str(exc))
        return render(request, "kardex/mantenimiento_db.html", {"form": form})

    messages.success(
        request,
        f"Base de datos restaurada correctamente. Backup previo guardado en {backup_path}.",
    )
    return redirect("kardex:mantenimiento_db")


@login_required(login_url="/admin/login/")
def editar_stock_inicial_view(request, movimiento_id):
    movimiento = get_object_or_404(MovimientoKardex.objects.select_related("producto"), pk=movimiento_id)
    initial = {
        "fecha": movimiento.fecha,
        "producto": movimiento.producto,
        "cantidad": movimiento.cantidad_entrada,
        "costo_unitario": movimiento.costo_unitario_entrada,
        "observacion": movimiento.observacion,
    }
    form = StockInicialForm(request.POST or None, initial=initial, bloquear_producto=True)
    if request.method == "POST" and form.is_valid():
        try:
            editar_stock_inicial(movimiento, user=request.user, **form.cleaned_data)
            messages.success(request, "Stock inicial actualizado correctamente.")
            return redirect("kardex:stock_inicial")
        except KardexError as exc:
            messages.error(request, str(exc))
    return render(request, "kardex/editar_stock_inicial.html", {"form": form, "movimiento": movimiento})


@login_required(login_url="/admin/login/")
def reportes_index_view(request):
    return render(request, "kardex/reportes_index.html")


@login_required(login_url="/admin/login/")
def reporte_stock_actual_view(request):
    items = obtener_stock_actual()
    total = sum((item.costo_total for item in items), 0)
    if request.GET.get("export") == "excel":
        return generar_excel_response(
            "stock_actual.xlsx",
            "Stock actual",
            ["Codigo", "Producto", "Tipo", "Unidad", "Cantidad", "Costo promedio", "Valor total"],
            [
                [
                    item.producto.codigo_interno,
                    item.producto.nombre,
                    item.producto.get_tipo_producto_display(),
                    item.producto.unidad_base,
                    item.cantidad,
                    item.costo_promedio,
                    item.costo_total,
                ]
                for item in items
            ],
            metadata=[("Stock valorizado total", total)],
        )
    return render(request, "kardex/reporte_stock_actual.html", {"items": items, "total": total})


@login_required(login_url="/admin/login/")
def reporte_kardex_producto_view(request):
    producto_id = request.GET.get("producto") or None
    productos = Producto.objects.filter(activo=True).order_by("nombre")
    movimientos = obtener_movimientos_producto(producto_id=producto_id)
    producto_seleccionado = get_object_or_404(Producto, pk=producto_id) if producto_id else None
    if request.GET.get("export") == "excel":
        return generar_excel_response(
            "kardex_producto.xlsx",
            "Kardex producto",
            [
                "Fecha",
                "Producto",
                "Documento",
                "Entidad",
                "Movimiento",
                "Entrada",
                "Costo entrada",
                "Salida",
                "Costo salida",
                "Stock",
                "Promedio",
                "Valor",
            ],
            [
                [
                    mov.fecha,
                    str(mov.producto),
                    str(mov.documento_origen) if mov.documento_origen else "",
                    str(mov.entidad) if mov.entidad else "",
                    mov.get_tipo_movimiento_display(),
                    mov.cantidad_entrada,
                    mov.costo_total_entrada,
                    mov.cantidad_salida,
                    mov.costo_total_salida,
                    mov.stock_cantidad,
                    mov.stock_costo_unitario_promedio,
                    mov.stock_costo_total,
                ]
                for mov in movimientos
            ],
            metadata=[("Producto", str(producto_seleccionado) if producto_seleccionado else "Todos")],
        )
    return render(request, "kardex/reporte_kardex_producto.html", {"productos": productos, "producto_seleccionado": producto_seleccionado, "movimientos": movimientos})


@login_required(login_url="/admin/login/")
def reporte_kardex_sunat_producto_view(request):
    producto_id = request.GET.get("producto") or None
    fecha_inicio_raw = request.GET.get("fecha_inicio") or ""
    fecha_fin_raw = request.GET.get("fecha_fin") or ""
    mes_raw = request.GET.get("mes") or ""
    anio_raw = request.GET.get("anio") or ""
    fecha_inicio = parse_date(fecha_inicio_raw) if fecha_inicio_raw else None
    fecha_fin = parse_date(fecha_fin_raw) if fecha_fin_raw else None
    fecha_inicio, fecha_fin, periodo_label = _periodo_kardex_sunat(
        fecha_inicio,
        fecha_fin,
        fecha_inicio_raw,
        fecha_fin_raw,
        mes_raw,
        anio_raw,
    )
    productos = Producto.objects.filter(activo=True, controla_stock=True).order_by("nombre")
    producto_seleccionado = get_object_or_404(Producto, pk=producto_id) if producto_id else None
    filas = obtener_kardex_sunat_producto(producto_seleccionado, fecha_inicio, fecha_fin) if producto_seleccionado else []
    empresa = obtener_empresa_principal()
    if request.GET.get("export") == "excel":
        return generar_excel_response(
            "kardex_valorizado_sunat.xlsx",
            "Formato 13.1",
            [
                "Fecha",
                "Tipo documento",
                "Serie",
                "Numero",
                "Tipo operacion",
                "Entrada cantidad",
                "Entrada costo unitario",
                "Entrada costo total",
                "Salida cantidad",
                "Salida costo unitario",
                "Salida costo total",
                "Saldo cantidad",
                "Saldo costo unitario",
                "Saldo costo total",
            ],
            [
                [
                    fila.movimiento.fecha,
                    fila.tipo_documento,
                    fila.serie,
                    fila.numero,
                    fila.tipo_operacion,
                    fila.movimiento.cantidad_entrada,
                    fila.movimiento.costo_unitario_entrada,
                    fila.movimiento.costo_total_entrada,
                    fila.movimiento.cantidad_salida,
                    fila.movimiento.costo_unitario_salida,
                    fila.movimiento.costo_total_salida,
                    fila.movimiento.stock_cantidad,
                    fila.movimiento.stock_costo_unitario_promedio,
                    fila.movimiento.stock_costo_total,
                ]
                for fila in filas
            ],
            metadata=[
                ("Formato", "13.1 Registro de Inventario Permanente Valorizado"),
                ("Periodo", periodo_label),
                ("RUC", empresa.ruc if empresa else ""),
                ("Razon social", empresa.razon_social if empresa else ""),
                ("Producto", str(producto_seleccionado) if producto_seleccionado else ""),
            ],
        )
    return render(
        request,
        "kardex/reporte_kardex_sunat_producto.html",
        {
            "empresa": empresa,
            "productos": productos,
            "producto_seleccionado": producto_seleccionado,
            "filas": filas,
            "fecha_inicio": fecha_inicio_raw,
            "fecha_fin": fecha_fin_raw,
            "mes": mes_raw,
            "mes_seleccionado": _parse_int(mes_raw),
            "anio": anio_raw or date.today().year,
            "meses_reporte": MESES_NOMBRE.items(),
            "periodo_label": periodo_label,
        },
    )


def _periodo_kardex_sunat(fecha_inicio, fecha_fin, fecha_inicio_raw, fecha_fin_raw, mes_raw, anio_raw):
    mes = _parse_int(mes_raw)
    anio = _parse_int(anio_raw)
    if mes and 1 <= mes <= 12 and anio:
        primer_dia = date(anio, mes, 1)
        ultimo_dia = date(anio, mes, monthrange(anio, mes)[1])
        periodo_label = f"{MESES_NOMBRE[mes]} {anio} ({primer_dia:%Y-%m-%d} al {ultimo_dia:%Y-%m-%d})"
        return primer_dia, ultimo_dia, periodo_label

    if fecha_inicio or fecha_fin:
        return fecha_inicio, fecha_fin, f"{fecha_inicio_raw or '...'} al {fecha_fin_raw or '...'}"

    return fecha_inicio, fecha_fin, "Todos los movimientos"


def _parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


CATEGORIAS_REPORTE_MENSUAL_KG = [
    {
        "key": "per",
        "label": "PER - CAFE PERGAMINO CONVENCIONAL",
        "prefix": "PER",
        "proc_header": "Proc. salida",
        "proc_attr": "proc_salida",
    },
    {
        "key": "exp",
        "label": "EXP - CAFE EXPORTABLE",
        "prefix": "EXP",
        "proc_header": "Proc. ingreso",
        "proc_attr": "proc_ingreso",
    },
    {
        "key": "sub",
        "label": "SUB - CAFE SUBPRODUCTOS",
        "prefix": "SUB",
        "proc_header": "Proc. ingreso",
        "proc_attr": "proc_ingreso",
    },
]


@login_required(login_url="/admin/login/")
def reporte_mensual_kardex_kg_view(request):
    anio = _parse_int(request.GET.get("anio")) or date.today().year
    categorias_seleccionadas = _categorias_reporte_mensual_kardex(request)
    items, totales = obtener_reporte_mensual_kardex_kg(anio)
    if request.GET.get("export") == "excel":
        return generar_excel_response(
            f"reporte_mensual_kardex_kg_{anio}.xlsx",
            "Mensual KG",
            _headers_reporte_mensual_kardex_excel(categorias_seleccionadas),
            [_fila_reporte_mensual_kardex_excel(item, categorias_seleccionadas) for item in items]
            + [_fila_reporte_mensual_kardex_excel(totales, categorias_seleccionadas, total=True)],
            metadata=[
                ("Reporte", "Ingresos, salidas y saldo final (KG)"),
                ("Anio", anio),
                ("Categorias", " / ".join(categoria["label"] for categoria in categorias_seleccionadas)),
            ],
        )
    return render(
        request,
        "kardex/reporte_mensual_kardex_kg.html",
        {
            "anio": anio,
            "items": items,
            "totales": totales,
            "categorias_reporte": CATEGORIAS_REPORTE_MENSUAL_KG,
            "categorias_seleccionadas": [categoria["key"] for categoria in categorias_seleccionadas],
            "mostrar_per": any(categoria["key"] == "per" for categoria in categorias_seleccionadas),
            "mostrar_exp": any(categoria["key"] == "exp" for categoria in categorias_seleccionadas),
            "mostrar_sub": any(categoria["key"] == "sub" for categoria in categorias_seleccionadas),
        },
    )


def _categorias_reporte_mensual_kardex(request):
    seleccionadas = request.GET.getlist("categorias")
    categorias_validas = {categoria["key"] for categoria in CATEGORIAS_REPORTE_MENSUAL_KG}
    if not seleccionadas:
        seleccionadas = [categoria["key"] for categoria in CATEGORIAS_REPORTE_MENSUAL_KG]
    seleccionadas = [key for key in seleccionadas if key in categorias_validas]
    if not seleccionadas:
        seleccionadas = [categoria["key"] for categoria in CATEGORIAS_REPORTE_MENSUAL_KG]
    return [categoria for categoria in CATEGORIAS_REPORTE_MENSUAL_KG if categoria["key"] in seleccionadas]


def _headers_reporte_mensual_kardex_excel(categorias):
    headers = ["N", "Mes"]
    for categoria in categorias:
        prefix = categoria["prefix"]
        headers.extend(
            [
                f"{prefix} Compras",
                f"{prefix} Ventas",
                f"{prefix} Ajuste +",
                f"{prefix} Ajuste -",
                f"{prefix} {categoria['proc_header']}",
                f"{prefix} Saldo final",
            ]
        )
    return headers


def _fila_reporte_mensual_kardex_excel(item, categorias, total=False):
    fila = ["" if total else item.numero, item.mes_nombre]
    for categoria_def in categorias:
        categoria = getattr(item, categoria_def["key"])
        fila.extend(
            [
                categoria.compras,
                categoria.ventas,
                categoria.ajuste_positivo,
                categoria.ajuste_negativo,
                getattr(categoria, categoria_def["proc_attr"]),
                categoria.saldo_final,
            ]
        )
    return fila


@login_required(login_url="/admin/login/")
def reporte_documentos_mensual_view(request):
    filtros = _filtros_documentos_mensual(request)
    items = obtener_documentos_mensual(**filtros["valores"])
    query_params = request.GET.copy()
    query_params.pop("export", None)
    for item in items:
        detalle_params = query_params.copy()
        item.detalle_query = detalle_params.urlencode()

    if request.GET.get("export") == "excel":
        return generar_excel_response(
            "documentos_por_mes.xlsx",
            "Documentos por mes",
            [
                "Anio",
                "Mes",
                "Facturas de venta",
                "Facturas de compra",
                "Liquidaciones de compra",
                "Total documentos",
                "Total ventas",
                "Total compras",
                "Total liquidaciones",
                "Total general",
            ],
            [
                [
                    item.anio,
                    item.mes_nombre,
                    item.facturas_venta,
                    item.facturas_compra,
                    item.liquidaciones_compra,
                    item.total_documentos,
                    item.total_ventas,
                    item.total_compras,
                    item.total_liquidaciones,
                    item.total_general,
                ]
                for item in items
            ],
            metadata=_metadata_documentos_mensual(filtros),
        )

    return render(
        request,
        "kardex/reporte_documentos_mensual.html",
        {
            "items": items,
            **filtros["context"],
        },
    )


@login_required(login_url="/admin/login/")
def reporte_documentos_mensual_detalle_view(request, anio, mes):
    filtros = _filtros_documentos_mensual(request)
    documentos = obtener_documentos_mensual_detalle(anio, mes, **filtros["valores"])
    filas = [_fila_detalle_documento_mensual(documento) for documento in documentos]
    mes_nombre = {
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
    }.get(mes, str(mes))

    if request.GET.get("export") == "excel":
        return generar_excel_response(
            f"documentos_{anio}_{mes:02d}.xlsx",
            f"{anio}-{mes:02d}",
            [
                "Fecha emision",
                "Tipo operacion",
                "Tipo documento",
                "Serie",
                "Numero",
                "RUC entidad",
                "Nombre entidad",
                "Moneda",
                "Base imponible",
                "IGV",
                "Total",
                "Estado",
            ],
            [
                [
                    fila["documento"].fecha_emision,
                    fila["documento"].tipo_operacion_nombre,
                    fila["documento"].tipo_documento_nombre,
                    fila["documento"].serie,
                    fila["documento"].numero,
                    fila["entidad"].numero_documento if fila["entidad"] else "",
                    fila["entidad"].razon_social if fila["entidad"] else "",
                    fila["documento"].moneda_mostrada,
                    fila["base_imponible"],
                    fila["igv"],
                    fila["documento"].total,
                    fila["documento"].get_estado_display(),
                ]
                for fila in filas
            ],
            metadata=[("Periodo", f"{mes_nombre} {anio}"), *_metadata_documentos_mensual(filtros)],
        )

    query_params = request.GET.copy()
    query_params.pop("export", None)
    return render(
        request,
        "kardex/reporte_documentos_mensual_detalle.html",
        {
            "anio": anio,
            "mes": mes,
            "mes_nombre": mes_nombre,
            "filas": filas,
            "querystring": query_params.urlencode(),
            **filtros["context"],
        },
    )


def _filtros_documentos_mensual(request):
    fecha_desde_raw = request.GET.get("fecha_desde") or ""
    fecha_hasta_raw = request.GET.get("fecha_hasta") or ""
    tipo_operacion = request.GET.get("tipo_operacion") or ""
    tipo_documento = request.GET.get("tipo_documento") or ""
    entidad_id = request.GET.get("entidad") or ""
    estado = request.GET.get("estado") or ""
    fecha_desde = parse_date(fecha_desde_raw) if fecha_desde_raw else None
    fecha_hasta = parse_date(fecha_hasta_raw) if fecha_hasta_raw else None

    return {
        "valores": {
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "tipo_operacion": tipo_operacion or None,
            "tipo_documento": tipo_documento or None,
            "entidad_id": entidad_id or None,
            "estado": estado or None,
        },
        "context": {
            "fecha_desde": fecha_desde_raw,
            "fecha_hasta": fecha_hasta_raw,
            "tipo_operacion": tipo_operacion,
            "tipo_documento": tipo_documento,
            "entidad_id": entidad_id,
            "estado": estado,
            "entidades": Entidad.objects.order_by("razon_social"),
            "estados": Documento.ESTADO_CHOICES,
            "tipos_operacion": [
                (Documento.COMPRA, "Compra"),
                (Documento.VENTA, "Venta"),
            ],
            "tipos_documento": [
                (Documento.FACTURA, "Factura"),
                (Documento.LIQUIDACION_COMPRA, "Liquidacion de compra"),
            ],
        },
    }


def _metadata_documentos_mensual(filtros):
    context = filtros["context"]
    return [
        ("Fecha desde", context["fecha_desde"] or "Todos"),
        ("Fecha hasta", context["fecha_hasta"] or "Todos"),
        ("Tipo operacion", context["tipo_operacion"] or "Todos"),
        ("Tipo documento", context["tipo_documento"] or "Todos"),
        ("Entidad", context["entidad_id"] or "Todas"),
        ("Estado", context["estado"] or "Todos excepto anulados"),
    ]


def _fila_detalle_documento_mensual(documento):
    detalles = list(documento.detalles.all())
    return {
        "documento": documento,
        "entidad": entidad_documento_reporte(documento),
        "base_imponible": sum((detalle.subtotal for detalle in detalles), Decimal("0")),
        "igv": sum((detalle.igv for detalle in detalles), Decimal("0")),
    }


@login_required(login_url="/admin/login/")
def reporte_documentos_importados_view(request):
    estado = request.GET.get("estado") or None
    documentos = obtener_documentos_importados()
    if estado:
        documentos = documentos.filter(estado=estado)
    if request.GET.get("export") == "excel":
        return generar_excel_response(
            "documentos_importados.xlsx",
            "Documentos",
            ["Documento", "Fecha", "Operacion", "Entidad", "Estado", "Total"],
            [
                [
                    str(doc),
                    doc.fecha_emision,
                    doc.tipo_operacion_nombre,
                    str(doc.proveedor or doc.cliente or doc.entidad_emisor),
                    doc.get_estado_display(),
                    doc.total,
                ]
                for doc in documentos
            ],
            metadata=[("Estado", estado or "Todos")],
        )
    return render(request, "kardex/reporte_documentos_importados.html", {"documentos": documentos, "estado": estado, "estados": Documento.ESTADO_CHOICES})


@login_required(login_url="/admin/login/")
def reporte_movimientos_documento_view(request):
    filtros = _filtros_movimientos_documento(request)
    documentos = Documento.objects.order_by("-fecha_emision", "-id")
    movimientos = obtener_movimientos_documento(**filtros["valores"])
    sort_headers = _sort_headers_movimientos_documento(request, filtros["sort"], filtros["order"])
    monedas = Documento.objects.exclude(moneda="").values_list("moneda", flat=True).distinct().order_by("moneda")
    documento_id = filtros["context"]["documento_id"]
    documento_seleccionado = get_object_or_404(Documento, pk=documento_id) if documento_id else None
    if request.GET.get("export") == "excel":
        return generar_excel_response(
            "movimientos_documento.xlsx",
            "Movimientos",
            [
                "Documento",
                "Tipo documento",
                "Fecha",
                "Entidad",
                "Producto",
                "Movimiento",
                "Moneda",
                "Entrada",
                "Salida",
                "Costo entrada",
                "Costo salida",
                "Stock final",
            ],
            [
                [
                    str(mov.documento_origen) if mov.documento_origen else "",
                    mov.documento_origen.tipo_documento_nombre if mov.documento_origen else "",
                    mov.fecha,
                    str(mov.entidad) if mov.entidad else "",
                    str(mov.producto),
                    mov.get_tipo_movimiento_display(),
                    mov.documento_origen.moneda_mostrada if mov.documento_origen else "",
                    mov.cantidad_entrada,
                    mov.cantidad_salida,
                    mov.costo_total_entrada,
                    mov.costo_total_salida,
                    mov.stock_cantidad,
                ]
                for mov in movimientos
            ],
            metadata=_metadata_movimientos_documento(filtros, documento_seleccionado),
        )
    return render(
        request,
        "kardex/reporte_movimientos_documento.html",
        {
            "documentos": documentos,
            "documento_seleccionado": documento_seleccionado,
            "movimientos": movimientos,
            "sort_headers": sort_headers,
            "sort": filtros["sort"],
            "order": filtros["order"],
            "monedas": monedas,
            "tipos_documento": [
                (Documento.FACTURA, "Factura"),
                (Documento.LIQUIDACION_COMPRA, "Liquidacion de compra"),
            ],
            **filtros["context"],
        },
    )


def _filtros_movimientos_documento(request):
    documento_id = request.GET.get("documento") or ""
    fecha_desde_raw = request.GET.get("fecha_desde") or ""
    fecha_hasta_raw = request.GET.get("fecha_hasta") or ""
    tipo_documento = request.GET.get("tipo_documento") or ""
    moneda = request.GET.get("moneda") or ""
    sort = request.GET.get("sort") or "fecha"
    order = request.GET.get("order") or "asc"
    fecha_desde = parse_date(fecha_desde_raw) if fecha_desde_raw else None
    fecha_hasta = parse_date(fecha_hasta_raw) if fecha_hasta_raw else None
    ordering = _ordering_movimientos_documento(sort, order)

    return {
        "valores": {
            "documento_id": documento_id or None,
            "fecha_desde": fecha_desde,
            "fecha_hasta": fecha_hasta,
            "tipo_documento": tipo_documento or None,
            "moneda": moneda or None,
            "ordering": ordering,
        },
        "context": {
            "documento_id": documento_id,
            "fecha_desde": fecha_desde_raw,
            "fecha_hasta": fecha_hasta_raw,
            "tipo_documento": tipo_documento,
            "moneda": moneda,
        },
        "sort": sort,
        "order": order if order in {"asc", "desc"} else "asc",
    }


def _ordering_movimientos_documento(sort, order):
    allowed = {
        "documento": ["documento_origen__serie", "documento_origen__numero", "id"],
        "tipo_documento": ["documento_origen__tipo_documento", "id"],
        "fecha": ["fecha", "id"],
        "entidad": ["entidad__razon_social", "id"],
        "producto": ["producto__nombre", "id"],
        "movimiento": ["tipo_movimiento", "id"],
        "moneda": ["documento_origen__moneda", "id"],
        "entrada": ["cantidad_entrada", "id"],
        "salida": ["cantidad_salida", "id"],
        "costo_entrada": ["costo_total_entrada", "id"],
        "costo_salida": ["costo_total_salida", "id"],
        "stock": ["stock_cantidad", "id"],
    }
    fields = allowed.get(sort, allowed["fecha"])
    if order == "desc":
        return [f"-{field}" for field in fields]
    return fields


def _sort_headers_movimientos_documento(request, current_sort, current_order):
    columns = [
        ("documento", "Documento", ""),
        ("tipo_documento", "Tipo doc.", ""),
        ("fecha", "Fecha", ""),
        ("entidad", "Entidad", ""),
        ("producto", "Producto", ""),
        ("movimiento", "Movimiento", ""),
        ("moneda", "Moneda", ""),
        ("entrada", "Entrada", "text-end"),
        ("salida", "Salida", "text-end"),
        ("costo_entrada", "Costo entrada", "text-end"),
        ("costo_salida", "Costo salida", "text-end"),
        ("stock", "Stock final", "text-end"),
    ]
    query_params = request.GET.copy()
    query_params.pop("export", None)
    headers = []
    for key, label, css_class in columns:
        params = query_params.copy()
        next_order = "desc" if current_sort == key and current_order == "asc" else "asc"
        params["sort"] = key
        params["order"] = next_order
        headers.append(
            {
                "label": label,
                "css_class": css_class,
                "url": f"?{params.urlencode()}",
                "active": current_sort == key,
                "direction": "↑" if current_order == "asc" else "↓",
            }
        )
    return headers


def _metadata_movimientos_documento(filtros, documento_seleccionado):
    context = filtros["context"]
    tipo_documento_label = dict(
        [
            (Documento.FACTURA, "Factura"),
            (Documento.LIQUIDACION_COMPRA, "Liquidacion de compra"),
        ]
    ).get(context["tipo_documento"], "Todos")
    return [
        ("Documento", str(documento_seleccionado) if documento_seleccionado else "Todos"),
        ("Fecha desde", context["fecha_desde"] or "Todos"),
        ("Fecha hasta", context["fecha_hasta"] or "Todos"),
        ("Tipo documento", tipo_documento_label),
        ("Moneda", context["moneda"] or "Todas"),
    ]
