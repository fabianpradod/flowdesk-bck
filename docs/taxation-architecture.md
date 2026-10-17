# Arquitectura tributaria genérica

FlowDesk no debe implementar un módulo distinto por país. El país o jurisdicción,
el régimen, los impuestos, las tasas y las reglas son configuración versionada por
empresa/tenant. El motor central solo interpreta el subconjunto declarativo seguro
que soporta.

## Configuración tributaria declarativa

`TaxProfile` es la configuración versionada de un tenant. Además de
jurisdicción, régimen y vigencia, puede conservar nombre, descripción, moneda
por defecto, precisión, modo de redondeo y metadata acotada. `TaxDefinition`
describe impuestos configurables mediante código, nombre, tipo, categoría,
tasa por defecto, prioridad, composición y metadata. El modelo no presupone
que exista un único impuesto ni un nombre fiscal universal.

Las categorías son datos del perfil y preservan semánticas distintas para
`STANDARD`, `TAXABLE`, `ZERO_RATED`, `EXEMPT`, `NON_TAXABLE`, `WITHHOLDING` y
`OTHER`. El motor no transforma automáticamente exento, tasa cero o fuera de
ámbito en otra categoría.

`TaxRule` utiliza condiciones y resultados declarativos seguros. Sus scopes
`INPUT_TAX` y `WITHHOLDING` siguen disponibles, junto con scopes genéricos para
clasificación o salida. Las condiciones pueden leer campos de la operación y
metadata mediante rutas de diccionario acotadas. Los resultados pueden ajustar
categoría, código o tasa, además de elegibilidad y efecto de retención. No se
ejecuta Python de la configuración: no se utiliza `eval`, `exec` ni código
almacenado.

El `TaxEngine` ordena los impuestos por prioridad y puede calcular componentes
múltiples. Una definición `is_compound` aplica su base sobre la base original
más los componentes previos, sin introducir una fórmula legal de jurisdicción.
La precisión y el redondeo pertenecen al perfil y usan exclusivamente
`Decimal`. La simulación y los detalles del cálculo conservan código, tasa,
base, importe y versión del perfil para trazabilidad.

## Versionado y vigencia temporal

Los perfiles son versiones del tenant y se resuelven con una fecha explícita:

```text
effective_from <= fecha < effective_until
```

`effective_until = NULL` significa que no existe fecha de finalización. Por
ejemplo, una versión que termina el `01/07/2026` no aplica el día 1 de julio;
ese día comienza la siguiente versión:

```text
Perfil V1: 01/01/2026 -> 01/07/2026
Perfil V2: 01/07/2026 -> NULL
```

La persistencia valida que no existan perfiles solapados para el mismo ámbito
lógico del tenant. Las reglas también pueden tener su propia vigencia y se
filtran por la fecha de la operación, tanto para `INPUT_TAX` como para
`WITHHOLDING`. Un hueco de configuración no se rellena silenciosamente con la
versión actual: la operación queda sin perfil aplicable y el cálculo lo reporta.

Los documentos fiscales conservan sus tasas, importes, componentes y
retenciones como snapshots. Cambiar o crear una versión futura no recalcula
documentos históricos. Las ventas continúan usando `Venta.tasa_impuesto` y
`Venta.impuesto`; el cálculo periódico resuelve el perfil correspondiente a la
fecha de cada documento, incluso cuando el período atraviesa varios cambios.
Los resultados incluyen identificadores y fechas de la versión usada cuando
existen operaciones detalladas.

## Separación de responsabilidades

- **Tax Engine**: calcula resultados a partir de una operación y un perfil; no
  conoce países ni fórmulas legales externas.
- **Tax Configuration**: perfil versionado del tenant: jurisdicción, régimen,
  vigencia, impuestos y reglas.
- **Tax Rule**: condición y cálculo declarativos, con operadores y cálculos
  permitidos explícitamente; nunca Python arbitrario.
