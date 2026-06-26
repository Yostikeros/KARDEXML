# KARDEXML

Aplicacion Django para importar comprobantes XML SUNAT, clasificarlos contra productos internos y generar movimientos de Kardex valorizado.

Este proyecto fue recuperado despues de corrupcion en un disco extraible. Las vistas, templates, servicios y pruebas principales fueron reconstruidos para dejar la aplicacion operativa.

## Como levantar la app

Desde la raiz del proyecto:

```powershell
python -m venv .ven
.\.ven\Scripts\Activate.ps1
pip install -r requirements.txt
```

Configura variables de entorno tomando como base `.env.example`:

```powershell
$env:DJANGO_SECRET_KEY='usa-una-clave-local'
$env:DJANGO_DEBUG='1'
$env:DJANGO_ALLOWED_HOSTS='127.0.0.1,localhost'
```

Ejecuta migraciones/tablas y levanta el servidor:

```powershell
python manage.py migrate --run-syncdb
python manage.py runserver 127.0.0.1:8000
```

Si ya tienes el entorno activo y la base local creada, basta con:

```powershell
python manage.py runserver 127.0.0.1:8000
```

URL local:

```text
http://127.0.0.1:8000/
```

Admin:

```text
http://127.0.0.1:8000/admin/
```

Usuario local de trabajo: `rogger`. La clave no se documenta aqui por seguridad.

Si se usa el entorno Python 3.12 recuperado:

```powershell
$env:PYTHONPATH='F:\DEVELOPER\DEV_APP\KARDEXML\.venv\Lib\site-packages'
py -3.12 manage.py runserver 127.0.0.1:8000
```

## Verificacion

Comandos usados para validar el estado actual:

```powershell
python manage.py check
python manage.py test
```

Estado al ultimo avance: `78 tests OK`.

## Base de datos y migraciones

- La base local fue recreada despues de la corrupcion del disco.
- En `kardexml/settings.py` sigue `MIGRATION_MODULES = {"kardex": None}` porque `kardex/migrations/0001_initial.py` quedo comprometido.
- La base local usa SQLite en `db.sqlite3`.
- Los cambios de esquema de `kardex` se sincronizan en bases nuevas con `migrate --run-syncdb`. En bases SQLite ya existentes, antes de agregar columnas nuevas se debe crear backup y aplicar la actualizacion de esquema correspondiente.
- Para crear tablas desde los modelos en una base nueva:

```powershell
python manage.py migrate --run-syncdb
```

Si se usa Python 3.12 con el entorno recuperado:

```powershell
$env:PYTHONPATH='F:\DEVELOPER\DEV_APP\KARDEXML\.venv\Lib\site-packages'
py -3.12 manage.py migrate --run-syncdb
```

## Mantenimiento de base de datos

La app incluye una pantalla de mantenimiento para usuarios administradores/staff.

Ruta:

```text
/mantenimiento/db/
```

Tambien aparece en el menu lateral como `Sistema > Mantenimiento DB` cuando el usuario es administrador.

Permite:

- Descargar un backup completo de la base SQLite actual.
- Restaurar una base SQLite subida desde archivo `.sqlite3`, `.sqlite` o `.db`.
- Validar que el archivo subido sea SQLite y tenga estructura minima de Django.
- Crear automaticamente un backup previo antes de reemplazar la base actual.

Los backups previos generados por restauracion se guardan en:

```text
backups/db/
```

Rutas internas:

```text
/mantenimiento/db/backup/
/mantenimiento/db/restaurar/
```

Importante: restaurar una base reemplaza productos, entidades, documentos, movimientos, usuarios y configuraciones por el contenido del archivo subido.

## Configuracion actual importante

