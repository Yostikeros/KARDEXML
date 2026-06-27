from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


def backfill_costo_servicio(apps, schema_editor):
    ProcesoProductivo = apps.get_model('kardex', 'ProcesoProductivo')
    for proceso in ProcesoProductivo.objects.all():
        kg_por_quintal = proceso.kg_por_quintal or Decimal('46')
        cantidad = proceso.cantidad_consumida or Decimal('0')
        costo_por_quintal = Decimal('5')
        tipo_cambio = proceso.tipo_cambio_fecha_proceso or Decimal('0')
        quintales = (cantidad / kg_por_quintal).quantize(Decimal('0.000001')) if cantidad and kg_por_quintal else Decimal('0')
        total_usd = (quintales * costo_por_quintal).quantize(Decimal('0.000001'))
        total_soles = (total_usd * tipo_cambio).quantize(Decimal('0.01'))
        proceso.quintales_procesados = quintales
        proceso.costo_servicio_por_quintal_usd = costo_por_quintal
        proceso.costo_proceso_usd = total_usd
        proceso.costo_proceso_soles = total_soles
        proceso.costo_total_proceso = (proceso.costo_pergamino_consumido + total_soles).quantize(Decimal('0.01'))
        proceso.costo_servicio_por_kg_usd = (
            (total_usd / cantidad).quantize(Decimal('0.000001')) if cantidad else Decimal('0')
        )
        proceso.costo_servicio_por_kg_soles = (
            (total_soles / cantidad).quantize(Decimal('0.000001')) if cantidad else Decimal('0')
        )
        proceso.save(
            update_fields=[
                'quintales_procesados',
                'costo_servicio_por_quintal_usd',
                'costo_proceso_usd',
                'costo_proceso_soles',
                'costo_total_proceso',
                'costo_servicio_por_kg_usd',
                'costo_servicio_por_kg_soles',
            ]
        )


class Migration(migrations.Migration):
    dependencies = [
        ('kardex', '0003_tipo_cambio_sunat_lbr'),
    ]

    operations = [
        migrations.AddField(
            model_name='procesoproductivo',
            name='contrato_destino',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='procesoproductivo',
            name='cliente_destino',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='procesoproductivo',
            name='cliente_destino_entidad',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='procesos_trillado_destino',
                to='kardex.entidad',
            ),
        ),
        migrations.AddField(
            model_name='procesoproductivo',
            name='factura_destino',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='procesoproductivo',
            name='valor_total_destino_usd',
            field=models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=24),
        ),
        migrations.AddField(
            model_name='procesoproductivo',
            name='tipo_cambio_destino',
            field=models.DecimalField(decimal_places=6, default=Decimal('0'), max_digits=12),
        ),
        migrations.AddField(
            model_name='procesoproductivo',
            name='valor_total_destino_soles',
            field=models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=24),
        ),
        migrations.AddField(
            model_name='procesoproductivo',
            name='kg_por_quintal',
            field=models.DecimalField(decimal_places=6, default=Decimal('46'), max_digits=24),
        ),
        migrations.AddField(
            model_name='procesoproductivo',
            name='quintales_procesados',
            field=models.DecimalField(decimal_places=6, default=Decimal('0'), max_digits=24),
        ),
        migrations.AddField(
            model_name='procesoproductivo',
            name='costo_servicio_por_quintal_usd',
            field=models.DecimalField(decimal_places=6, default=Decimal('5'), max_digits=24),
        ),
        migrations.AddField(
            model_name='procesoproductivo',
            name='costo_servicio_por_kg_usd',
            field=models.DecimalField(decimal_places=6, default=Decimal('0'), max_digits=24),
        ),
        migrations.AddField(
            model_name='procesoproductivo',
            name='costo_servicio_por_kg_soles',
            field=models.DecimalField(decimal_places=6, default=Decimal('0'), max_digits=24),
        ),
        migrations.RunPython(backfill_costo_servicio, migrations.RunPython.noop),
    ]
