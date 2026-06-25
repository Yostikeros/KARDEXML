from decimal import Decimal

from django import forms

from .models import Entidad, Producto, ProductoEquivalencia


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