- Empresa principal activa: RUC `20570726014`.
- Razon social configurada: `EMPRESA CAFETALERA AROMAS DE CAFE E.I.R.L.`
- El admin de Django registra los modelos de la app `kardex`.
- El boton del usuario en el sidebar lleva al admin cuando el usuario es administrador.
- La pagina de stock inicial filtra saldos iniciales reales, sin mezclar movimientos de documentos.
- La pantalla `Trillado` registra procesos internos de pergamino a exportable/subproductos como documento interno, con costo de proceso USD, tipo de cambio automatico por fecha, valorizacion residual y anulacion por reversion.
- Los documentos en Pre-Kardex o Confirmado pueden devolverse al estado inicial `Pendiente de clasificacion` desde el boton `Devolver a pendiente`; si estaban confirmados, se eliminan sus movimientos y se recalculan saldos posteriores.
- El menu `Sistema > Mantenimiento DB` permite backup y restauracion de la base SQLite para usuarios administradores.
- Los mensajes de error usan clases Bootstrap correctas mediante `MESSAGE_TAGS`.
- `SECRET_KEY`, `DEBUG` y `ALLOWED_HOSTS` se leen desde variables de entorno (`DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`).

## Flujo operativo

1. Cargar XML desde `XML > Importar`.
2. Revisar documentos en `Documentos`.
3. Filtrar u ordenar documentos por tipo, estado, serie o numero.
4. Clasificar detalles individualmente o clasificar documentos en lote.
5. Revisar documentos en `Pre-Kardex`.
6. Aprobar Pre-Kardex para generar movimientos de inventario.
7. Revisar reportes de stock, Kardex por producto, documentos importados, movimientos por documento y documentos por mes.
8. Respaldar la base desde `Sistema > Mantenimiento DB` cuando se termine una carga o ajuste importante.

## Importacion XML

Soporte actual:

- Importacion XML por lote.
- Rechazo de XML duplicados por hash.
- Deteccion de duplicados por tipo, serie, numero, emisor y receptor.
- `InvoiceTypeCode` `01`: Factura.
- `InvoiceTypeCode` `04`: Liquidacion de compra.
- En liquidaciones, si el productor tiene documento de 8 digitos, se registra como DNI.
- En documentos normales, 8 digitos se infiere como DNI y 11 digitos como RUC cuando el XML no trae `schemeID`.
- La moneda se lee de `DocumentCurrencyCode` y de atributos `currencyID`.
- Si el XML viene en USD, el sistema exige tipo de cambio SUNAT venta para la fecha del documento.
- Si no existe tipo de cambio para esa fecha, la importacion se detiene con mensaje.

## Unidades, moneda y cantidades

- `KGM` se normaliza como `KG`.
- `LBR`, `LB` y `LBS` se normalizan como `LBR`.
- Existe conversion `LBR -> KG` con factor `0.453592`.
- Si un XML trae cantidad en `NIU`/`UND`, pero la descripcion contiene kilos, se guarda como `KG` y se usa la cantidad de kilos inferida.
- Si un XML trae cantidad en `NIU`/`UND` y la descripcion indica quintales, por ejemplo `QQ/46 KG`, se interpreta como quintales de 46 kg y se convierte a kilos.
- La clasificacion manual tambien corrige equivalencias antiguas de `LBR -> KG` o `NIU/UND` con quintales cuando el factor guardado era `1`.
- Las cantidades inferidas se normalizan cuando quedan dentro de una tolerancia pequena de un entero, para evitar diferencias visuales como `20000.000014`.
- Si el XML no trae valor/precio unitario util, se deriva:
  - Valor unitario = subtotal / cantidad.
  - Precio unitario = total / cantidad.
- Los importes en moneda extranjera se convierten usando el tipo de cambio SUNAT venta.

## Panel Documentos

La pantalla `Documentos` permite:

- Ver comprobantes importados.
- Filtrar por tipo de documento.
- Filtrar por estado del documento.
- Buscar por serie, numero o codigo de tipo.
- Ordenar por fecha, tipo de documento o estado.
- Seleccionar documentos pendientes con checkboxes.
- Seleccionar todos o ninguno.
- Clasificar documentos en lote con un producto, factor de conversion y regla de equivalencia.