- **Fiscal Document**: documento fiscal u operación que conserva sus snapshots
  históricos. Las ventas existentes siguen usando `Venta.tasa_impuesto` y
  `Venta.impuesto`.
- **Import Adapter**: convierte datos de formatos externos al dominio; no calcula
  impuestos por su cuenta.
- **Country Localization**: configuración o adaptadores de una jurisdicción;
  no contiene el motor tributario central.

El perfil se guarda bajo `ConfiguracionTributaria` dentro del esquema tenant
autenticado. El endpoint legacy de tasa y el cálculo actual de ventas se mantienen
sin cambios funcionales. La migración al motor genérico podrá hacerse después,
conservando los snapshots históricos.

El modelo ya distingue `TAXABLE`, `ZERO_RATED` y `EXEMPT`, y deja campos para
elegibilidad de crédito, retenciones y saldos a favor. La elegibilidad de impuesto
de entrada se expresa mediante reglas con `scope: INPUT_TAX` y el resultado
`eligible_for_input_credit`; si no existe una regla aplicable, la operación no
genera crédito por defecto.

## Crédito fiscal configurable

La simulación `POST /api/v1/tax/calculate` trabaja con operaciones tributarias en
memoria. No crea compras ni documentos fiscales. El flujo es:

```text
Input Tax
    ↓
Eligibility Rule
    ↓
Tax Credit
    ↓
Tax Debit
    ↓
Net Tax
    ↓
Tax Payable / Carry Forward
```

El motor conserva por separado `tax_debit`, `tax_credit` y `net_tax`. El pago se
calcula usando `current_period_credit + prior_carry_forward`; si el crédito
disponible excede el débito, el remanente queda en `carry_forward` y no se pierde.
La elegibilidad, disponibilidad del concepto de crédito y arrastre son decisiones
de configuración, no conocimiento del país o del régimen dentro del código.

Las ventas históricas continúan usando sus snapshots (`Venta.impuesto` y
`Venta.tasa_impuesto`). Los documentos fiscales importados mediante CSV/XLSX ya
son una fuente persistida para el reporte y el cálculo periódico; no convierten
movimientos de inventario en compras fiscales.
## Documentos fiscales de entrada

Los documentos fiscales persistidos son información genérica, no una compra
comercial ni una localización de país:

```text
Fiscal Document
      ↓
Tax Components
      ↓
Normalization
      ↓
Tax Engine
      ↓
Tax Result
```

`FiscalDocument` conserva el documento, sus líneas, componentes tributarios,
moneda, estado, jurisdicción y snapshots de importes. `ImportBatch` registra la
fuente, archivo, filas y estado de una carga sin copiar el archivo completo por
documento. El CRUD de documentos no calcula crédito fiscal ni transforma
movimientos de inventario.

`app/taxation/fiscal_adapter.py` convierte los componentes guardados en
`TaxableOperation`, que es la entrada del `TaxEngine`. El importador CSV/XLSX
ya convierte fuentes externas en documentos fiscales; futuros `ImportAdapter`
para otros formatos conservarán la misma separación. Ninguna de estas piezas
contiene legislación específica.

La actualización de un documento solo permite cambiar estado y metadatos; bases,
impuestos, moneda, identificadores y demás valores históricos permanecen
inmutables después del registro. La detección de duplicados es una señal de
identidad potencial —basada en emisor, tipo, serie, número y autorización cuando
están disponibles—, no una unicidad legal universal.
## Importación universal CSV/XLSX

El flujo de importación es explícito y separado del cálculo tributario:

```text
CSV/XLSX
   ↓
ImportBatch
   ↓
Column Mapping
   ↓
Preview
   ↓
Validation
   ↓
Normalization
   ↓
FiscalDocument
   ↓
TaxComponent
   ↓
TaxEngine
```

