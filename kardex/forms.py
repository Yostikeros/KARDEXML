from decimal import Decimal, ROUND_HALF_UP

from django import forms

from .models import Entidad, Producto, ProductoEquivalencia, TipoCambioSunat


MESES_POR_NUMERO = {
    1: 'enero',
    2: 'febrero',
    3: 'marzo',
    4: 'abril',
    5: 'mayo',
    6: 'junio',
    7: 'julio',
    8: 'agosto',
    9: 'septiembre',
    10: 'octubre',
    11: 'noviembre',
    12: 'diciembre',
}


TRILLADO_PRODUCTO_ORIGEN_CODIGO = 'CAPS'
TRILLADO_PRODUCTO_ORIGEN_NOMBRE = 'CAFE PERGAMINO CONVENCIONAL'


class CommaDecimalField(forms.DecimalField):
    def to_python(self, value):
        if isinstance(value, str):
            value = (
                value.replace('USD', '')
                .replace('usd', '')
                .replace('S/', '')
                .replace('$', '')
                .replace(',', '')
                .strip()
            )
        return super().to_python(value)


def numeric_text_widget(step='0.000001', placeholder=None, currency=None):
    attrs = {
        'class': 'form-control',
        'inputmode': 'decimal',
        'data-decimal-input': 'true',
        'step': step,
    }
    if placeholder:
        attrs['placeholder'] = placeholder
    if currency:
        attrs['data-currency'] = currency
    return forms.TextInput(attrs=attrs)


def readonly_numeric_text_widget():
    return forms.TextInput(attrs={'class': 'form-control text-end', 'readonly': 'readonly'})


def decimal_initial_for_field(value, field):
    if value in (None, '') or not isinstance(field, forms.DecimalField):
        return value
    decimal_places = getattr(field, 'decimal_places', None)
    if decimal_places is None:
        return value
    return Decimal(str(value)).quantize(Decimal(1).scaleb(-decimal_places), rounding=ROUND_HALF_UP)


def producto_origen_trillado_queryset():
    return Producto.objects.filter(
        codigo_interno=TRILLADO_PRODUCTO_ORIGEN_CODIGO,
        nombre__iexact=TRILLADO_PRODUCTO_ORIGEN_NOMBRE,
        activo=True,
        controla_stock=True,
        afecta_kardex=True,
    )


