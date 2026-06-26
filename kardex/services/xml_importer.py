import hashlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction

from kardex.services.tipo_cambio import obtener_tc_venta_sunat
from kardex.services.unidades import (
    FACTOR_LIBRA_A_KG,
    inferir_cantidad_quintal_kg,
    inferir_cantidad_kg_descripcion,
    normalizar_unidad,
    normalizar_cantidad_kg,
    resolver_factor_conversion,
)

from kardex.models import (
    Auditoria,
    Documento,
    DocumentoDetalle,
    EmpresaPrincipal,
    Entidad,
    ProductoEquivalencia,
    UnidadConversion,
)


class XMLImportError(Exception):
    pass


@dataclass
class ImportResult:
    filename: str
    ok: bool
    message: str
    documento: Documento | None = None
    detalles_creados: int = 0
    entidades_creadas: int = 0
    entidades_actualizadas: int = 0
    pendientes_clasificacion: int = 0
    warnings: list[str] = field(default_factory=list)


def importar_xml_lote(files, user=None):
    resultados = []
    for uploaded_file in files:
        filename = getattr(uploaded_file, 'name', 'archivo.xml')
        try:
            content = uploaded_file.read()
            resultado = importar_xml(content, filename=filename, user=user)
        except Exception as exc:
            resultado = ImportResult(
                filename=filename,
                ok=False,
                message=str(exc),
            )
        resultados.append(resultado)
    return resultados


@transaction.atomic
def importar_xml(content, filename='archivo.xml', user=None):
    if not content:
        raise XMLImportError('El archivo esta vacio.')

    xml_hash = hashlib.sha256(content).hexdigest()
    if Documento.objects.filter(xml_hash=xml_hash).exists():
        raise XMLImportError('XML duplicado: ya existe un documento con el mismo hash.')

    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise XMLImportError(f'XML invalido: {exc}') from exc

    empresas = list(EmpresaPrincipal.objects.filter(activo=True))
    if not empresas:
        raise XMLImportError('Configura primero una Empresa principal activa.')

    datos = _parse_documento(root)
    empresa = _resolver_empresa(empresas, datos)
    tipo_operacion = _resolver_tipo_operacion(datos, empresa)
    es_liquidacion_compra = datos['tipo_documento'] == Documento.LIQUIDACION_COMPRA
    liquidacion_proveedor_es_receptor = (
        es_liquidacion_compra and datos['emisor']['numero_documento'] == empresa.ruc
    )
    liquidacion_proveedor_es_emisor = (
        es_liquidacion_compra and datos['receptor']['numero_documento'] == empresa.ruc
    )

    entidad_emisor, emisor_created, emisor_updated = _crear_o_actualizar_entidad(
        datos['emisor'],
        es_cliente=tipo_operacion in [Documento.NOTA_CREDITO_COMPRA],
        es_proveedor=tipo_operacion == Documento.COMPRA and (
            not es_liquidacion_compra or liquidacion_proveedor_es_emisor
        ),
    )
    entidad_receptor, receptor_created, receptor_updated = _crear_o_actualizar_entidad(
        datos['receptor'],
        es_cliente=tipo_operacion == Documento.VENTA,
        es_proveedor=tipo_operacion == Documento.COMPRA and liquidacion_proveedor_es_receptor,
    )

    proveedor = None
    cliente = None
    if tipo_operacion == Documento.COMPRA:
        if es_liquidacion_compra:
            proveedor = entidad_receptor if liquidacion_proveedor_es_receptor else entidad_emisor
        else:
            proveedor = entidad_emisor
    elif tipo_operacion == Documento.VENTA:
        cliente = entidad_receptor

    if Documento.objects.filter(
        tipo_documento=datos['tipo_documento'],
        serie=datos['serie'],
        numero=datos['numero'],
        entidad_emisor=entidad_emisor,
        entidad_receptor=entidad_receptor,
    ).exists():
        raise XMLImportError('Documento duplicado: coincide tipo, serie, numero, emisor y receptor.')

    documento = Documento.objects.create(
        tipo_documento=datos['tipo_documento'],
        serie=datos['serie'],
        numero=datos['numero'],
        fecha_emision=datos['fecha_emision'],
        entidad_emisor=entidad_emisor,
        entidad_receptor=entidad_receptor,
        proveedor=proveedor,
        cliente=cliente,
        tipo_operacion=tipo_operacion,
        moneda=datos['moneda'],
        tipo_cambio=datos['tipo_cambio'],
        total=datos['total'],
        xml_hash=xml_hash,
        estado=Documento.IMPORTADO,
        usuario_creacion=user if getattr(user, 'is_authenticated', False) else None,
    )

    pendientes = 0
    detalles_creados = 0
    entidad_documento = proveedor or cliente
    for item in datos['detalles']:
        detalle = _crear_detalle(documento, item, entidad_documento)
        detalles_creados += 1
        if detalle.estado_clasificacion == DocumentoDetalle.PENDIENTE:
            pendientes += 1

    documento.estado = Documento.PENDIENTE_CLASIFICACION if pendientes else Documento.PRE_KARDEX
    documento.save(update_fields=['estado', 'fecha_actualizacion'])

    Auditoria.objects.create(
        usuario=user if getattr(user, 'is_authenticated', False) else None,
        accion='importacion_xml',
        modelo_afectado='Documento',
        registro_id=str(documento.id),
        descripcion=f'Importacion XML lote: {filename}. Documento {documento}.',
    )

    return ImportResult(
        filename=filename,
        ok=True,
        message='Importado correctamente.',
        documento=documento,
        detalles_creados=detalles_creados,
        entidades_creadas=int(emisor_created) + int(receptor_created),
        entidades_actualizadas=int(emisor_updated) + int(receptor_updated),
        pendientes_clasificacion=pendientes,
    )


