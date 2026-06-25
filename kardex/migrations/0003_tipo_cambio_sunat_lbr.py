from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


def crear_conversion_lbr(apps, schema_editor):
    UnidadConversion = apps.get_model('kardex', 'UnidadConversion')
    UnidadConversion.objects.update_or_create(
        unidad_origen='LBR',
        unidad_destino='KG',
        defaults={
            'factor': Decimal('0.45359237'),
            'descripcion': 'Libra a kilogramo',
        },
    )


def eliminar_conversion_lbr(apps, schema_editor):
    UnidadConversion = apps.get_model('kardex', 'UnidadConversion')
    UnidadConversion.objects.filter(unidad_origen='LBR', unidad_destino='KG').delete()


class Migration(migrations.Migration):
    dependencies = [
        ('kardex', '0002_unidades_conversion_iniciales'),
    ]

    operations = [
        migrations.CreateModel(
            name='TipoCambioSunat',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('mes', models.CharField(choices=[('enero', 'Enero'), ('febrero', 'Febrero'), ('marzo', 'Marzo'), ('abril', 'Abril'), ('mayo', 'Mayo'), ('junio', 'Junio'), ('julio', 'Julio'), ('agosto', 'Agosto'), ('septiembre', 'Septiembre'), ('octubre', 'Octubre'), ('noviembre', 'Noviembre'), ('diciembre', 'Diciembre')], max_length=20)),
                ('anio', models.PositiveIntegerField()),
                ('dia', models.PositiveSmallIntegerField()),
                ('compra', models.DecimalField(decimal_places=6, max_digits=12)),
                ('venta', models.DecimalField(decimal_places=6, max_digits=12)),
                ('fecha_creacion', models.DateTimeField(auto_now_add=True)),
                ('fecha_actualizacion', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'tipo de cambio SUNAT',
                'verbose_name_plural': 'tipos de cambio SUNAT',
            },
        ),
        migrations.AddIndex(
            model_name='tipocambiosunat',
            index=models.Index(fields=['anio', 'mes', 'dia'], name='kardex_tipo_anio_90a065_idx'),
        ),
        migrations.AddConstraint(
            model_name='tipocambiosunat',
            constraint=models.UniqueConstraint(fields=('mes', 'anio', 'dia'), name='uq_tipo_cambio_sunat_fecha'),
        ),
        migrations.RunPython(crear_conversion_lbr, eliminar_conversion_lbr),
    ]