class ProductoForm(forms.ModelForm):
    class Meta:
        model = Producto
        fields = [
            'codigo_interno',
            'nombre',
            'categoria',
            'tipo_producto',
            'unidad_base',
            'controla_stock',
            'afecta_kardex',
            'activo',
        ]
        widgets = {
            'codigo_interno': forms.TextInput(attrs={'class': 'form-control'}),
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'categoria': forms.TextInput(attrs={'class': 'form-control'}),
            'tipo_producto': forms.Select(attrs={'class': 'form-select'}),
            'unidad_base': forms.TextInput(attrs={'class': 'form-control'}),
            'controla_stock': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'afecta_kardex': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

class EntidadForm(forms.ModelForm):
    class Meta:
        model = Entidad
        fields = [
            'tipo_documento_identidad',
            'numero_documento',
            'razon_social',
            'nombre_comercial',
            'direccion',
            'ubigeo',
            'departamento',
            'provincia',
            'distrito',
            'pais',
            'telefono',
            'email',
            'es_cliente',
            'es_proveedor',
            'activo',
        ]
        widgets = {
            'tipo_documento_identidad': forms.Select(attrs={'class': 'form-select'}),
            'numero_documento': forms.TextInput(attrs={'class': 'form-control'}),
            'razon_social': forms.TextInput(attrs={'class': 'form-control'}),
            'nombre_comercial': forms.TextInput(attrs={'class': 'form-control'}),
            'direccion': forms.TextInput(attrs={'class': 'form-control'}),
            'ubigeo': forms.TextInput(attrs={'class': 'form-control'}),
            'departamento': forms.TextInput(attrs={'class': 'form-control'}),
            'provincia': forms.TextInput(attrs={'class': 'form-control'}),
            'distrito': forms.TextInput(attrs={'class': 'form-control'}),
            'pais': forms.TextInput(attrs={'class': 'form-control'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'es_cliente': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'es_proveedor': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'tipo_documento_identidad': 'Tipo documento',
            'numero_documento': 'Numero documento',
            'razon_social': 'Razon social',
            'nombre_comercial': 'Nombre comercial',
            'direccion': 'Direccion',
            'pais': 'Pais',
            'telefono': 'Telefono',
            'email': 'Email',
            'es_cliente': 'Cliente',
            'es_proveedor': 'Proveedor',
            'activo': 'Activo',
        }

class ProductoEquivalenciaForm(forms.ModelForm):
    class Meta:
        model = ProductoEquivalencia
        fields = [
            'entidad',
            'codigo_producto_xml',
            'descripcion_xml',
            'unidad_medida_xml',
            'producto',
            'factor_conversion',
            'activo',
        ]
        widgets = {
            'entidad': forms.Select(attrs={'class': 'form-select'}),
            'codigo_producto_xml': forms.TextInput(attrs={'class': 'form-control'}),
            'descripcion_xml': forms.TextInput(attrs={'class': 'form-control'}),
            'unidad_medida_xml': forms.TextInput(attrs={'class': 'form-control'}),
            'producto': forms.Select(attrs={'class': 'form-select'}),
            'factor_conversion': forms.NumberInput(
                attrs={
                    'class': 'form-control',
                    'step': '0.000001',
                }
            ),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'entidad': 'Entidad',
            'codigo_producto_xml': 'Codigo XML',
            'descripcion_xml': 'Descripcion XML',
            'unidad_medida_xml': 'Unidad XML',
            'producto': 'Producto interno',
            'factor_conversion': 'Factor de conversion',
            'activo': 'Activo',
        }
        help_texts = {
            'entidad': 'Dejalo vacio para aplicar la equivalencia a cualquier entidad.',
            'factor_conversion': 'Multiplica la cantidad XML para convertirla a la unidad base del producto.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['entidad'].queryset = Entidad.objects.filter(activo=True).order_by('razon_social')
        self.fields['entidad'].required = False
        self.fields['entidad'].empty_label = 'Global - cualquier entidad'
        self.fields['producto'].queryset = Producto.objects.filter(activo=True).order_by('nombre')

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get('activo'):
            return cleaned_data

        entidad = cleaned_data.get('entidad')
        codigo = cleaned_data.get('codigo_producto_xml') or ''
        descripcion = cleaned_data.get('descripcion_xml')
        unidad = cleaned_data.get('unidad_medida_xml')
        if not descripcion or not unidad:
            return cleaned_data

        duplicados = ProductoEquivalencia.objects.filter(
            activo=True,
            codigo_producto_xml=codigo,
            descripcion_xml=descripcion,
            unidad_medida_xml=unidad,
        )
        if entidad:
            duplicados = duplicados.filter(entidad=entidad)
        else:
            duplicados = duplicados.filter(entidad__isnull=True)
        if self.instance.pk:
            duplicados = duplicados.exclude(pk=self.instance.pk)
        if duplicados.exists():
            raise forms.ValidationError('Ya existe una equivalencia activa con la misma entidad, codigo, descripcion y unidad XML.')
        return cleaned_data

class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            return [single_file_clean(file_data, initial) for file_data in data]
        return [single_file_clean(data, initial)]


class ImportarXMLLoteForm(forms.Form):
    archivos = MultipleFileField(
        label='Archivos XML',
        widget=MultipleFileInput(
            attrs={
                'class': 'form-control',
                'accept': '.xml,text/xml,application/xml',
                'multiple': True,
            }
        ),
        help_text='Selecciona uno o varios XML SUNAT.',
    )


class RestaurarBaseDatosForm(forms.Form):
    archivo = forms.FileField(
        label='Archivo de base de datos',
        widget=forms.ClearableFileInput(
            attrs={
                'class': 'form-control',
                'accept': '.sqlite,.sqlite3,.db,application/vnd.sqlite3,application/octet-stream',
            }
        ),
        help_text='Selecciona un backup SQLite generado por esta aplicacion.',
    )
    confirmar = forms.BooleanField(
        label='Confirmo que deseo reemplazar la base de datos actual',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )


class ClasificarDetalleForm(forms.Form):
    producto = forms.ModelChoiceField(
        queryset=Producto.objects.filter(activo=True).order_by('nombre'),
        label='Producto interno',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    factor_conversion = forms.DecimalField(
        label='Factor de conversion',
        max_digits=18,
        decimal_places=6,
        min_value=Decimal('0.000001'),
        initial=1,
        widget=forms.NumberInput(
            attrs={
                'class': 'form-control',
                'step': '0.000001',
            }
        ),
    )
    guardar_equivalencia = forms.BooleanField(
        label='Guardar equivalencia para futuras importaciones',
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )
    equivalencia_global = forms.BooleanField(
        label='Aplicar equivalencia a cualquier entidad',
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )

class ClasificarBloqueForm(forms.Form):
    producto = forms.ModelChoiceField(
        queryset=Producto.objects.filter(activo=True).order_by('nombre'),
        label='Producto interno',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    factor_conversion = forms.DecimalField(
        label='Factor de conversion',
        max_digits=18,
        decimal_places=6,
        min_value=Decimal('0.000001'),
        initial=1,
        widget=forms.NumberInput(
            attrs={
                'class': 'form-control',
                'step': '0.000001',
            }
        ),
    )
    guardar_equivalencia = forms.BooleanField(
        label='Guardar equivalencias',
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )
    equivalencia_global = forms.BooleanField(
        label='Aplicar a cualquier entidad',
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )
class TipoCambioSunatImportForm(forms.Form):
    mes = forms.ChoiceField(
        label='Mes',
        choices=[
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
        ],
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    anio = forms.IntegerField(
        label='Anio',
        min_value=2000,
        max_value=2100,
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
    )

class StockInicialForm(forms.Form):
    fecha = forms.DateField(
        label='Fecha',
        input_formats=['%Y-%m-%d', '%d/%m/%Y'],
        widget=forms.DateInput(
            format='%Y-%m-%d',
            attrs={
                'class': 'form-control',
                'type': 'date',
            }
        ),
    )
    producto = forms.ModelChoiceField(
        queryset=Producto.objects.filter(
            activo=True,
            controla_stock=True,
            afecta_kardex=True,
        ).order_by('nombre'),
        label='Producto',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    cantidad = forms.DecimalField(
        label='Cantidad inicial',
        max_digits=18,
        decimal_places=6,
        min_value=0,
        widget=forms.NumberInput(
            attrs={
                'class': 'form-control',
                'step': '0.000001',
            }
        ),
    )
    costo_unitario = forms.DecimalField(
        label='Costo unitario inicial',
        max_digits=18,
        decimal_places=6,
        min_value=0,
        widget=forms.NumberInput(
            attrs={
                'class': 'form-control',
                'step': '0.000001',
            }
        ),
    )
    observacion = forms.CharField(
        label='Observacion',
        required=False,
        widget=forms.Textarea(
            attrs={
                'class': 'form-control',
                'rows': 3,
            }
        ),
    )

    def __init__(self, *args, bloquear_producto=False, **kwargs):
        super().__init__(*args, **kwargs)
        if bloquear_producto:
            self.fields['producto'].disabled = True


class ProcesoTrilladoForm(forms.Form):
    fecha = forms.DateField(
        label='Fecha del proceso',
        input_formats=['%Y-%m-%d', '%d/%m/%Y'],
        widget=forms.DateInput(
            format='%Y-%m-%d',
            attrs={'class': 'form-control', 'type': 'date'},
        ),
    )
    lote = forms.CharField(
        label='Lote',
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    factura_relacionada = forms.CharField(
        label='Factura de proceso',
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    factura_destino = forms.CharField(
        label='Factura Nro.',
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'E001-1796'}),
    )
    fecha_factura_relacionada = forms.DateField(
        label='Fecha',
        input_formats=['%Y-%m-%d', '%d/%m/%Y'],
        required=False,
        widget=forms.DateInput(
            format='%Y-%m-%d',
            attrs={'class': 'form-control', 'type': 'date'},
        ),
    )
    cliente_destino_entidad = forms.ModelChoiceField(
        queryset=Entidad.objects.filter(activo=True).order_by('razon_social'),
        label='Cliente',
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    contrato_destino = forms.CharField(
        label='Contrato',
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'P81267.000'}),
    )
    valor_total_destino_usd = CommaDecimalField(
        label='Valor total USD',
        max_digits=24,
        decimal_places=2,
        min_value=Decimal('0'),
        required=False,
        widget=numeric_text_widget(step='0.01', placeholder='USD 133,863.31', currency='USD'),
    )
    tipo_cambio_destino = forms.DecimalField(
        label='TC fecha',
        max_digits=12,
        decimal_places=6,
        min_value=Decimal('0'),
        required=False,
        disabled=True,
        widget=readonly_numeric_text_widget(),
    )
    valor_total_destino_soles = forms.DecimalField(
        label='Valor en soles',
        max_digits=24,
        decimal_places=2,
        min_value=Decimal('0'),
        required=False,
        disabled=True,
        widget=readonly_numeric_text_widget(),
    )
    producto_consumido = forms.ModelChoiceField(
        queryset=Producto.objects.none(),
        label='Cafe pergamino consumido',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    cantidad_consumida = CommaDecimalField(
        label='Cantidad pergamino KG',
        max_digits=24,
        decimal_places=6,
        min_value=Decimal('0.000001'),
        widget=numeric_text_widget(),
    )
    kg_por_quintal = CommaDecimalField(
        label='Kg por quintal',
        max_digits=24,
        decimal_places=6,
        min_value=Decimal('0.000001'),
        initial=Decimal('46'),
        widget=numeric_text_widget(),
    )
    quintales_procesados = forms.DecimalField(
        label='Quintales procesados',
        max_digits=24,
        decimal_places=6,
        min_value=Decimal('0'),
        required=False,
        disabled=True,
        widget=readonly_numeric_text_widget(),
    )
    costo_servicio_por_quintal_usd = CommaDecimalField(
        label='Costo servicio por quintal USD',
        max_digits=24,
        decimal_places=6,
        min_value=Decimal('0'),
        initial=Decimal('5'),
        widget=numeric_text_widget(currency='USD'),
    )
    costo_proceso_usd = forms.DecimalField(
        label='Costo total servicio USD',
        max_digits=24,
        decimal_places=6,
        min_value=Decimal('0'),
        required=False,
        disabled=True,
        widget=readonly_numeric_text_widget(),
    )
    tipo_cambio_fecha_proceso = forms.DecimalField(
        label='Tipo de cambio del proceso',
        max_digits=12,
        decimal_places=6,
        min_value=Decimal('0.000001'),
        required=False,
        widget=forms.HiddenInput(),
        help_text='Automatico segun la fecha del proceso.',
    )
    costo_proceso_soles = forms.DecimalField(
        label='Costo total servicio S/',
        max_digits=24,
        decimal_places=2,
        min_value=Decimal('0'),
        required=False,
        disabled=True,
        widget=readonly_numeric_text_widget(),
    )
    costo_servicio_por_kg_usd = forms.DecimalField(
        label='Costo servicio por kg USD',
        max_digits=24,
        decimal_places=6,
        min_value=Decimal('0'),
        required=False,
        disabled=True,
        widget=readonly_numeric_text_widget(),
    )
    costo_servicio_por_kg_soles = forms.DecimalField(
        label='Costo servicio por kg S/',
        max_digits=24,
        decimal_places=6,
        min_value=Decimal('0'),
        required=False,
        disabled=True,
        widget=readonly_numeric_text_widget(),
    )
    producto_exportable = forms.ModelChoiceField(
        queryset=Producto.objects.filter(activo=True, controla_stock=True, afecta_kardex=True).order_by('nombre'),
        label='Cafe exportable obtenido',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    cantidad_exportable = CommaDecimalField(
        label='Cantidad exportable KG',
        max_digits=24,
        decimal_places=6,
        min_value=Decimal('0.000001'),
        widget=numeric_text_widget(),
    )
    valor_mercado_exportable = CommaDecimalField(
        label='Valor mercado USD',
        max_digits=24,
        decimal_places=6,
        min_value=Decimal('0'),
        widget=numeric_text_widget(currency='USD'),
    )
    merma = CommaDecimalField(
        label='Merma KG',
        max_digits=24,
        decimal_places=6,
        min_value=Decimal('0'),
        initial=Decimal('0'),
        widget=numeric_text_widget(),
    )
    observaciones = forms.CharField(
        label='Observaciones',
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
    )

    def __init__(self, *args, tipo_cambio_proceso=None, fecha_proceso=None, solo_detalles=False, **kwargs):
        self.tipo_cambio_proceso = tipo_cambio_proceso
        self.fecha_proceso = fecha_proceso
        self.solo_detalles = solo_detalles
        super().__init__(*args, **kwargs)
        producto_origen_queryset = producto_origen_trillado_queryset()
        producto_origen = producto_origen_queryset.first()
        self.fields['producto_consumido'].queryset = producto_origen_queryset
        self.fields['producto_consumido'].disabled = True
        if producto_origen:
            self.fields['producto_consumido'].initial = producto_origen.pk
            self.initial['producto_consumido'] = producto_origen.pk
        subproductos = Producto.objects.filter(
            activo=True,
            controla_stock=True,
            afecta_kardex=True,
        ).order_by('nombre')
        for index in range(1, 4):
            self.fields[f'subproducto_{index}'] = forms.ModelChoiceField(
                queryset=subproductos,
                label=f'Subproducto {index}',
                required=False,
                widget=forms.Select(attrs={'class': 'form-select'}),
            )
            self.fields[f'cantidad_subproducto_{index}'] = CommaDecimalField(
                label='Cantidad KG',
                max_digits=24,
                decimal_places=6,
                min_value=Decimal('0.000001'),
                required=False,
                widget=numeric_text_widget(),
            )
            self.fields[f'valor_mercado_subproducto_{index}'] = CommaDecimalField(
                label='Valor mercado USD',
                max_digits=24,
                decimal_places=6,
                min_value=Decimal('0'),
                required=False,
                widget=numeric_text_widget(currency='USD'),
            )
        if self.solo_detalles:
            campos_editables = {
                'lote',
                'factura_destino',
                'fecha_factura_relacionada',
                'cliente_destino_entidad',
                'contrato_destino',
                'factura_relacionada',
                'valor_total_destino_usd',
                'observaciones',
            }
            for nombre, campo in self.fields.items():
                if nombre not in campos_editables:
                    campo.disabled = True
                    campo.required = False
                    if nombre in self.initial:
                        self.initial[nombre] = decimal_initial_for_field(self.initial[nombre], campo)

    def clean(self):
        cleaned_data = super().clean()
        fecha = cleaned_data.get('fecha')
        tipo_cambio = None
        if fecha and self.fecha_proceso and fecha == self.fecha_proceso and self.tipo_cambio_proceso:
            tipo_cambio = self.tipo_cambio_proceso
            cleaned_data['tipo_cambio_fecha_proceso'] = tipo_cambio
        elif fecha:
            tipo_cambio = _tipo_cambio_sunat_venta(fecha)
            if tipo_cambio:
                cleaned_data['tipo_cambio_fecha_proceso'] = tipo_cambio
        if fecha and not cleaned_data.get('tipo_cambio_fecha_proceso'):
            self.add_error(
                'tipo_cambio_fecha_proceso',
                'Registra el tipo de cambio SUNAT para la fecha del proceso.',
            )

        cantidad_consumida = cleaned_data.get('cantidad_consumida') or Decimal('0')
        cantidad_exportable = cleaned_data.get('cantidad_exportable') or Decimal('0')
        merma = cleaned_data.get('merma') or Decimal('0')
        kg_por_quintal = cleaned_data.get('kg_por_quintal') or Decimal('0')
        costo_servicio_por_quintal_usd = cleaned_data.get('costo_servicio_por_quintal_usd') or Decimal('0')
        tipo_cambio_proceso = cleaned_data.get('tipo_cambio_fecha_proceso') or Decimal('0')
        quintales = Decimal('0')
        costo_total_servicio_usd = Decimal('0')
        costo_total_servicio_soles = Decimal('0')
        costo_servicio_por_kg_usd = Decimal('0')
        costo_servicio_por_kg_soles = Decimal('0')
        if cantidad_consumida and kg_por_quintal:
            quintales = (cantidad_consumida / kg_por_quintal).quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP)
            costo_total_servicio_usd = (quintales * costo_servicio_por_quintal_usd).quantize(
                Decimal('0.000001'),
                rounding=ROUND_HALF_UP,
            )
            costo_total_servicio_soles = (costo_total_servicio_usd * tipo_cambio_proceso).quantize(
                Decimal('0.01'),
                rounding=ROUND_HALF_UP,
            )
            costo_servicio_por_kg_usd = (costo_total_servicio_usd / cantidad_consumida).quantize(
                Decimal('0.000001'),
                rounding=ROUND_HALF_UP,
            )
            costo_servicio_por_kg_soles = (costo_total_servicio_soles / cantidad_consumida).quantize(
                Decimal('0.000001'),
                rounding=ROUND_HALF_UP,
            )
        cleaned_data['quintales_procesados'] = quintales
        cleaned_data['costo_proceso_usd'] = costo_total_servicio_usd
        cleaned_data['costo_proceso_soles'] = costo_total_servicio_soles
        cleaned_data['costo_servicio_por_kg_usd'] = costo_servicio_por_kg_usd
        cleaned_data['costo_servicio_por_kg_soles'] = costo_servicio_por_kg_soles
        fecha_destino = cleaned_data.get('fecha_factura_relacionada')
        valor_destino_usd = cleaned_data.get('valor_total_destino_usd') or Decimal('0')
        tipo_cambio_destino = None
        if fecha_destino:
            tipo_cambio_destino = _tipo_cambio_sunat_venta(fecha_destino)
            if tipo_cambio_destino:
                cleaned_data['tipo_cambio_destino'] = tipo_cambio_destino
                cleaned_data['valor_total_destino_soles'] = (valor_destino_usd * tipo_cambio_destino).quantize(
                    Decimal('0.01')
                )
            else:
                self.add_error(
                    'fecha_factura_relacionada',
                    'Registra el tipo de cambio SUNAT para la fecha del destino.',
                )
        else:
            cleaned_data['tipo_cambio_destino'] = Decimal('0')
            cleaned_data['valor_total_destino_soles'] = Decimal('0')
        cantidad_subproductos = Decimal('0')
        productos = []

        for index in range(1, 4):
            producto = cleaned_data.get(f'subproducto_{index}')
            cantidad = cleaned_data.get(f'cantidad_subproducto_{index}')
            valor = cleaned_data.get(f'valor_mercado_subproducto_{index}')
            if producto or cantidad or valor is not None:
                if not producto:
                    self.add_error(f'subproducto_{index}', 'Selecciona el subproducto.')
                if cantidad is None:
                    self.add_error(f'cantidad_subproducto_{index}', 'Ingresa la cantidad.')
            if producto and cantidad:
                cantidad_subproductos += cantidad
                productos.append(producto.id)

        producto_exportable = cleaned_data.get('producto_exportable')
        if producto_exportable:
            productos.append(producto_exportable.id)
        if len(productos) != len(set(productos)):
            raise forms.ValidationError('No repitas el mismo producto como exportable y subproducto.')

        if cantidad_consumida and cantidad_exportable:
            total_fisico = cantidad_exportable + cantidad_subproductos + merma
            if total_fisico != cantidad_consumida:
                raise forms.ValidationError(
                    'La cantidad de pergamino debe ser igual a exportable + subproductos + merma.'
                )
        return cleaned_data


def _tipo_cambio_sunat_venta(fecha):
    tipo_cambio = TipoCambioSunat.objects.filter(
        anio=fecha.year,
        mes=MESES_POR_NUMERO[fecha.month],
        dia=fecha.day,
    ).first()
    if tipo_cambio:
        return tipo_cambio.venta
    return None