def _parse_documento(root):
    tipo_documento = _direct_text(root, 'InvoiceTypeCode') or _direct_text(root, 'CreditNoteTypeCode')
    if not tipo_documento:
        raise XMLImportError('No se encontro el tipo de documento SUNAT.')

    document_id = _required_direct_text(root, 'ID', 'No se encontro la serie-numero del documento.')
    serie, numero = _split_serie_numero(document_id)
    fecha_emision = _parse_date(_required_direct_text(root, 'IssueDate', 'No se encontro la fecha de emision.'))
    moneda = _parse_moneda(root)
    total = _decimal(_text(_direct_first(root, 'LegalMonetaryTotal'), 'PayableAmount') or '0')
    tipo_cambio = _parse_tipo_cambio(root)

    supplier = _required_direct_first(root, 'AccountingSupplierParty', 'No se encontro el emisor.')
    customer = _required_direct_first(root, 'AccountingCustomerParty', 'No se encontro el receptor.')

    detalles = []
    line_nodes = _children(root, 'InvoiceLine') or _children(root, 'CreditNoteLine')
    for line in line_nodes:
        detalles.append(_parse_detalle(line))

    moneda = _normalizar_moneda(moneda)
    tipo_cambio = _resolver_tipo_cambio_moneda(moneda, fecha_emision, tipo_cambio)
    if tipo_cambio:
        total = _convertir_moneda(total, tipo_cambio)
        detalles = [_convertir_importes_detalle(detalle, tipo_cambio) for detalle in detalles]

    if not detalles:
        raise XMLImportError('El XML no contiene lineas de detalle.')

    return {
        'tipo_documento': tipo_documento.strip(),
        'serie': serie,
        'numero': numero,
        'fecha_emision': fecha_emision,
        'moneda': moneda,
        'tipo_cambio': tipo_cambio,
        'total': total,
        'emisor': _parse_party(supplier, tipo_documento=tipo_documento.strip(), rol='emisor'),
        'receptor': _parse_party(customer, tipo_documento=tipo_documento.strip(), rol='receptor'),
        'detalles': detalles,
    }

def _resolver_tipo_cambio_moneda(moneda, fecha_emision, tipo_cambio_xml):
    if moneda == 'PEN':
        return None
    if tipo_cambio_xml:
        return tipo_cambio_xml
    tipo_cambio = obtener_tc_venta_sunat(fecha_emision)
    if tipo_cambio is None:
        raise XMLImportError(
            f'No existe tipo de cambio SUNAT venta para {fecha_emision:%Y-%m-%d}. '
            'Importalo antes de cargar documentos en moneda extranjera.'
        )
    return tipo_cambio


def _convertir_moneda(value, tipo_cambio):
    return Decimal(value) * Decimal(tipo_cambio)


def _convertir_importes_detalle(detalle, tipo_cambio):
    detalle = detalle.copy()
    for field in ['valor_unitario', 'precio_unitario', 'subtotal', 'igv', 'total']:
        detalle[field] = _convertir_moneda(detalle[field], tipo_cambio)
    return detalle

