from decimal import Decimal

from django.db import migrations


UNIDADES_INICIALES = [
    ('KG', 'KG', Decimal('1'), 'Kilogramo a kilogramo'),
    ('QQ', 'KG', Decimal('55.2'), 'Quintal a kilogramo'),
    ('SACO_69', 'KG', Decimal('69'), 'Saco de 69 kg a kilogramo'),
    ('SACO_30', 'KG', Decimal('30'), 'Saco de 30 kg a kilogramo'),
    ('TM', 'KG', Decimal('1000'), 'Tonelada metrica a kilogramo'),
]


def crear_unidades_iniciales(apps, schema_editor):
    UnidadConversion = apps.get_model('kardex', 'UnidadConversion')
    for unidad_origen, unidad_destino, factor, descripcion in UNIDADES_INICIALES:
        UnidadConversion.objects.update_or_create(
            unidad_origen=unidad_origen,
            unidad_destino=unidad_destino,
            defaults={
                'factor': factor,
                'descripcion': descripcion,
            },
        )


def eliminar_unidades_iniciales(apps, schema_editor):
    UnidadConversion = apps.get_model('kardex', 'UnidadConversion')
    for unidad_origen, unidad_destino, _, _ in UNIDADES_INICIALES:
        UnidadConversion.objects.filter(
            unidad_origen=unidad_origen,
            unidad_destino=unidad_destino,
        ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('kardex', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(crear_unidades_iniciales, eliminar_unidades_iniciales),
    ]
