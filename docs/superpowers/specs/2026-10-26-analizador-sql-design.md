# Analizador SQL, nivel 1

Fecha: 2026-10-26

MojandoseLosDedosConSQL es una aplicación local que explica una sentencia SQL en español. El núcleo es determinista: parsea con SQLGlot, recorre el árbol y aplica reglas comprobables. La optimización y el modelo de lenguaje son módulos posteriores y no forman parte de este diseño.

## Alcance

Este diseño cubre el nivel 1.

Entra:

- Una página web local para pegar una o varias sentencias y elegir el dialecto.
- Dialectos: PostgreSQL, MySQL, SQLite y SQL Server.
- Cualquier sentencia que SQLGlot acepte en el dialecto elegido, con el mismo modelo de informe.
- Árbol de componentes lógicos: consulta, CTE, subconsulta y `UNION`.
- Explicaciones en español por plantilla, ligadas a tablas, columnas, cláusulas y relaciones.
- Pasos en orden lógico, distintos del plan físico del motor.
- Cuatro advertencias demostrables sin esquema.
- SQL formateado en el dialecto elegido.
- Errores de sintaxis y de petición con textos explícitos.

Queda fuera y se diseñará aparte:

- Nivel 2: importar el esquema, claves primarias y foráneas, y advertencias de cardinalidad o duplicados en agregaciones.
- Nivel 3: preguntas en lenguaje natural, modelo de lenguaje y envío del SQL fuera del equipo.
- Recomendaciones de reescritura y cualquier otro análisis de optimización.
- Planes de ejecución.
- Comparar dos consultas y exportar informes.
- Historial, cuentas de usuario y conexión a una base de datos.

## Arquitectura

La biblioteca no sabe que existe una web. La web no importa SQLGlot. La única entrada pública es:

```python
def analizar(sql: str, dialecto: str) -> Informe:
    ...
```

`analizar` devuelve siempre un `Informe` para una consulta analizable, incluido cuando hay errores de sintaxis o fallos de una fase. Las excepciones que salen de `analizar` son las de `errores.py`: `DialectoNoSoportado` si el dialecto no está admitido, y cualquier excepción no prevista que ocurra antes de poder construir el informe. `api.py` convierte los fallos de una sentencia ya parseada en entradas del informe. No los presenta como SQL mal escrito.

Cinco componentes:

1. **Analizador SQL** (`parser.py`). Único módulo que importa SQLGlot. Convierte el texto en un `Nodo` propio o en errores de sintaxis.
2. **Analizador semántico** (`semantica.py`). Recibe ese `Nodo` y lo transforma en componentes. No importa SQLGlot.
3. **Generador de explicaciones** (`explicacion.py`). Rellena los textos en español a partir de los componentes.
4. **Detector de advertencias** (`advertencias.py`). Evalúa reglas sobre la forma de expresión que expone `parser.py`. Si una regla no puede demostrar el riesgo, no avisa.
5. **Interfaz** (`web/`). Recibe la petición, llama a `analizar` y presenta el JSON.

`dialectos.py` solo traduce los nombres de la petición (`postgresql`, `mysql`, `sqlite`, `sqlserver`) a los nombres internos (`postgres`, `mysql`, `sqlite`, `tsql`). No importa SQLGlot.

Módulos de apoyo:

- `modelo.py` define el informe.
- `formato.py` recibe un `Nodo` y el dialecto, y pide a `parser.normalizar` el SQL normalizado.
- `mensajes.py` guarda los textos fijos.
- `errores.py` define `ErrorAnalizador`, `DialectoNoSoportado` y `ErrorDeFase`.
- `api.py` coordina las fases y construye el informe. Atrapa `ErrorDeFase` y las excepciones inesperadas de cada fase. No importa SQLGlot.

```
pyproject.toml
src/analizador/
  __init__.py          # expone analizar
  api.py
  dialectos.py
  errores.py
  parser.py
  modelo.py
  semantica.py
  explicacion.py
  advertencias.py
  formato.py
  mensajes.py
web/
  app.py
  plantillas/index.html
  estaticos/estilo.css
  estaticos/app.js
tests/
  test_analizar.py
  test_advertencias.py
  test_errores.py
  test_web.py
```

Python 3.11 o superior. Dependencias de ejecución: `sqlglot==30.25.0`, `fastapi`, `uvicorn`, `jinja2`. La versión de SQLGlot va fijada. Dependencias de prueba: `pytest`, `httpx`. El comportamiento de scripts, huecos vacíos y `TokenError` descrito aquí está comprobado con la 30.25.0.

Instalación y arranque, desde la raíz del repositorio:

```
pip install -e ".[dev]"
uvicorn web.app:app --reload
```

`pyproject.toml` declara el paquete `analizador` en `src` y deja `web` importable desde la raíz.

## Frontera con SQLGlot

`parser.py` entrega el resultado ya analizado. El resto de las fases no llama a `sqlglot.parse`, no importa `sqlglot` y no recibe la expresión original de la biblioteca.

```python
def parsear(sql: str, dialecto: str) -> ResultadoParseo:
    ...

def normalizar(nodo: Nodo, dialecto: str) -> str:
    ...

def bloque(nodo: Nodo) -> Bloque:
    ...

def expresion(nodo: Nodo) -> Expresion:
    ...
```

`ResultadoParseo` trae o bien errores de sintaxis, o bien una `SentenciaSintactica` por expresión no vacía. Cada una tiene `indice`, `tipo` y `nodo`.