def _parse_moneda(root):
    moneda_node = _direct_first(root, 'DocumentCurrencyCode')
    monetary_total = _direct_first(root, 'LegalMonetaryTotal')
    payable_amount = _first(monetary_total, 'PayableAmount')

    candidates = [
        _node_text(moneda_node),
        _attr(moneda_node, 'currencyID'),
        _attr(payable_amount, 'currencyID'),
    ]
    for line in _children(root, 'InvoiceLine') or _children(root, 'CreditNoteLine'):
        candidates.append(_attr(_first(line, 'LineExtensionAmount'), 'currencyID'))
        candidates.append(_attr(_first(_first(line, 'TaxTotal'), 'TaxAmount'), 'currencyID'))
        candidates.append(_attr(_first(_first(line, 'Price'), 'PriceAmount'), 'currencyID'))

    for candidate in candidates:
        moneda = _normalizar_moneda(candidate)
        if moneda:
            return moneda
    return 'PEN'


def _normalizar_moneda(value):
    value = (value or '').strip().upper()
    if value in {'PEN', 'USD', 'EUR'}:
        return value
    return ''


def _parse_party(node, tipo_documento=None, rol=None):
    party = _first(node, 'Party') or node
    numero = (
        _text(_first(party, 'PartyIdentification'), 'ID')
        or _text(_first(party, 'PartyLegalEntity'), 'CompanyID')
        or _text(party, 'CustomerAssignedAccountID')
        or ''
    ).strip()
    razon_social = (
        _text(_first(party, 'PartyLegalEntity'), 'RegistrationName')
        or _text(_first(party, 'PartyName'), 'Name')
        or numero
    ).strip()
    direccion_node = _first(_first(party, 'PartyLegalEntity'), 'RegistrationAddress')
    if direccion_node is None:
        direccion_node = _first(party, 'PostalAddress')

    identification_node = _first(_first(party, 'PartyIdentification'), 'ID')
    company_node = _first(_first(party, 'PartyLegalEntity'), 'CompanyID')
    customer_account_node = _first(party, 'CustomerAssignedAccountID')
    tipo_doc = (
        _attr(identification_node, 'schemeID')
        or _attr(company_node, 'schemeID')
        or _attr(customer_account_node, 'schemeID')
        or _inferir_tipo_documento_identidad(numero, tipo_documento=tipo_documento, rol=rol)
    )
    direccion = _text(direccion_node, 'Line') or _text(direccion_node, 'StreetName') or ''

    if not numero:
        raise XMLImportError(f'Entidad sin numero de documento: {razon_social}')

    return {
        'tipo_documento_identidad': _normalizar_tipo_documento(
            tipo_doc,
            numero=numero,
            tipo_documento=tipo_documento,
            rol=rol,
        ),
        'numero_documento': numero,
        'razon_social': razon_social,
        'nombre_comercial': _text(_first(party, 'PartyName'), 'Name') or '',
        'direccion': direccion,
        'ubigeo': _text(direccion_node, 'ID') or '',
        'departamento': _text(direccion_node, 'CountrySubentity') or '',
        'provincia': _text(direccion_node, 'CityName') or '',
        'distrito': _text(direccion_node, 'District') or '',
        'pais': _text(_first(direccion_node, 'Country'), 'IdentificationCode') or 'PE',
    }


def _parse_detalle(line):
    quantity_node = _first(line, 'InvoicedQuantity')
    if quantity_node is None:
        quantity_node = _first(line, 'CreditedQuantity')
    item_node = _first(line, 'Item')
    price_node = _first(line, 'Price')
    pricing_ref = _first(line, 'PricingReference')
    alt_price = _first(_first(pricing_ref, 'AlternativeConditionPrice'), 'PriceAmount')

    descripcion = _text(item_node, 'Description') or 'Producto sin descripcion'
    unidad = normalizar_unidad(_attr(quantity_node, 'unitCode') or 'NIU')
    cantidad = _decimal(_node_text(quantity_node) or '0')
    cantidad_kg = inferir_cantidad_quintal_kg(descripcion, cantidad)
    if cantidad_kg is None:
        cantidad_kg = inferir_cantidad_kg_descripcion(descripcion)
    if unidad in {'NIU', 'UND'} and cantidad_kg:
        unidad = 'KG'
        cantidad = cantidad_kg

    subtotal = _decimal(_text(line, 'LineExtensionAmount') or '0')
    igv = _decimal(_text(_first(line, 'TaxTotal'), 'TaxAmount') or '0')
    total = subtotal + igv
    valor_unitario = _decimal(_text(price_node, 'PriceAmount') or '0')
    precio_unitario = _decimal(_node_text(alt_price) or _text(price_node, 'PriceAmount') or '0')
    if cantidad > 0:
        if valor_unitario <= 0 and subtotal:
            valor_unitario = _dividir_decimal(subtotal, cantidad)
        if precio_unitario <= 0:
            precio_unitario = _dividir_decimal(total if total else subtotal, cantidad)

    return {
        'codigo_producto_xml': (
            _text(_first(item_node, 'SellersItemIdentification'), 'ID')
            or _text(_first(item_node, 'StandardItemIdentification'), 'ID')
            or ''
        ),
        'descripcion_xml': descripcion,
        'unidad_medida_xml': unidad,
        'cantidad': cantidad,
        'valor_unitario': valor_unitario,
        'precio_unitario': precio_unitario,
        'subtotal': subtotal,
        'igv': igv,
        'total': total,
    }


