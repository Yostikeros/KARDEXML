from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
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
    StockInicialForm,
    TipoCambioSunatImportForm,
)
from .models import Documento, DocumentoDetalle, Entidad, MovimientoKardex, Producto, ProductoEquivalencia, TipoCambioSunat
from .services.clasificacion import (
    clasificar_detalle,
    clasificar_detalles_bloque,
    clasificar_documentos_bloque,
    excluir_detalle_kardex,
    generar_pre_kardex,
)
from .services.dashboard import obtener_analisis_compras_ventas
from .services.excel import generar_excel_response
from .services.kardex import (
    KardexError,
    confirmar_documento_kardex,
    confirmar_documentos_kardex,
    editar_stock_inicial,
    registrar_stock_inicial,
    revertir_aprobacion_kardex,
    revertir_pre_kardex,
)
from .services.reportes import (
    obtener_empresa_principal,
    obtener_documentos_importados,
    obtener_kardex_sunat_producto,
    obtener_movimientos_documento,
    obtener_movimientos_producto,
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
    documento_busqueda = (request.GET.get("documento") or "").strip()
    if tipo_documento:
        documentos = documentos.filter(tipo_documento=tipo_documento)
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
            "documento_busqueda": documento_busqueda,
            "tipos_documento": Documento.TIPO_DOCUMENTO_LABELS.items(),
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
    fecha_inicio = parse_date(fecha_inicio_raw) if fecha_inicio_raw else None
    fecha_fin = parse_date(fecha_fin_raw) if fecha_fin_raw else None
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
                ("Periodo", f"{fecha_inicio_raw or '...'} al {fecha_fin_raw or '...'}"),
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
        },
    )


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
    documento_id = request.GET.get("documento") or None
    documentos = Documento.objects.order_by("-fecha_emision", "-id")
    movimientos = obtener_movimientos_documento(documento_id=documento_id)
    documento_seleccionado = get_object_or_404(Documento, pk=documento_id) if documento_id else None
    if request.GET.get("export") == "excel":
        return generar_excel_response(
            "movimientos_documento.xlsx",
            "Movimientos",
            ["Documento", "Fecha", "Entidad", "Producto", "Movimiento", "Entrada", "Salida", "Costo entrada", "Costo salida", "Stock final"],
            [
                [
                    str(mov.documento_origen) if mov.documento_origen else "",
                    mov.fecha,
                    str(mov.entidad) if mov.entidad else "",
                    str(mov.producto),
                    mov.get_tipo_movimiento_display(),
                    mov.cantidad_entrada,
                    mov.cantidad_salida,
                    mov.costo_total_entrada,
                    mov.costo_total_salida,
                    mov.stock_cantidad,
                ]
                for mov in movimientos
            ],
            metadata=[("Documento", str(documento_seleccionado) if documento_seleccionado else "Todos")],
        )
    return render(request, "kardex/reporte_movimientos_documento.html", {"documentos": documentos, "documento_seleccionado": documento_seleccionado, "movimientos": movimientos})