El importador solo transforma datos externos al modelo fiscal normalizado. No
determina legislación, no calcula crédito/débito y no convierte movimientos de
inventario en documentos fiscales. Los mappings son configuración del tenant y
pueden reutilizarse para archivos del mismo formato.

El límite técnico actual es `10 MiB` por archivo y `10.000` filas. Está centralizado
en `app/services/importer.py`; un archivo que excede el límite recibe `422` y no
crea un batch. CSV admite la codificación declarada por el perfil/mapping (UTF-8
por defecto), mientras XLSX se lee como valores sin ejecutar macros ni fórmulas.
Las fechas ambiguas requieren `locale` explícito (`DMY` o `MDY`).

Los errores bloquean la ejecución; los warnings se reportan y no necesariamente
impiden importar. Las filas válidas pueden importarse parcialmente. Documentos
duplicados se reportan y no se sobrescriben. La disponibilidad temporal del
archivo subido se mantiene en el proceso de la aplicación para completar preview,
validación y ejecución; la persistencia de archivos y limpieza de almacenamiento
serán responsabilidad de una fase posterior de producción.

### Perfil de importación y normalización

`ImportMapping` funciona también como el perfil reutilizable de importación del
tenant. Además de mapear columnas, puede declarar formato, codificación,
delimitador, fila de encabezados, fila inicial de datos, formato de fecha,
separadores numéricos y claves `group_by`. No existe un segundo motor ni una
configuración global: los mappings se guardan en el contexto aislado del tenant.

La normalización distingue el valor original de su representación interna. Los
identificadores fiscales se conservan como texto, los importes como `Decimal`, y
las filas pueden agruparse declarativamente para producir un documento con
múltiples líneas, impuestos o retenciones. Preview devuelve métricas de filas,
campos mapeados, columnas no mapeadas, muestras normalizadas y candidatos a
duplicado sin persistir documentos.

Ejemplo genérico de mapping:

```json
{
  "Fecha externa": "issue_date",
  "Identificador emisor": "issuer.tax_identifier",
  "Base": "taxes[0].taxable_base",
  "Impuesto externo": "taxes[0].amount",
  "Retención externa": "taxes[1].withholding_amount"
}
```

Estos nombres son datos del archivo, no requisitos fiscales. El importador
transforma y valida; no decide elegibilidad, crédito, débito ni legislación.
En consecuencia, `Importación ≠ legislación` y `Normalización ≠ cálculo fiscal`.

## Clasificación fiscal declarativa

La clasificación es una capa posterior a la importación y anterior al cálculo:

```text
Importación
    ↓
Normalización
    ↓
FiscalClassifier
    ↓
ClassificationResult
    ↓
FiscalAdapter
    ↓
TaxableOperation
    ↓
TaxEngine
    ↓
TaxPeriodService
```

`FiscalClassifier` evalúa reglas declarativas con el DSL seguro existente. Puede
resolver dirección (`INPUT`/`OUTPUT`), categoría, código, base, calculabilidad y
elegibilidad, además de conservar `profile_version`, `rule_version` y la
vigencia que produjo la decisión. Las reglas se evalúan usando la fecha fiscal
del documento; no se utiliza la fecha actual del servidor.

La prioridad es determinista. Una coincidencia de menor prioridad numérica se
selecciona primero; dos resultados incompatibles con la misma prioridad generan
un error explícito. Cuando no hay una clasificación suficiente, el resultado
queda marcado como no calculable con una razón genérica, como
`NO_APPLICABLE_RULE` o `MISSING_REQUIRED_FIELD`.

Los `TaxComponent` almacenados siguen siendo snapshots históricos. El adapter
los transforma sin recalcular sus bases, tasas o importes. La clasificación no
es un segundo motor: `TaxEngine` continúa siendo responsable del crédito,
débito, retenciones, saldo a favor y demás resultados económicos. La
simulación puede usar una configuración histórica distinta de la persistida,
pero nunca modifica el documento.