def _dividir_decimal(value, divisor):
    try:
        return Decimal(value) / Decimal(divisor)
    except (InvalidOperation, ZeroDivisionError):
        return Decimal('0')


def _crear_o_actualizar_entidad(data, es_cliente=False, es_proveedor=False):
    defaults = {
        'tipo_documento_identidad': data['tipo_documento_identidad'],
        'razon_social': data['razon_social'],
        'nombre_comercial': data['nombre_comercial'],
        'direccion': data['direccion'],
        'ubigeo': data['ubigeo'],
        'departamento': data['departamento'],
        'provincia': data['provincia'],
        'distrito': data['distrito'],
        'pais': data['pais'],
        'es_cliente': es_cliente,
        'es_proveedor': es_proveedor,
        'activo': True,
    }
    entidad, created = Entidad.objects.get_or_create(
        numero_documento=data['numero_documento'],
        defaults=defaults,
    )
    updated = False
    if not created:
        for field, value in defaults.items():
            if field in ['es_cliente', 'es_proveedor']:
                if value and not getattr(entidad, field):
                    setattr(entidad, field, True)
                    updated = True
            elif field == 'tipo_documento_identidad':
                if value and getattr(entidad, field) != value:
                    setattr(entidad, field, value)
                    updated = True
            elif value and not getattr(entidad, field):
                setattr(entidad, field, value)
                updated = True
        if updated:
            entidad.save()
    return entidad, created, updated


def _crear_detalle(documento, item, entidad):
    equivalencia = _buscar_equivalencia(entidad, item)
    producto = equivalencia.producto if equivalencia else None
    factor = equivalencia.factor_conversion if equivalencia else _factor_unidad(item['unidad_medida_xml'], producto)
    factor = resolver_factor_conversion(
        item['unidad_medida_xml'],
        producto.unidad_base if producto else 'KG',
        factor,
        item['descripcion_xml'],
    )
    cantidad_base = item['cantidad'] * factor
    if producto and producto.unidad_base == 'KG':
        cantidad_base = normalizar_cantidad_kg(cantidad_base)
    afecta_kardex = bool(producto and producto.afecta_kardex)
    estado = DocumentoDetalle.CLASIFICADO if producto else DocumentoDetalle.PENDIENTE
    if producto and not producto.afecta_kardex:
        estado = DocumentoDetalle.NO_APLICA

    return DocumentoDetalle.objects.create(
        documento=documento,
        codigo_producto_xml=item['codigo_producto_xml'],
        descripcion_xml=item['descripcion_xml'],
        unidad_medida_xml=item['unidad_medida_xml'],
        cantidad=item['cantidad'],
        valor_unitario=item['valor_unitario'],
        precio_unitario=item['precio_unitario'],
        subtotal=item['subtotal'],
        igv=item['igv'],
        total=item['total'],
        producto=producto,
        factor_conversion=factor,
        cantidad_base=cantidad_base,
        afecta_kardex=afecta_kardex,
        estado_clasificacion=estado,
    )


def _buscar_equivalencia(entidad, item):
    qs = ProductoEquivalencia.objects.filter(
        activo=True,
        codigo_producto_xml=item['codigo_producto_xml'],
        descripcion_xml=item['descripcion_xml'],
        unidad_medida_xml=item['unidad_medida_xml'],
    )
    return qs.filter(entidad=entidad).first() or qs.filter(entidad__isnull=True).first()


def _factor_unidad(unidad_xml, producto):
    unidad_destino = producto.unidad_base if producto else 'KG'
    conversion = UnidadConversion.objects.filter(
        unidad_origen=unidad_xml,
        unidad_destino=unidad_destino,
    ).first()
    if conversion:
        return conversion.factor
    if unidad_xml == 'LBR' and unidad_destino == 'KG':
        return FACTOR_LIBRA_A_KG
    return Decimal('1')