`Bloque` describe solo el nivel directo de ese nodo: CTE, ramas de una unión, subconsultas, tablas, relaciones, cláusulas y proyecciones. El interior de una CTE, de una rama o de una subconsulta sigue siendo un `Nodo` hijo, sin desplegar.

`Expresion` es la forma que usan las advertencias: columna, literal, `NULL`, comparación, `IS NULL`, `IS NOT NULL`, `AND`, `OR`, `NOT`, agregación, ventana, asterisco, alias u otra. Una columna de esa forma trae el nombre escrito y el calificador escrito, o ninguno. No trae una tabla deducida.

`api.py` encadena las fases así: `parsear`, luego por sentencia `formato.formatear(nodo, dialecto)`, `semantica.componentes(nodo)`, `explicacion.rellenar` y `advertencias.evaluar`. El `Nodo` acompaña al componente mientras dura ese recorrido y no aparece en el JSON.

## Dialecto

Valores aceptados en la API y en el JSON: `postgresql`, `mysql`, `sqlite`, `sqlserver`.

Correspondencia interna con SQLGlot: `postgres`, `mysql`, `sqlite`, `tsql`.

La página muestra PostgreSQL, MySQL, SQLite y SQL Server. El selector no tiene valor vacío: el primero visible es PostgreSQL, y el usuario puede cambiarlo antes de analizar.

## Flujo

1. La web comprueba el cuerpo. Si no es JSON, falta `sql`, falta `dialecto`, `sql` no es un texto, el dialecto no está admitido o `sql` supera 1048576 bytes en UTF-8, responde 400 con el mensaje de esa causa y no llama al análisis.
2. `analizar` recibe el dialecto. Si no está admitido, lanza `DialectoNoSoportado` con el mismo texto que la web usa para el dialecto desconocido. La web lo convierte en 400.
3. Si el texto está vacío o solo tiene espacios, el informe trae el error de consulta vacía y ninguna sentencia.
4. Los comentarios se reconocen con el tokenizador de SQLGlot, sin una expresión regular sobre el texto, para no tocar el contenido de las cadenas. Si todos los tokens son comentarios o espacios, el informe trae el error de solo comentarios y ninguna sentencia.
5. El parser analiza el script completo con `sqlglot.parse` y el dialecto elegido. En la 30.25.0, `SELECT 1; SELECT 2` devuelve dos expresiones. `SELECT 1;; SELECT 2` devuelve tres posiciones y la del medio es `None`. Un error de sintaxis en cualquier sentencia lanza `ParseError` para el script entero y no deja sentencias parciales.
6. `ParseError` y `TokenError` son errores de sintaxis. El informe trae esos errores y ninguna sentencia. No hay árbol, pasos ni advertencias. `TokenError` no hereda de `ParseError`; un fallo al tokenizar, como una comilla o un comentario sin cerrar, sigue siendo sintaxis y no un fallo interno. Cualquier otra excepción durante el parseo, incluida `UnsupportedError`, no se traduce como SQL mal escrito: la web responde 500 con la fase `el parseo`.
7. Si el script parsea, cada expresión que no es `None` produce un bloque. Los `None` de un punto y coma vacío no producen bloque. Si, descartados esos `None`, no queda ninguna sentencia y el texto tampoco está vacío ni es solo comentarios, el error es «La consulta no contiene ninguna sentencia.» Los índices empiezan en 1. El `tipo` sale del nodo ya parseado y se rellena aunque fallen las fases siguientes.
8. Por cada sentencia, en este orden: formatear, análisis semántico, explicación, advertencias. Si una fase falla, sus resultados se descartan y las fases siguientes de esa sentencia no se ejecutan. Las demás sentencias siguen.
   - Fallo al formatear: `sql_formateado` es null, `arbol` es null, `resumen` es null, `pasos` es `[]` y `advertencias` es `[]`.
   - Fallo al recorrer: se conserva `sql_formateado`; `arbol` y `resumen` son null; `pasos` y `advertencias` son `[]`.
   - Fallo al explicar: se conservan formato, árbol y pasos; `resumen` y cada `explicacion` quedan null; `advertencias` es `[]`.
   - Fallo al advertir: se conserva todo lo anterior y `advertencias` es `[]`.

La biblioteca no ejecuta el SQL, no abre conexiones y no llama a un modelo. El backend analiza el texto, construye el informe y devuelve JSON. La página presenta ese JSON escapando el contenido.

## Informe

El informe es serializable a JSON. Las claves están en español. Las listas vacías se serializan como `[]`. Un campo de texto ausente porque su fase no llegó a ejecutarse va como `null`.

```json
{
  "dialecto": "postgresql",
  "sql_original": "SELECT 1",
  "sentencias": [],
  "errores": []
}
```

`Sentencia`:

| Campo | Tipo | Contenido |
| --- | --- | --- |
| `indice` | número | Posición en el script, desde 1 |
| `tipo` | texto | Tipo devuelto por SQLGlot, por ejemplo `Select` o `Update` |
| `sql_formateado` | texto o null | SQL generado desde el árbol en el dialecto elegido |
| `resumen` | texto o null | Una frase en español |
| `pasos` | lista de textos | Resumen lógico de la sentencia |
| `arbol` | componente o null | Raíz del árbol de componentes |
| `advertencias` | lista | Advertencias de la sentencia |

`Componente`:

| Campo | Tipo | Contenido |
| --- | --- | --- |
| `id` | texto | Identificador estable dentro del informe. Recorrido en preorden: la raíz es `s{indice}.c1` y `n` crece al visitar cada hijo de izquierda a derecha |
| `clase` | texto | `consulta`, `cte`, `subconsulta` o `union` |
| `nombre` | texto o null | Nombre de la CTE, si la clase es `cte` |
| `tipo` | texto | Tipo del nodo principal |
| `tablas` | lista | Apariciones de tablas |
| `columnas` | lista | Apariciones de columnas o expresiones |
| `clausulas` | lista | Cláusulas de este componente |
| `relaciones` | lista | `JOIN` escritos en este componente |
| `pasos` | lista de textos | Pasos lógicos de este componente |
| `hijos` | lista | Componentes anidados |
| `explicacion` | texto o null | Frase del componente. Null si la explicación de esa sentencia no llegó a completarse |

`Tabla`: `nombre`, `alias` o null, `papel`, `explicacion`.

`Columna`: `expresion`, `nombre` o null, `calificador` o null, `tabla` o null, `certeza`, `alias` o null, `papel`, `explicacion`. Hay una entrada por aparición, no una por nombre distinto. `expresion` es el SQL normalizado de esa aparición.

`certeza` vale `resuelta`, `sin_calificar`, `ambigua` o `no_resuelta`. `tabla` solo se rellena cuando `certeza` es `resuelta`. El nivel 1 no inventa la tabla de una columna a partir del número de orígenes.

- `resuelta`: el calificador coincide con un único origen del mismo componente. En `empleados.salario`, `calificador` es `empleados` y `tabla` es el nombre de ese origen. `e.salario` se resuelve igual si `e` es alias de un solo origen.
- `sin_calificar`: la columna no lleva calificador. `salario` queda con `tabla` null aunque el `FROM` tenga una sola tabla.
- `ambigua`: hay más de una interpretación posible. El calificador coincide con más de un origen y `tabla` queda null.
- `no_resuelta`: lleva un calificador que no coincide con ningún origen. En `SELECT x.salario FROM empleados e`, `x.salario` tiene `calificador` `x`, `tabla` null y `certeza` `no_resuelta`. No es `sin_calificar` y no es la misma referencia que `salario`.

`Clausula`: `nombre`, `texto`, `explicacion`. El nombre es el de la cláusula en el dialecto elegido (`LIMIT`, `TOP` o `FETCH`, según corresponda). `texto` es el SQL normalizado de esa cláusula.

`Relacion`: `tipo` (`inner`, `left`, `right`, `full`, `cross` u `otro`), `izquierda`, `derecha`, `condicion` o null, `explicacion`.

`Advertencia`: `codigo`, `gravedad` (siempre `aviso` en este nivel), `mensaje`, `componente_id`, `fragmento`. `fragmento` es el SQL normalizado de la expresión afectada, generado con SQLGlot en el dialecto elegido y sin formato ancho. No es un recorte del texto original ni incluye códigos de color del mensaje de error. Conservar los intervalos del texto escrito queda fuera de este nivel.

`Error`: `mensaje`, `linea` o null, `columna` o null, `sentencia` o null. `sentencia` apunta al índice de la sentencia cuando el fallo es de una fase posterior al parseo. En un error de todo el script queda null.

Papeles de una tabla: `lectura`, `destino`, `definicion`.

Papeles de una columna: `proyeccion`, `filtro`, `agrupacion`, `orden`, `asignacion`, `condicion_union`, `calculo`, `definicion`, `otro`.

### Árbol y propiedad

Cada tabla, columna, cláusula y relación tiene un solo dueño: el componente del bloque de consulta donde aparece el nodo. Las listas de un componente no copian las de sus descendientes. Este nivel no construye una lista agregada de tablas de toda la sentencia.

Una subconsulta es un hijo. Sus tablas viven solo en ese hijo. El componente exterior puede tener una columna o una cláusula cuyo SQL normalizado incluye el texto de la subconsulta, porque esa expresión ocupa un hueco exterior, pero no repite las tablas ni las columnas interiores.

Reglas de forma:

- Sin `WITH` y sin operación de conjunto, la raíz tiene clase `consulta`. Sus hijos son las subconsultas y las uniones que ocupan un hueco de subconsulta.
- Con `WITH` y un cuerpo que es una sola consulta, la raíz tiene clase `consulta`. Sus hijos empiezan por un componente `cte` por cada CTE, en orden de escritura, y siguen con las subconsultas del cuerpo. Las tablas y cláusulas del cuerpo viven en la raíz. La explicación de la raíz nombra las CTE y dice que el cuerpo las usa después.
- Con `WITH` y un cuerpo que es `UNION` o `UNION ALL`, la raíz tiene clase `consulta` y sus listas propias van vacías. Sus hijos son las CTE y, al final, un componente `union`. Las tablas viven en las ramas de esa unión.
- Una CTE cuyo cuerpo contiene otro `WITH` aplica la misma regla por dentro. El componente `cte` exterior es dueño de las tablas de su propia consulta, y las CTE interiores son hijos de clase `cte` con sus tablas propias. En `WITH a AS (WITH b AS (SELECT 1 AS n) SELECT n FROM b) SELECT n FROM a`, la raíz es dueña de `a`, `a` es dueña de `b` y `b` no tiene tabla de origen.
- Una subconsulta que no es una unión tiene clase `subconsulta`.
- Una subconsulta cuyo cuerpo es una unión es un hijo de clase `union`, sin un envoltorio adicional. En `SELECT * FROM (SELECT id FROM t UNION ALL SELECT id FROM u) s`, la raíz es dueña del alias `s` como origen de lectura y no es dueña de `t` ni de `u`. Esas tablas pertenecen a las ramas.
- Un `UNION` o `UNION ALL` tiene clase `union` y no es dueño de las tablas de sus ramas. Sus hijos son las ramas, en orden de escritura. Una rama es `consulta`, u otra `union` si el cuerpo vuelve a ser una operación de conjunto.
- `INSERT ... SELECT` deja la tabla de destino en el componente del `INSERT`. El `SELECT` origen es un hijo, y las tablas leídas viven en ese hijo.
- El mismo criterio se aplica dentro de una CTE o de una subconsulta.