Las categorías por línea se conservan individualmente, incluyendo documentos
con componentes `ZERO_RATED`, `EXEMPT` o `NON_TAXABLE`. La elegibilidad de
crédito y los efectos de retención siguen dependiendo de reglas configuradas,
no de nombres de países ni de fórmulas codificadas.

## Escenarios fiscales end-to-end

La suite de escenarios verifica la composición completa de las capas sin
introducir una nueva abstracción productiva:

```text
Importación
    ↓
Normalización
    ↓
Clasificación
    ↓
Cálculo
    ↓
Período
    ↓
Reporte
```

Los escenarios usan perfiles, definiciones, reglas, documentos, líneas,
componentes, mappings y batches genéricos construidos en los tests. Cubren
impuestos estándar, crédito, débito, saldo a favor, categorías no estándar,
múltiples impuestos, composición, retenciones, vigencias, cambios de versión,
ambigüedad, CSV y trazabilidad hacia el reporte.

Las tasas y códigos de estos escenarios son datos artificiales de prueba; no
representan legislación de ninguna jurisdicción. La suite también verifica que
los componentes históricos no se recalculen cuando cambia el perfil, que las
monedas incompatibles se rechacen según la política existente y que el
aislamiento tenant se mantenga en los flujos ya cubiertos por las pruebas de
servicio y API.

## Administración y simulación tributaria

La configuración se administra por tenant mediante los endpoints existentes:

```text
GET  /api/v1/tax/profile
PUT  /api/v1/tax/profile
POST /api/v1/tax/profile/validate
GET  /api/v1/tax/rules
POST /api/v1/tax/rules
POST /api/v1/tax/calculate
```

`PUT /profile` conserva las versiones anteriores y aplica la vigencia temporal;
`POST /profile/validate` ejecuta validación declarativa sin persistir cambios.
La validación comprueba rangos, reglas, condiciones seguras, referencias a
impuestos y determinismo básico. El perfil se resuelve por fecha, o por
`profile_version` cuando la simulación lo solicita explícitamente.

La simulación recibe operaciones en memoria y reutiliza el mismo
`FiscalClassifier` y `TaxEngine` del cálculo periódico. Cuando una operación
incluye semántica documental, la clasificación se aplica antes del motor y la
respuesta conserva versiones de perfil/regla, tasas, bases, crédito,
retenciones, neto, payable y carry-forward. Las operaciones sin esos campos
mantienen el contrato legacy de simulación.

La simulación no crea `FiscalDocument`, `TaxComponent` ni `ImportBatch`, y no
modifica ventas ni documentos históricos. Todas las lecturas y escrituras usan
el tenant derivado del usuario autenticado; no se aceptan `tenant_id` ni
`schema_name` para seleccionar configuración. Esta capacidad administra
configuración interna y no reemplaza declaraciones, libros oficiales ni
interpretación automática de leyes nacionales.
## Tax Period Calculation

El cálculo periódico es un orquestador y no un segundo motor:

```text
Tax Period Calculation
        ↓
Sales historical snapshots
        ↓
Tax Debit
        +
Fiscal Documents
        ↓
Input Tax
        ↓
Eligibility Rules
        ↓
Tax Credit
        ↓
TaxEngine
        ↓
Tax Result
```

`TaxPeriodService` reutiliza el débito histórico de ventas, obtiene documentos
`direction=INPUT`, adapta sus `TaxComponent` mediante `fiscal_adapter` y entrega
las operaciones al `TaxEngine`. No persiste saldos ni crea declaraciones fiscales.
Los estados `CANCELLED` y `VOIDED` no son calculables por defecto; una regla
`INPUT_TAX` puede declarar explícitamente `is_calculable` si una configuración
válida requiere otro tratamiento. La elegibilidad continúa siendo falsa cuando
no existe una regla aplicable.