def _resolver_empresa(empresas, datos):
    rucs = {datos['emisor']['numero_documento'], datos['receptor']['numero_documento']}
    for empresa in empresas:
        if empresa.ruc in rucs:
            return empresa
    raise XMLImportError('El XML no corresponde a ninguna Empresa principal activa.')


def _resolver_tipo_operacion(datos, empresa):
    tipo = datos['tipo_documento']
    emisor_es_empresa = datos['emisor']['numero_documento'] == empresa.ruc
    receptor_es_empresa = datos['receptor']['numero_documento'] == empresa.ruc

    if tipo == Documento.FACTURA:
        if receptor_es_empresa:
            return Documento.COMPRA
        if emisor_es_empresa:
            return Documento.VENTA
    if tipo == Documento.LIQUIDACION_COMPRA and (emisor_es_empresa or receptor_es_empresa):
        return Documento.COMPRA
    if tipo == Documento.NOTA_CREDITO:
        if receptor_es_empresa:
            return Documento.NOTA_CREDITO_COMPRA
        if emisor_es_empresa:
            return Documento.NOTA_CREDITO_VENTA
    return Documento.OTRO


def _split_serie_numero(document_id):
    parts = document_id.strip().split('-', 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return document_id[:4], document_id[4:]


def _parse_date(value):
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise XMLImportError(f'Fecha de emision invalida: {value}') from exc


def _parse_tipo_cambio(root):
    exchange = _first(root, 'PaymentExchangeRate') or _first(root, 'PricingExchangeRate')
    value = _text(exchange, 'CalculationRate')
    return _decimal(value) if value else None


def _decimal(value):
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, AttributeError) as exc:
        raise XMLImportError(f'Numero decimal invalido: {value}') from exc

def _inferir_tipo_documento_identidad(numero, tipo_documento=None, rol=None):
    digits = ''.join(ch for ch in (numero or '') if ch.isdigit())
    if tipo_documento == Documento.LIQUIDACION_COMPRA and len(digits) == 8:
        return 'DNI'
    if len(digits) == 11:
        return 'RUC'
    if len(digits) == 8:
        return 'DNI'
    return 'RUC'


def _normalizar_tipo_documento(value, numero=None, tipo_documento=None, rol=None):
    value = (value or '').strip().upper()
    digits = ''.join(ch for ch in (numero or '') if ch.isdigit())

    if tipo_documento == Documento.LIQUIDACION_COMPRA and len(digits) == 8:
        return Entidad.DNI
    if len(digits) == 11:
        return Entidad.RUC
    if len(digits) == 8 and value in {'', '1', '6', 'DNI', 'RUC'}:
        return Entidad.DNI

    if value in {'6', 'RUC'}:
        return Entidad.RUC
    if value in {'1', 'DNI'}:
        return Entidad.DNI
    if value in {'4', 'CE'}:
        return Entidad.CE
    return Entidad.OTRO


def _required_first(node, name, message):
    found = _first(node, name)
    if found is None:
        raise XMLImportError(message)
    return found


def _required_direct_first(node, name, message):
    found = _direct_first(node, name)
    if found is None:
        raise XMLImportError(message)
    return found


def _required_text(node, name, message):
    value = _text(node, name)
    if not value:
        raise XMLImportError(message)
    return value


def _required_direct_text(node, name, message):
    value = _direct_text(node, name)
    if not value:
        raise XMLImportError(message)
    return value


def _first(node, name):
    if node is None:
        return None
    for child in node.iter():
        if _local_name(child.tag) == name:
            return child
    return None


def _direct_first(node, name):
    if node is None:
        return None
    for child in list(node):
        if _local_name(child.tag) == name:
            return child
    return None


def _children(node, name):
    if node is None:
        return []
    return [child for child in list(node) if _local_name(child.tag) == name]


def _text(node, name):
    found = _first(node, name)
    return _node_text(found)


def _direct_text(node, name):
    found = _direct_first(node, name)
    return _node_text(found)


def _node_text(node):
    if node is None or node.text is None:
        return ''
    return node.text.strip()


def _attr(node, name):
    if node is None:
        return ''
    value = node.attrib.get(name, '')
    if value:
        return value.strip()
    for key, attr_value in node.attrib.items():
        if _local_name(key) == name:
            return attr_value.strip()
    return ''


def _local_name(tag):
    return tag.rsplit('}', 1)[-1]