Ruta principal:

```text
/documentos/
```

Ruta POST para clasificacion masiva:

```text
/documentos/clasificar-bloque/
```

La vista acepta campos `documento_ids` y `documentos` para mantener compatibilidad con formularios anteriores.

## Clasificacion

Clasificacion individual:

- Ruta: `/detalles/<id>/clasificar/`
- Permite asignar producto interno.
- Permite definir factor de conversion.
- Permite guardar equivalencia por entidad o global.
- Permite marcar un item como no aplicable al Kardex.

Clasificacion por bloque dentro de un documento:

- Ruta POST: `/documentos/<id>/clasificar-bloque/`
- Permite seleccionar varios detalles del mismo documento.
- Aplica el mismo producto, factor y equivalencia a todos los seleccionados.

Clasificacion por bloque desde el panel Documentos:

- Permite seleccionar varios documentos pendientes.
- Clasifica todos los detalles pendientes de esos documentos con una misma regla.

Validaciones relevantes:

- No se puede clasificar un documento confirmado.
- Las acciones por bloque sin seleccion no generan error 500; devuelven mensaje de usuario.
- El factor de conversion debe ser mayor que cero.

## Pre-Kardex y aprobacion

La bandeja de Pre-Kardex permite:

- Revisar documentos listos para aprobar.
- Seleccionar varios documentos.
- Usar botones `Todos` y `Ninguno`.
- Aprobar seleccionados en bloque.
- Aprobar un documento individual.

Rutas:

```text
/pre-kardex/
/pre-kardex/confirmar-bloque/
/documentos/<id>/pre-kardex/
/documentos/<id>/confirmar-kardex/
```

Al aprobar:

- Se generan movimientos de entrada, salida o ajuste segun el tipo de operacion.
- Se valida stock suficiente para salidas.
- Se actualiza el saldo por producto con promedio movil.
- El documento pasa a estado `Confirmado`.
- Si se confirma un documento historico y existen movimientos posteriores, el sistema recalcula los saldos posteriores del producto desde la fecha del documento.

## Reversiones

Reversion de Pre-Kardex:

- Boton: `Quitar de Pre-Kardex`.
- No elimina el XML ni el documento.
- Devuelve el documento a `Pendiente de clasificacion`.
- Limpia producto, factor, cantidad base y estado de clasificacion en sus detalles.
- Ruta POST: `/documentos/<id>/revertir-pre-kardex/`

Reversion de aprobacion:

- Disponible para documentos confirmados.
- Elimina los movimientos generados por ese documento.
- Devuelve el documento a `Pre-Kardex`.
- Solo se permite si esos movimientos siguen siendo los ultimos movimientos del producto.
- Si ya existen movimientos posteriores, se bloquea para proteger saldos historicos.
- Ruta POST: `/documentos/<id>/revertir-aprobacion/`

Devolver a pendiente:

- Disponible para documentos en `Pre-Kardex` o `Confirmado`.
- Limpia producto, factor, cantidad base y estado de clasificacion en sus detalles.
- Si el documento estaba confirmado, elimina sus movimientos Kardex y recalcula saldos posteriores de los productos afectados desde la fecha del documento.
- Devuelve el documento a `Pendiente de clasificacion`.
- Boton: `Devolver a pendiente`.
- Ruta POST: `/documentos/<id>/devolver-pendiente/`

## Stock inicial

La pantalla de stock inicial permite:

- Registrar stock inicial por producto.
- Editar stock inicial si no existen movimientos posteriores.
- Bloquear edicion si el producto ya tiene otros movimientos.
- Registrar auditoria de creacion y edicion.

Rutas:

```text
/stock-inicial/
/stock-inicial/<movimiento_id>/editar/
```

## Proceso de trillado de cafe

La pantalla `Trillado` permite registrar la transformacion interna de cafe pergamino a cafe exportable y subproductos.

Ruta:

```text
/procesos/trillado/
```

Rutas:

```text
/procesos/trillado/
/procesos/trillado/nuevo/
/procesos/trillado/<id>/
/procesos/trillado/<id>/editar/
/procesos/trillado/<id>/confirmar/
/procesos/trillado/<id>/anular/
```

Flujo:

1. Registrar un borrador de proceso con codigo autogenerado, fecha de proceso, lote opcional, factura externa relacionada opcional, cafe pergamino consumido, cantidad, costo de proceso USD y observaciones.
2. Registrar los resultados en una tabla editable: cafe exportable, subproductos dinamicos y merma.
3. El tipo de cambio se toma automaticamente desde SUNAT para la fecha del proceso y se muestra como dato de lectura.
4. Revisar balance fisico, resumen valorizado y rendimientos.
5. Confirmar Kardex para generar movimientos historicos.
6. Si se necesita corregir un proceso confirmado, anularlo y registrar un nuevo proceso.

Mientras el proceso esta en borrador se puede editar. Si se cambia la fecha antes de confirmar, el sistema vuelve a tomar el tipo de cambio SUNAT venta registrado para la fecha del proceso. Una vez confirmado, el tipo de cambio queda guardado y no cambia automaticamente.

Reglas de valorizacion:

- `costo_pergamino_consumido = cantidad_pergamino_kg * costo_promedio_pergamino`.
- `costo_proceso_soles = costo_proceso_usd * tipo_cambio_fecha_proceso`.
- `costo_total_proceso = costo_pergamino_consumido + costo_proceso_soles`.
- `valor_mercado_subproducto_soles = valor_mercado_subproducto_usd * tipo_cambio_fecha_proceso`.
- `costo_total_subproductos = suma(cantidad_subproducto * valor_mercado_subproducto_soles)`.
- `costo_exportable = costo_total_proceso - costo_total_subproductos`.
- `costo_unitario_exportable = costo_exportable / cantidad_exportable`.

El tipo de cambio se guarda en el proceso como `tipo_cambio_fecha_proceso`. El campo no es editable en pantalla: la app toma el tipo de cambio SUNAT venta registrado para la fecha del proceso. Una vez confirmado, el tipo de cambio queda congelado y no cambia aunque se actualice la tabla de tipo de cambio.

Validaciones principales:

- Fecha obligatoria.
- Tipo de cambio mayor que cero.
- Costo de proceso USD mayor o igual que cero.
- Stock suficiente de cafe pergamino a la fecha del proceso.
- `cantidad_pergamino = cantidad_exportable + cantidad_subproductos + merma`.
- El costo total de subproductos no puede superar el costo total del proceso.
- El costo exportable no puede ser negativo.
- La cantidad exportable debe ser mayor que cero.
- Si se confirma un proceso historico y existen movimientos posteriores, el sistema recalcula los saldos posteriores de los productos afectados desde la fecha del proceso.

Al confirmar:

- Se genera `PROCESO_SALIDA` para el cafe pergamino.
- Se genera `PROCESO_ENTRADA` para el cafe exportable con costo residual.
- Se genera `PROCESO_ENTRADA` para cada subproducto con valor de mercado convertido a soles.
- Se registran costo de proceso USD, tipo de cambio usado, costo equivalente en soles y merma fisica no valorizada.

Los procesos confirmados no se editan directamente; cualquier correccion debe hacerse mediante anulacion/nuevo proceso. La anulacion registra movimientos `REVERSION` y solo se permite si los movimientos del proceso siguen siendo los ultimos de los productos involucrados.

## Reportes

Pantallas disponibles:

- Stock actual.
- Kardex por producto.
- Kardex valorizado SUNAT por producto, con formato 13.1.
- Documentos importados.
- Movimientos por documento.
- Documentos por mes.
- Exportacion Excel `.xlsx` en los reportes.

Rutas:

```text
/reportes/
/reportes/stock-actual/
/reportes/kardex-producto/
/reportes/kardex-sunat-producto/
/reportes/documentos-mensual/
/reportes/documentos-mensual/<anio>/<mes>/
/reportes/documentos-importados/
/reportes/movimientos-documento/
```