El endpoint `POST /api/v1/tax/period/calculate` devuelve el período, débito,
crédito, neto, pago, carry-forward y conteos de trazabilidad. Si los documentos
de entrada del período usan monedas diferentes, el cálculo se rechaza porque no
existe conversión configurada.
## Estado actual del reporte tributario

El reporte tributario es un reporte interno de control, no una declaracion
fiscal. Su flujo actual integra documentos de entrada importados:

```text
CSV/XLSX
  -> ImportBatch
  -> Column Mapping
  -> Preview
  -> Validation
  -> Normalization
  -> FiscalDocument
  -> TaxComponent
  -> TaxPeriodService
  -> TaxEngine
```

Las compras del reporte provienen de `FiscalDocument` con direccion `INPUT` y
respetan el tenant, el periodo, la moneda, el estado y los snapshots historicos
del documento. La elegibilidad del credito usa las reglas declarativas
`INPUT_TAX`; el reporte no contiene reglas de pais ni calcula impuestos por su
cuenta. Las ventas siguen utilizando los snapshots historicos de `Venta`.

`TaxPeriodService` es la orquestacion compartida por el calculo periodico y el
resumen del reporte. No se persiste automaticamente un carry-forward y FlowDesk
todavia no implementa filing o declaraciones fiscales. Los importadores CSV/XLSX
ya existen; un futuro `ImportAdapter` seguira siendo responsable solamente de
normalizar fuentes externas, no de interpretar legislacion.
## Withholding / Retenciones

Una retención es un componente tributario normalizado dentro de
`TaxComponent`, no una tabla ni un modelo específico de país. Puede conservar
su identificador, código y nombre del impuesto, base, tasa, importe, moneda,
tipo, rol, objeto de aplicación y el efecto configurado. El documento conserva
estos valores como snapshot histórico.

```text
FiscalDocument
      -> TaxComponent(is_withholding=true)
      -> TaxRule(scope=WITHHOLDING)
      -> TaxEngine
      -> withholding_tax + Tax Result
```

El `TaxEngine` mantiene `withholding_tax` separado de `tax_credit` y
`tax_debit`. Una retención no se convierte automáticamente en crédito. Una regla
declarativa puede seleccionar `REDUCE_PAYABLE`, `INCREASE_CREDIT` o
`INFORMATIONAL`; sin esa indicación, el componente se conserva como informativo.
Las reglas usan únicamente el DSL seguro existente y no ejecutan código
almacenado.

CSV/XLSX puede mapear múltiples componentes de retención sin reconocer nombres
legales de columnas. `TaxPeriodService` los incorpora junto con documentos de
entrada/salida y el reporte SMALL_TAXPAYER puede mostrar el importe real cuando
existe una fuente persistida. No se persiste una declaración ni se recalculan
retenciones históricas.

FlowDesk no determina por código qué impuestos están sujetos a retención ni qué
porcentajes corresponden a una jurisdicción. Esa información pertenece a la
configuración tributaria versionada del tenant.

## Flujo tributario end-to-end

La prueba principal para un tenant nuevo ejecuta las capas existentes en este
orden:

```text
Configuración
    → Validación
    → Importación
    → Normalización
    → Clasificación
    → Cálculo
    → Período
    → Reporte
```

El perfil, las reglas, el mapping, el batch, los documentos y sus componentes
son datos tenant-scoped. El CSV se transforma mediante `ImportMapping`; los
valores monetarios se conservan como `Decimal` y las filas mantienen su origen.
`FiscalClassifier` interpreta la semántica configurada, `TaxPeriodService`
orquesta el período y el reporte reutiliza sus resultados sin recalcular ventas
históricas.

Los escenarios usan `jurisdiction = TEST`, códigos y tasas artificiales. No
representan normativa nacional. Las simulaciones no persisten documentos,
componentes ni batches; los documentos importados sí conservan snapshots y
trazabilidad. La política actual rechaza períodos con múltiples monedas cuando
no existe conversión configurada; no se introduce conversión automática.