### Pasos

`Componente.pasos` detalla ese componente. `Sentencia.pasos` resume la sentencia: si no hay CTE, es la misma lista que la de la raíz, o la de la unión raíz si la raíz es `union`. Si hay CTE, empieza con un paso «Prepara la CTE {nombre}.» por cada CTE, en orden de escritura, y sigue con los pasos del cuerpo. Cuando el cuerpo es una unión hija, esos pasos son los de la unión, no una lista vacía de la raíz. El orden lógico de una consulta es: orígenes y cada unión, filtro de filas, agrupación, filtro de grupos, columnas y cálculos, `DISTINCT`, orden y límite. Las tablas separadas por comas en un `FROM` cuentan como orígenes en producto cruzado, en el orden escrito, y generan relaciones `cross` sin condición. Ese orden describe la sentencia. La página lo separa del plan físico con la frase fija: «Estos pasos describen el orden lógico de la sentencia. El motor puede ejecutarla en otro orden.»

Recetas de los pasos de sentencia:

- `SELECT`: un paso por cada origen o unión, y un paso por cada cláusula presente de la lista anterior.
- `INSERT`: destino, columnas afectadas, origen (`VALUES` o consulta) y, si existe, la cláusula de conflicto que el dialecto haya parseado.
- `UPDATE`: destino, orígenes adicionales, asignaciones y filtro.
- `DELETE`: destino, orígenes adicionales y filtro.
- Cualquier otra: «Ejecuta una sentencia {tipo}.» seguido de un paso por cada cláusula reconocida. Una cláusula sin plantilla usa el texto de nodo desconocido.

### Explicaciones

Las plantillas reciben los datos del componente.

- `SELECT`: «Selecciona {expresiones}.»
- `FROM`: «Toma las filas de {tablas}.»
- `JOIN`: «Une {izquierda} con {derecha} con un {forma}, por {condición}.» `{forma}` es el texto `INNER JOIN`, `LEFT JOIN`, `RIGHT JOIN` o `FULL JOIN`. Si no hay condición: «Une {izquierda} con {derecha} con un producto cruzado.»
- `WHERE`: «Filtra las filas según {condición}.»
- `GROUP BY`: «Agrupa las filas por {expresiones}.»
- `HAVING`: «Filtra los grupos según {condición}.»
- `ORDER BY`: «Ordena el resultado por {expresiones}.»
- Límite: «Limita el resultado a {descripción del límite}.»
- `SET`: «Asigna {asignaciones}.»
- `VALUES`: «Usa los valores {valores}.»
- `INSERT`: «Inserta filas en {tabla}.»
- `UPDATE`: «Modifica filas de {tabla}.»
- `DELETE`: «Elimina filas de {tabla}.»
- `WITH`, en la raíz: «Define las expresiones de tabla {nombres}. La consulta exterior las usa después.»
- Nodo sin plantilla: «Esta parte es un nodo {tipo} y su texto es {texto}.»

Resumen de la sentencia:

- Consulta con tablas propias: «Consulta sobre {tablas}. Devuelve {n} expresiones.»
- Consulta cuyo cuerpo no delega en una unión y no tiene tablas: «Consulta sin tabla de origen. Devuelve {n} expresiones.»
- Raíz con las listas vacías porque el cuerpo es una unión hija: el resumen es el de esa unión, no el de una consulta sin orígenes. Con tablas en las ramas: «Combina con {UNION|UNION ALL} filas de {tablas de las ramas}.» Sin tablas en ninguna rama: «Combina con {UNION|UNION ALL} consultas sin tabla de origen.» En `WITH activos AS (SELECT id FROM empleados) SELECT id FROM activos UNION ALL SELECT id FROM antiguos` el resumen es «Combina con UNION ALL filas de activos y antiguos.»
- `INSERT`: «Inserta filas en {tabla}.»
- `UPDATE`: «Modifica filas de {tabla}.»
- `DELETE`: «Elimina filas de {tabla}.»
- Definición con nombre: «Define {nombre}.»
- Definición sin nombre: «Define un objeto {tipo}.»
- Resto: «Ejecuta una sentencia {tipo}.»

Estas frases son estructurales. No dicen si el resultado se duplica, si un `NULL` cambia el sentido más allá de la advertencia correspondiente, ni si la consulta será lenta.

## Advertencias

Las cuatro usan `gravedad` = `aviso`. Citan el `fragmento` normalizado y el `componente_id`. Una subconsulta anidada aparece en el árbol y no genera aviso por el hecho de existir. Si una regla no puede demostrar el riesgo, no emite aviso.

### `outer_join_filtrado`

Se aplica a `LEFT`, `RIGHT` y `FULL JOIN` del mismo componente. En un `LEFT JOIN` el lado anulable es el derecho. En un `RIGHT JOIN`, el izquierdo. En un `FULL JOIN` se evalúa cada lado por separado y cada uno puede producir su propio aviso.