### Documentos por mes

El reporte `Documentos por mes` resume cuantas facturas de venta, facturas de compra y liquidaciones de compra existen por anio y mes, usando la fecha de emision del XML/documento.

Filtros:

- Fecha desde y fecha hasta.
- Tipo de operacion: todos, compra o venta.
- Tipo de documento: todos, factura o liquidacion de compra.
- Entidad opcional.
- Estado opcional. Por defecto excluye anulados.

Columnas resumidas:

- Anio, mes, facturas de venta, facturas de compra, liquidaciones de compra y total de documentos.
- Total ventas, total compras, total liquidaciones y total general.

Tambien incluye una vista de detalle por mes con fecha de emision, operacion, tipo de documento, serie, numero, RUC/nombre de entidad, moneda, base imponible, IGV, total y estado.

### Movimientos por documento

El reporte `Movimientos por documento` permite filtrar por:

- Documento especifico.
- Fecha desde y fecha hasta.
- Tipo de documento: factura o liquidacion de compra.
- Moneda.

El grid permite ordenar por cabeceras, incluyendo fecha, documento, tipo de documento, moneda, producto, entrada, salida, costo y saldo.

### Kardex valorizado SUNAT por producto

La pantalla `Kardex valorizado SUNAT` genera el Formato 13.1: `Registro de Inventario Permanente Valorizado - Detalle del Inventario Valorizado`.

Incluye:

- Filtro obligatorio por producto.
- Filtro opcional por fecha inicial y final.
- Cabecera con periodo, RUC, razon social, establecimiento, codigo de existencia, tipo de existencia, descripcion, unidad y metodo de valuacion.
- Columnas de documento: fecha, tipo, serie y numero.
- Tipo de operacion.
- Entradas: cantidad, costo unitario y costo total.
- Salidas: cantidad, costo unitario y costo total.
- Saldo final: cantidad, costo unitario y costo total.

La valorizacion usa los movimientos confirmados en `MovimientoKardex`, por lo que el reporte depende de que los documentos hayan sido aprobados en Pre-Kardex.

### Exportacion Excel

Los reportes operativos incluyen boton `Exportar Excel` y usan los mismos filtros aplicados en pantalla. Si `openpyxl` esta disponible generan `.xlsx`; si el entorno no tiene `openpyxl`, generan `.xls` compatible con Excel para no impedir que la app cargue.

- Stock actual.
- Kardex por producto.
- Kardex valorizado SUNAT por producto.
- Documentos importados.
- Movimientos por documento.
- Documentos por mes.

La exportacion se activa con el parametro `export=excel` en la URL del reporte.

## Pantallas recuperadas o ajustadas

- Dashboard.
- Importacion XML por lote.
- Documentos importados con filtros, ordenamiento y clasificacion masiva.
- Documentos pendientes.
- Comprobante de documento.
- Clasificacion individual.
- Clasificacion por bloque de detalles.
- Clasificacion por lote desde Documentos.
- Entidades.
- Productos.
- Equivalencias XML.
- Stock inicial y edicion de stock inicial.
- Pre-Kardex por aprobar.
- Reversion de Pre-Kardex.
- Reversion de aprobacion.
- Boton para devolver documentos a pendiente desde Pre-Kardex o Confirmado.
- Proceso de trillado de cafe con diseno tipo documento, tipo de cambio automatico, costo de proceso USD, subproductos dinamicos y costo residual exportable.
- Tipo de cambio SUNAT.
- Mantenimiento DB para backup y restauracion de SQLite.
- Reportes.
- Kardex valorizado SUNAT por producto.
- Reporte mensual de documentos.
- Filtros de movimientos por documento por tipo, fecha y moneda, con cabeceras ordenables.
- Exportacion Excel de reportes.
- Mejora visual global: tipografia Inter mas liviana, tablas con mas padding, formularios mas legibles, KPI cards balanceadas y reporte SUNAT con scroll horizontal y columnas mas respirables.

## Pruebas cubiertas

La suite actual cubre, entre otros:

- Importacion de facturas y liquidaciones.
- Moneda USD con tipo de cambio SUNAT.
- Normalizacion de unidades `KGM`, `LBR` y `NIU` con kilos o quintales en descripcion.
- Correccion de equivalencias antiguas con factor incorrecto para libras o quintales.
- Inferencia y correccion de DNI/RUC.
- Rechazo de XML duplicado.
- Listado de documentos, filtros y ordenamiento.
- Clasificacion individual y por bloque.
- Clasificacion masiva desde Documentos.
- Pre-Kardex y aprobacion individual/bloque.
- Confirmacion historica con recalculo de movimientos posteriores.
- Reversion de Pre-Kardex sin borrar XML.
- Reversion de aprobacion con bloqueo por movimientos posteriores.
- Devolucion de documentos a pendiente, incluyendo confirmados con recalculo de saldos posteriores.
- Stock inicial y edicion controlada.
- Proceso de trillado: tipo de cambio SUNAT automatico, costo de proceso en soles, costo residual exportable, subproductos a valor de mercado convertido a soles, confirmacion historica y anulacion con reversiones.
- Reportes principales.
- Kardex valorizado SUNAT por producto.
- Reporte mensual de documentos y detalle por mes.
- Reporte de movimientos por documento con filtros y ordenamiento.
- Exportacion Excel `.xlsx` o `.xls` compatible segun dependencias disponibles.
- Mantenimiento DB: acceso staff, descarga de backup y rechazo de archivos no SQLite.
- Formatos de numero y fecha.

## Recomendaciones para no volver a perder avances

- No trabajar directamente sobre un disco extraible con errores.
- Mover el proyecto a un disco interno o SSD estable.
- Usar Git y hacer commits pequenos despues de cada correccion importante.
- Subir el repositorio a GitHub como respaldo remoto.
- Mantener copias de `db.sqlite3` si se necesita conservar datos cargados localmente.
- Usar `Sistema > Mantenimiento DB` para descargar backups antes de restaurar o hacer cambios grandes de datos.
- Separar respaldos de codigo y respaldos de base de datos.

## Preparacion para GitHub

Archivos agregados para publicar el proyecto:

- `.gitignore`: excluye entornos virtuales, base SQLite local, logs, cache Python, `.env` y artefactos locales.
- `requirements.txt`: dependencias reproducibles (`Django` y `openpyxl`).
- `.env.example`: variables necesarias sin secretos reales.

Importante: la carpeta `.git` local encontrada esta vacia y Git no reconoce el directorio como repositorio. Antes de subir, inicializa Git desde la raiz del proyecto:

```powershell
git init
git config --global --add safe.directory F:/DEVELOPER/DEV_APP/KARDEXML
git add .
git commit -m "Estado recuperado de KARDEXML"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/TU_REPO.git
git push -u origin main
```

Antes de ejecutar `git add .`, confirma que no se incluiran archivos locales sensibles:

```powershell
git status --short
```

No deberian aparecer `db.sqlite3`, `.ven/`, `.venv/`, `.env`, `*.log` ni `__pycache__/`.

## Pendientes tecnicos

- Reconstruir migraciones Django definitivas y quitar `MIGRATION_MODULES = {"kardex": None}` cuando el esquema este estabilizado.
- Confirmar con XML reales de SUNAT todos los formatos de liquidacion usados por la empresa.
- Crear respaldo Git/GitHub del estado actual.
- Revisar politicas de seguridad para produccion: `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS` y manejo de credenciales.

Para guardar avances en GitHub, usa este ciclo cuando termines un cambio importante:

```powershell
python manage.py check
python manage.py test
git status
git add .
git commit -m "Describe aqui el cambio"
git push
```

Regla practica: haz commit cuando algo ya funciona y paso pruebas.