El predicado que se evalúa es el `WHERE`, el `HAVING` o el `ON` de un `INNER JOIN` posterior, dentro del mismo componente. El `ON` del propio outer join no se evalúa. El `ON` de un `LEFT`, `RIGHT` o `FULL JOIN` posterior tampoco: no está demostrado que elimine las filas ya conservadas.

Antes de evaluar el predicado tiene que mencionar al menos una columna del lado anulable. Si no la menciona, no hay aviso, aunque el predicado sea falso por otro motivo. `WHERE 1 = 0` descarta todas las filas y no habla de la nulabilidad del `LEFT JOIN`, así que no emite `outer_join_filtrado`.

Si esa mención existe, el predicado se evalúa como si todas las columnas de ese lado fueran `NULL`. El resultado abstracto es uno de `TRUE`, `FALSE`, `UNKNOWN` o `INDETERMINADO`. Se avisa solo si el resultado es `FALSE` o `UNKNOWN`, porque entonces la fila extendida con `NULL` no puede superar el filtro. `TRUE` e `INDETERMINADO` no generan aviso.

La evaluación entiende literales, referencias a columnas, comparaciones (`=`, `!=`, `<>`, `<`, `>`, `<=`, `>=`), `IS NULL`, `IS NOT NULL`, `AND`, `OR` y `NOT`. Una columna del lado anulable vale `NULL`. Una columna de otro lado vale `INDETERMINADO`. Una comparación con un operando `NULL` vale `UNKNOWN`. Una comparación con un operando `INDETERMINADO` vale `INDETERMINADO`. `NOT` invierte `TRUE` y `FALSE`, y deja igual `UNKNOWN` e `INDETERMINADO`.

`AND` queda demostrado como no verdadero si alguno de sus operandos es `FALSE` o `UNKNOWN`. Así, `p.estado = 'activo' AND c.prioridad = 'alta'` avisa: el primer lado es `UNKNOWN` y la conjunción no puede ser `TRUE`. Si los dos operandos son `INDETERMINADO`, o uno es `INDETERMINADO` y el otro es `TRUE`, el resultado es `INDETERMINADO` y no avisa.

`OR` solo queda demostrado como no verdadero si todos sus operandos lo están. Si alguno es `TRUE`, el resultado es `TRUE`. Si alguno es `INDETERMINADO` y ninguno es `TRUE`, el resultado es `INDETERMINADO`. Así, `p.estado = 'activo' OR c.prioridad = 'alta'` no avisa, porque la segunda parte puede conservar la fila. `p.estado = 'activo' OR p.tipo = 'vip'`, con ambas columnas del lado anulable, queda `UNKNOWN` y sí avisa. `p.id IS NULL` queda `TRUE` y no avisa.

Cualquier otra construcción dentro del predicado (`IN`, `LIKE`, `BETWEEN`, `CASE`, una función o una subconsulta) hace que ese subárbol valga `INDETERMINADO`.

Hay un aviso por cada par de outer join y predicado que menciona ese lado y cuyo resultado es `FALSE` o `UNKNOWN`. El fragmento es el predicado completo.

Mensaje: «El {forma} con {tabla} deja sus columnas a NULL cuando no hay coincidencia. El filtro posterior `{fragmento}` descarta esos NULL, así que las filas sin coincidencia pueden desaparecer.» `{forma}` es `LEFT JOIN`, `RIGHT JOIN` o `FULL JOIN`. `{tabla}` es la tabla de ese lado nombrada en el predicado.

### `comparacion_con_null`

Hay un `=`, `!=` o `<>` con un literal `NULL` en cualquiera de los dos lados. No entran `IS NULL`, `IS NOT NULL`, `IS DISTINCT FROM` ni el `<=>` de MySQL.

Mensaje: «La comparación `{fragmento}` usa {operador} con NULL. Con este operador el resultado es desconocido, así que el filtro no selecciona esas filas. Para comprobar NULL usa IS NULL o IS NOT NULL.»

### `select_asterisco`

El aviso corresponde a un nodo asterisco que es, por sí mismo, un elemento de la lista de selección, o el hijo inmediato de su alias. Se emite uno por cada asterisco de ese tipo. Un asterisco dentro de una función no es una proyección: `COUNT(*)` y `COUNT(e.*)` no disparan el aviso. SQLGlot 30.25.0 acepta `COUNT(e.*)` en los cuatro dialectos; el detector no lo trata como `SELECT *` aunque algún motor lo rechace al ejecutarlo.

Mensaje: «`{fragmento}` recupera todas las columnas de {tablas}.» Si el asterisco no nombra tabla: «`*` recupera todas las columnas de las tablas de esta consulta.»

### `select_fuera_de_group_by`

Solo si el componente tiene `GROUP BY`. La unidad que se comprueba es cada referencia a columna del `SELECT` que no está dentro de los argumentos de una función de agregación. Una función de ventana no cuenta como agregación, y las columnas de su `PARTITION BY` u `ORDER BY` tampoco quedan agrupadas por estar ahí.

Una referencia está cubierta, y por tanto no avisa, si se cumple alguna de estas condiciones:

- Es la misma referencia que un elemento del `GROUP BY`. Dos referencias son la misma si ambas están `resuelta` a la misma `tabla` y al mismo `nombre`, o si ambas están `sin_calificar` y comparten el `nombre`. `no_resuelta` no es la misma referencia que `sin_calificar`, aunque el nombre de la columna coincida, y tampoco queda descubierta: no está demostrado a qué origen pertenece. `SELECT salario + 100 ... GROUP BY salario` no avisa: `salario` está agrupado aunque la expresión completa no sea una clave. `e.salario` y `salario` no se dan por la misma: podría serlo, así que no queda descubierta y no avisa. `x.salario` frente a `GROUP BY salario` tampoco avisa, porque `x.salario` es `no_resuelta`.
- La expresión completa del `SELECT` que la contiene equivale, por la forma del nodo, a un elemento del `GROUP BY`.
- El `GROUP BY` es un nombre sin calificar, el `SELECT` tiene un único alias con ese nombre y la consulta no tiene `FROM`. Ahí el nombre solo puede ser el alias. Si hay `FROM`, el nombre podría ser una columna del origen: no está demostrado y esa expresión no avisa. En la 30.25.0, `qualify` sin esquema no resuelve `GROUP BY total` y lanza `OptimizeError`; el analizador no usa esa llamada para decidir la regla ni convierte ese error en un fallo de fase.

Una referencia queda descubierta solo cuando se demuestra que ninguna de esas condiciones la cubre. Si la comparación queda en duda, no está descubierta. Se emite un aviso por cada expresión del `SELECT` que contenga al menos una referencia descubierta. El fragmento es esa expresión normalizada.

No se emite aviso en estos casos, porque el resultado no está demostrado:

- El dialecto es SQLite. Ese dialecto acepta la columna y elige un valor del grupo.
- La referencia es `ambigua` o `no_resuelta`, o el alias del `GROUP BY` no se puede resolver.

Sí se emite en PostgreSQL, SQL Server y MySQL. MySQL se evalúa como si `ONLY_FULL_GROUP_BY` estuviera activo, que es su modo predeterminado. El falso positivo aceptado es una sesión de MySQL con ese modo desactivado, y también una dependencia funcional que exigiría conocer la clave primaria: `SELECT d.id, d.nombre GROUP BY d.id` avisa por `d.nombre` aunque `id` pudiera determinarla.

Mensaje: «`{fragmento}` está en el SELECT, no está en el GROUP BY y no está dentro de una función de agregación. Según el dialecto, el motor puede rechazar la consulta o devolver un valor cualquiera del grupo.»

## Mensajes de error

Los textos salen de `mensajes.py`. La página muestra ese texto, con la línea y la columna cuando existen.

### Petición, HTTP 400

Cuerpo: `{"mensaje": "..."}`.

- Falta `dialecto`: «Falta el dialecto. Elige PostgreSQL, MySQL, SQLite o SQL Server.»
- Valor no admitido, por ejemplo `excel`: «El dialecto «excel» no está soportado. Elige PostgreSQL, MySQL, SQLite o SQL Server.»
- Falta `sql`: «Falta la consulta.»
- `sql` no es un texto: «La consulta tiene que ser un texto.»
- El cuerpo no es JSON: «El cuerpo de la petición tiene que ser un JSON con sql y dialecto.»
- `sql` supera 1048576 bytes en UTF-8: «La consulta ocupa {n} bytes y el límite es 1 MB (1048576 bytes).»

### Consulta vacía, HTTP 200

`sentencias` queda vacío y `errores` lleva un elemento sin línea ni sentencia.

- Texto vacío o solo espacios: «La consulta está vacía.»
- Solo comentarios, tras quitarlos y quitar espacios: «La consulta solo contiene espacios o comentarios.»
- Texto con signos y ningún nodo de sentencia, como `;;;`: «La consulta no contiene ninguna sentencia.»

### Sintaxis, HTTP 200

El script completo queda sin sentencias. Solo `ParseError` y `TokenError` llegan a esta traducción. La `description` que se cita es el campo `description` de `ParseError.errors`, nunca `str(ParseError)`, porque la cadena de la excepción incluye códigos de resaltado.

En un `ParseError` se usa `line` y `col` de cada elemento de `errors`, en el orden de la lista. En un `TokenError` la 30.25.0 no trae línea ni columna fiables (`start` puede ser 0). La posición es la del delimitador o comentario que sigue abierto, contada desde el texto original en base 1. Reglas de traducción, en este orden:

1. Hay un `/*` sin `*/`: «El comentario abierto en la línea {linea}, columna {columna} no se cierra.»
2. Hay un delimitador de identificador o de cadena sin cerrar (`'`, `"`, `` ` `` o `[`): «La comilla abierta en la línea {linea}, columna {columna} no se cierra.» o «El identificador abierto con `{delimitador}` en la línea {linea}, columna {columna} no se cierra.»
3. El token esperado es `)` y en el texto hay más `(` que `)`: «El paréntesis abierto en la línea {linea}, columna {columna} no se cierra.»
4. El error está al final de la sentencia y SQLGlot esperaba un token: «La sentencia termina en la línea {linea}, columna {columna}, y ahí se esperaba `{token}`.»
5. SQLGlot esperaba un token y encontró otro: «En la línea {linea}, columna {columna}, se esperaba `{esperado}` y apareció `{encontrado}`.»
6. Cualquier otro `ParseError`: «SQLGlot no interpreta la sentencia en la línea {linea}, columna {columna}: {description}.» Si no hay línea o columna, se omiten esas partes y se conserva la description.

Las comillas de dólar de PostgreSQL que no encajen en las reglas anteriores usan la regla 6.

### Fallo de una sentencia ya parseada, HTTP 200

`api.py` atrapa, en cada fase, `ErrorDeFase` y cualquier otra `Exception`. Las dos se registran con el mensaje de esa fase. Ninguna se convierte en error de sintaxis. La sentencia ocupa su sitio en `sentencias`. `errores` incluye un elemento con su `sentencia`. Los campos que quedan vacíos son los de la fase fallida y los de las fases que ya no se ejecutan, tal como dice el flujo. El mensaje incluye el tipo de la excepción y el detalle:

- «No se ha podido recorrer la sentencia {n} ({tipo}). El detalle técnico quedó en el registro del servidor.»
- «No se ha podido explicar la sentencia {n} ({tipo}). El detalle técnico quedó en el registro del servidor.»
- «No se han podido evaluar las advertencias de la sentencia {n} ({tipo}). El detalle técnico quedó en el registro del servidor.»
- «No se ha podido formatear la sentencia {n} ({tipo}). El detalle técnico quedó en el registro del servidor.»

El informe y la página no incluyen el tipo de la excepción, su mensaje ni fragmentos del trazado. El registro del servidor guarda el tipo, el mensaje completo y la traza, sin recortarlos.

### Fallo antes de tener informe, HTTP 500

Cuerpo: `{"mensaje": "No se ha podido construir el informe durante {fase}. El detalle técnico quedó en el registro del servidor."}`. `fase` es `la validación`, `el parseo` o `la respuesta`. La página muestra ese mensaje. El registro guarda el tipo, el mensaje completo y la traza.

## Interfaz

`GET /` devuelve la página. `POST /analizar` recibe `{"sql": "...", "dialecto": "postgresql"}` y responde el informe en JSON, o el cuerpo de error de las secciones anteriores.

La página tiene el formulario arriba: dialecto, área de texto y el botón Analizar. Antes de la primera respuesta solo se ve el formulario y la línea «Elige un dialecto y pega la sentencia.»

Con errores de script, esos errores van primero y no se dibuja el árbol de esa petición.

Con sentencias, cada una muestra, en orden:

1. Tipo y resumen.
2. Pasos conceptuales, con la frase fija sobre el orden lógico.
3. Advertencias y el fragmento citado.
4. Árbol de componentes, plegable. Al abrir un nodo se ven sus tablas, columnas, cláusulas, `JOIN`, pasos y explicación.
5. SQL formateado y un botón Copiar.

La consulta original permanece visible encima de los resultados. No hay historial, ni cuadro de preguntas, ni propuestas de reescritura.

El informe se pide con `fetch`. Un 400 o un 500 muestran el campo `mensaje` en la misma zona de errores. La página está en español.

La plantilla Jinja2 tiene el autoescape activado. El script que pinta el informe inserta la consulta, los fragmentos, los mensajes y el resto de textos con `textContent`, no con `innerHTML`.

## Pruebas

`pytest`, sin base de datos, sin red y sin modelo de lenguaje. Se afirma la estructura y los códigos de advertencia. Del español se afirma la frase decisiva de cada plantilla, no un volcado completo de la redacción. Del SQL formateado se afirma el contenido, no los espacios.

`test_analizar.py`:

- La misma consulta en los cuatro dialectos: `SELECT` con `INNER JOIN`, `WHERE` y `GROUP BY`, válida en todos.
- Un rasgo de cada dialecto para comprobar que el dialecto llega al parser: PostgreSQL con `ILIKE`; MySQL con identificadores entre backticks; SQLite con la consulta común y un identificador entre comillas dobles; SQL Server con `TOP` y corchetes.
- Un `INSERT`, un `UPDATE`, un `DELETE` y un `CREATE TABLE`.
- Sentencias que SQLGlot 30.25.0 acepta y que no deben explicarse como una consulta ni fallar a mitad de fase. El resumen de un `CREATE` puede ser «Define {nombre}.». El de `ALTER`, `DROP` y `MERGE` es «Ejecuta una sentencia {tipo}.» y no empieza por «Consulta». Una cláusula sin plantilla usa la frase de nodo desconocido. Los casos son: `CREATE`, `ALTER` y `DROP` en los cuatro dialectos; `WITH RECURSIVE` en PostgreSQL, MySQL y SQLite; `ON CONFLICT` en PostgreSQL; `ON DUPLICATE KEY UPDATE` en MySQL; `MERGE` en SQL Server. En el `WITH RECURSIVE` hay una sola CTE con ese nombre, y la lectura recursiva es una tabla de su cuerpo, no otra CTE.
- Un script de dos sentencias.
- Una CTE que contiene una subconsulta, comprobando clases, orden de los hijos y que las tablas interiores no se copian al exterior.
- Una CTE con otra CTE en su cuerpo: `WITH a AS (WITH b AS (SELECT 1 AS n) SELECT n FROM b) SELECT n FROM a`. La raíz es dueña de `a`, `a` es dueña de `b` y `b` no tiene tabla.
- Una unión dentro de una subconsulta: la raíz es dueña del alias exterior y las tablas de cada rama viven en esa rama.
- Un `WITH` cuyo cuerpo es un `UNION`: la raíz tiene las listas vacías y un hijo `union`. Con `WITH activos AS (SELECT id FROM empleados) SELECT id FROM activos UNION ALL SELECT id FROM antiguos`, el resumen es «Combina con UNION ALL filas de activos y antiguos.» y no contiene «sin tabla de origen».
- `SELECT 1; SELECT 2` produce dos sentencias. `SELECT 1;; SELECT 2` produce dos, no tres.
- Punto y coma vacío, que no crea sentencia.

`test_advertencias.py` cubre los casos límite, no solo un positivo y un negativo:

| Caso | Resultado |
| --- | --- |
| `LEFT JOIN` con `WHERE` sobre `derecha.estado = 'A'` | `outer_join_filtrado` |
| El mismo filtro dentro del `ON` de ese `LEFT JOIN` | Sin ese aviso |
| `WHERE derecha.id IS NULL` | Sin ese aviso |
| `WHERE p.estado = 'activo' OR c.prioridad = 'alta'` | Sin ese aviso |
| `LEFT JOIN` con `WHERE 1 = 0`, sin columnas del lado derecho | Sin `outer_join_filtrado` |
| `FULL JOIN` con un filtro demostrable en cada lado | Un aviso por lado |
| `SELECT * FROM empleados` | `select_asterisco` |
| `SELECT e.* FROM empleados e` | `select_asterisco` |
| `SELECT COUNT(*) FROM empleados` | Sin ese aviso |
| `SELECT COUNT(e.*) FROM empleados e` | Sin ese aviso en los cuatro dialectos |
| `= NULL` | `comparacion_con_null` |
| `IS NULL` | Sin ese aviso |
| `SELECT departamento, salario + 100 GROUP BY departamento, salario` | Sin aviso de agrupación |
| `SELECT salario GROUP BY salario + 100` | `select_fuera_de_group_by` en PostgreSQL |
| La misma expresión dentro de `SUM` | Sin ese aviso |
| Una columna solo usada en `PARTITION BY` de una ventana | Aviso en PostgreSQL |
| `SELECT salario + 100 AS total FROM empleados GROUP BY total` | Sin aviso: el alias no queda demostrado |
| `SELECT salario + 100 AS total GROUP BY total`, sin `FROM` | Sin aviso: el alias es la única lectura posible |
| `SELECT a.id, b.id FROM a, b GROUP BY a.id` | Aviso por `b.id` en PostgreSQL |
| La consulta de agrupación incompleta en SQLite | Sin ese aviso |

`test_errores.py` compara el texto exacto de: `DialectoNoSoportado` al llamar a `analizar`, consulta vacía, solo comentarios, `;;;`, paréntesis sin cerrar, comilla sin cerrar como `TokenError` y no como 500, un `ParseError` en la segunda sentencia que deja el script sin bloques, y un fallo de fase en la segunda sentencia de un script cuyas otras sentencias sí vuelven analizadas. El mensaje de ese fallo es «No se ha podido recorrer la sentencia 2 ({tipo}). El detalle técnico quedó en el registro del servidor.» y no contiene el texto de la excepción. Una prueba de columnas comprueba que `salario` sin calificador queda `sin_calificar` y con `tabla` null aunque haya una sola tabla. Otra comprueba que, en `SELECT x.salario FROM empleados e`, `x.salario` queda `no_resuelta`, con calificador `x` y `tabla` null, y no se clasifica como `sin_calificar`.

`test_frontera.py` importa `semantica`, `explicacion`, `advertencias`, `formato`, `api`, `modelo`, `dialectos`, `mensajes` y `errores`, y falla si alguno importa `sqlglot`.

`test_web.py` usa el cliente de FastAPI. `GET /` contiene el formulario y los cuatro dialectos. `POST /analizar` devuelve el informe. Los 400 cubren cuerpo que no es JSON, `sql` ausente, `sql` que no es un texto, dialecto ausente, dialecto desconocido y consulta de más de 1048576 bytes. El 500 se provoca sustituyendo el parseo por una función que lanza `RuntimeError("fallo de prueba")`. El cuerpo es «No se ha podido construir el informe durante el parseo. El detalle técnico quedó en el registro del servidor.» y no contiene `fallo de prueba`. El registro de la prueba sí lo contiene. Otra prueba lee `web/estaticos/app.js` y falla si el informe se inserta con `innerHTML`.

## Orden de construcción

Primero el núcleo, después la web. Cada módulo se prueba antes de añadir el siguiente.

1. `modelo.py`, `errores.py`, `dialectos.py` y `parser.py`, con `Nodo`, `bloque` y `expresion`, las pruebas de scripts, los huecos `None` y la distinción entre `ParseError` y `TokenError`.
2. `semantica.py` y el árbol de componentes, con las pruebas de propiedad.
3. `explicacion.py` y `formato.py`.
4. `advertencias.py`, con la batería de casos límite.
5. `api.py`, que coordina las fases y traduce los fallos internos.
6. `web/`, al final.

## Decisiones que este diseño deja cerradas

- El nivel 1 no lee un esquema. El detector no tiene todavía una entrada para claves.
- El detector no propone reescrituras. Ese texto pertenecerá al módulo de optimización.
- Una advertencia no se presenta como error de sintaxis ni como fallo seguro de la consulta.
- El árbol navegable de la página es el árbol de componentes, no el volcado de nodos de SQLGlot.
- `fragmento` es SQL normalizado. Los intervalos del texto original no forman parte del informe.
- Una regla que no demuestra el riesgo no avisa. Los falsos positivos aceptados de `select_fuera_de_group_by` son el modo `ONLY_FULL_GROUP_BY` desactivado en MySQL y la dependencia funcional de una clave que no está en el esquema.
- La versión de SQLGlot del nivel 1 es la 30.25.0, y solo `parser.py` la importa.
- Una columna sin calificador queda `sin_calificar` y no recibe una tabla supuesta. Un calificador que no coincide con ningún origen queda `no_resuelta`, no `sin_calificar`.
- El usuario ve la fase y la sentencia del fallo interno. El mensaje de la excepción y la traza se quedan en el registro.
- Aceptar lo que SQLGlot parsea no obliga a una plantilla por cada sentencia. Obliga a no explicarlas como otra cosa y a no fallar en los casos probados.
