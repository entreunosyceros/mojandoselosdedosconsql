# Analizador SQL nivel 1 — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir una aplicación web local que recibe SQL y un dialecto y devuelve un informe en español, producido por un núcleo determinista sobre SQLGlot 30.25.0.

**Architecture:** Solo `parser.py` importa SQLGlot y entrega un `Nodo`. `semantica.py`, `explicacion.py`, `formato.py` y `advertencias.py` consumen ese nodo o el `Informe`. `api.analizar(sql, dialecto)` es la única entrada pública. La web llama a esa función y pinta el JSON sin ejecutarlo.

**Tech Stack:** Python 3.11+, `sqlglot==30.25.0`, FastAPI, uvicorn, Jinja2, pytest, httpx.

**Spec:** `docs/superpowers/specs/2026-10-26-analizador-sql-design.md`

## Global Constraints

- Python 3.11 o superior.
- Dependencia fijada: `sqlglot==30.25.0`. FastAPI, uvicorn y Jinja2 en ejecución. pytest y httpx en desarrollo.
- Solo `parser.py` importa `sqlglot`. `dialectos.py`, `semantica.py`, `explicacion.py`, `advertencias.py`, `formato.py`, `api.py`, `modelo.py`, `mensajes.py`, `errores.py` y `web/` no lo importan.
- Entrada pública: `analizar(sql: str, dialecto: str) -> Informe`.
- Dialectos de la API: `postgresql`, `mysql`, `sqlite`, `sqlserver`. Internos: `postgres`, `mysql`, `sqlite`, `tsql`.
- `ParseError` y `TokenError` son sintaxis. Cualquier otra excepción de parseo no se presenta como SQL mal escrito.
- El usuario no ve el mensaje de una excepción interna. El registro guarda tipo, mensaje completo y traza.
- `certeza` es `resuelta`, `sin_calificar`, `ambigua` o `no_resuelta`. `tabla` solo si `certeza` es `resuelta`.
- `sin_calificar` solo cuando no hay calificador. Un calificador sin origen es `no_resuelta`.
- Una raíz vacía porque el cuerpo es una unión no se resume como consulta sin orígenes.
- `outer_join_filtrado` exige que el predicado mencione una columna del lado anulable. `WHERE 1 = 0` no avisa.
- `fragmento` es SQL normalizado, no un recorte del original.
- Límite de `sql`: 1048576 bytes UTF-8.
- La página inserta textos con `textContent`. Jinja2 tiene autoescape.
- El programa no ejecuta SQL ni abre conexiones.

## File structure

- `pyproject.toml` — paquete `analizador` en `src`, pytest con `pythonpath` `.` y `src`.
- `src/analizador/mensajes.py` — textos fijos.
- `src/analizador/errores.py` — `ErrorAnalizador`, `DialectoNoSoportado`, `ErrorDeFase`.
- `src/analizador/dialectos.py` — traducción de nombres.
- `src/analizador/modelo.py` — `Informe` y piezas, con `a_dict()`.
- `src/analizador/parser.py` — único import de SQLGlot: `parsear`, `normalizar`, `bloque`, `expresion`, `Nodo`.
- `src/analizador/semantica.py` — `componentes(nodo) -> Componente`.
- `src/analizador/explicacion.py` — `rellenar(componente) -> Componente` y `resumen(componente) -> str`.
- `src/analizador/formato.py` — `formatear(nodo, dialecto) -> str`.
- `src/analizador/advertencias.py` — `evaluar(componente) -> tuple[Advertencia, ...]`.
- `src/analizador/api.py` — `analizar`.
- `src/analizador/__init__.py` — exporta `analizar`.
- `web/__init__.py`, `web/app.py`, `web/plantillas/index.html`, `web/estaticos/estilo.css`, `web/estaticos/app.js`.
- `tests/test_modelo.py`, `tests/test_parser.py`, `tests/test_semantica.py`, `tests/test_explicacion.py`, `tests/test_advertencias.py`, `tests/test_errores.py`, `tests/test_frontera.py`, `tests/test_web.py`.

---

### Task 1: Mensajes, errores, dialectos y modelo

**Files:**
- Create: `pyproject.toml`
- Create: `src/analizador/__init__.py`
- Create: `src/analizador/mensajes.py`
- Create: `src/analizador/errores.py`
- Create: `src/analizador/dialectos.py`
- Create: `src/analizador/modelo.py`
- Test: `tests/test_modelo.py`

**Interfaces:**
- Consumes: nada.
- Produces: `nombre_interno(dialecto: str) -> str`, `DialectoNoSoportado`, `ErrorDeFase(fase, indice, tipo, causa)`, `Informe.a_dict() -> dict`, y las constantes de `mensajes.py` usadas por las tareas siguientes.

- [ ] **Step 1: Write the failing test**

```python
from analizador.dialectos import nombre_interno
from analizador.errores import DialectoNoSoportado
from analizador.mensajes import FALTA_DIALECTO
from analizador.modelo import Columna, Informe


def test_nombre_interno_de_sql_server():
    assert nombre_interno("sqlserver") == "tsql"


def test_dialecto_desconocido():
    try:
        nombre_interno("excel")
    except DialectoNoSoportado as error:
        assert str(error) == 'El dialecto «excel» no está soportado. Elige PostgreSQL, MySQL, SQLite o SQL Server.'
    else:
        raise AssertionError("debía fallar")


def test_informe_vacio_a_dict():
    informe = Informe(dialecto="postgresql", sql_original="", sentencias=(), errores=())
    assert informe.a_dict()["sentencias"] == []
    assert informe.a_dict()["errores"] == []


def test_columna_no_resuelta_no_lleva_tabla():
    columna = Columna(
        expresion="x.salario",
        nombre="salario",
        calificador="x",
        tabla=None,
        certeza="no_resuelta",
        alias=None,
        papel="proyeccion",
        explicacion=None,
    )
    assert columna.a_dict()["certeza"] == "no_resuelta"
    assert columna.a_dict()["tabla"] is None
    assert FALTA_DIALECTO.startswith("Falta el dialecto")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_modelo.py -v`

Expected: FAIL with `ModuleNotFoundError: analizador`

- [ ] **Step 3: Write minimal implementation**

`pyproject.toml`:

```toml
[project]
name = "mojandose-los-dedos-con-sql"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "sqlglot==30.25.0",
  "fastapi",
  "uvicorn",
  "jinja2",
]

[project.optional-dependencies]
dev = ["pytest", "httpx"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = [".", "src"]
testpaths = ["tests"]
```

`src/analizador/__init__.py` queda vacío en esta tarea.

`src/analizador/mensajes.py` empieza con estas constantes y sigue con las funciones:

```python
FALTA_DIALECTO = "Falta el dialecto. Elige PostgreSQL, MySQL, SQLite o SQL Server."
FALTA_CONSULTA = "Falta la consulta."
CONSULTA_NO_ES_TEXTO = "La consulta tiene que ser un texto."
CUERPO_NO_ES_JSON = "El cuerpo de la petición tiene que ser un JSON con sql y dialecto."
CONSULTA_VACIA = "La consulta está vacía."
SOLO_COMENTARIOS = "La consulta solo contiene espacios o comentarios."
SIN_SENTENCIA = "La consulta no contiene ninguna sentencia."
ORDEN_LOGICO = "Estos pasos describen el orden lógico de la sentencia. El motor puede ejecutarla en otro orden."
FALLO_ADVERTENCIAS = (
    "No se han podido evaluar las advertencias de la sentencia {indice} ({tipo}). "
    "El detalle técnico quedó en el registro del servidor."
)
```

```python
def dialecto_no_soportado(valor: str) -> str:
    return f"El dialecto «{valor}» no está soportado. Elige PostgreSQL, MySQL, SQLite o SQL Server."

def consulta_demasiado_grande(nbytes: int) -> str:
    return f"La consulta ocupa {nbytes} bytes y el límite es 1 MB (1048576 bytes)."

def fallo_fase(verbo: str, indice: int, tipo: str) -> str:
    return (
        f"No se ha podido {verbo} la sentencia {indice} ({tipo}). "
        "El detalle técnico quedó en el registro del servidor."
    )

def fallo_informe(fase: str) -> str:
    return (
        f"No se ha podido construir el informe durante {fase}. "
        "El detalle técnico quedó en el registro del servidor."
    )
```

`api.py` usará `fallo_fase("formatear", indice, tipo)`, `fallo_fase("recorrer", indice, tipo)`, `fallo_fase("explicar", indice, tipo)` y `FALLO_ADVERTENCIAS.format(indice=indice, tipo=tipo)`.

`src/analizador/errores.py`:

```python
class ErrorAnalizador(Exception):
    pass

class DialectoNoSoportado(ErrorAnalizador):
    pass

class ErrorDeFase(ErrorAnalizador):
    def __init__(self, fase: str, indice: int, tipo: str, causa: BaseException):
        self.fase = fase
        self.indice = indice
        self.tipo = tipo
        self.causa = causa
        super().__init__(str(causa))
```

`src/analizador/dialectos.py` mapea los cuatro nombres y lanza `DialectoNoSoportado(dialecto_no_soportado(valor))`. No importa sqlglot.

`src/analizador/modelo.py` define dataclasses congelados: `Error`, `Advertencia`, `Tabla`, `Columna`, `Clausula`, `Relacion`, `Componente`, `Sentencia`, `Informe`. Cada uno tiene `a_dict()`. `Componente.a_dict()` no incluye ningún atributo privado. Las tuplas se serializan como listas. `explicacion` y `sql_formateado` pueden ser `None`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pip install -e ".[dev]" && pytest tests/test_modelo.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/analizador tests/test_modelo.py
git commit -m "feat: define the report model and dialect names"
```

---

### Task 2: Parseo y errores de sintaxis

**Files:**
- Create: `src/analizador/parser.py`
- Test: `tests/test_parser.py`

**Interfaces:**
- Consumes: `nombre_interno`, `mensajes`.
- Produces: `parsear(sql: str, dialecto: str) -> ResultadoParseo`. `ResultadoParseo.sentencias` es una tupla de `SentenciaSintactica(indice, tipo, nodo)`. `ResultadoParseo.errores` es una tupla de `Error`. Si hay errores de sintaxis, `sentencias` está vacía.

- [ ] **Step 1: Write the failing test**

```python
from analizador.parser import parsear


def test_dos_sentencias():
    resultado = parsear("SELECT 1; SELECT 2", "postgresql")
    assert [s.tipo for s in resultado.sentencias] == ["Select", "Select"]
    assert [s.indice for s in resultado.sentencias] == [1, 2]
    assert resultado.errores == ()


def test_punto_y_coma_vacio_no_crea_sentencia():
    resultado = parsear("SELECT 1;; SELECT 2", "postgresql")
    assert len(resultado.sentencias) == 2


def test_error_en_la_segunda_anula_el_script():
    resultado = parsear("SELECT 1; SELEC 2", "postgresql")
    assert resultado.sentencias == ()
    assert resultado.errores


def test_comilla_es_error_de_sintaxis():
    resultado = parsear("SELECT 'ab", "postgresql")
    assert resultado.sentencias == ()
    assert "comilla abierta" in resultado.errores[0].mensaje


def test_parentesis_sin_cerrar():
    resultado = parsear("SELECT (1", "postgresql")
    assert "paréntesis abierto" in resultado.errores[0].mensaje


def test_solo_comentarios():
    resultado = parsear("-- hola\n", "postgresql")
    assert resultado.sentencias == ()
    assert resultado.errores[0].mensaje == "La consulta solo contiene espacios o comentarios."


def test_triple_punto_y_coma():
    resultado = parsear(";;;", "postgresql")
    assert resultado.errores[0].mensaje == "La consulta no contiene ninguna sentencia."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_parser.py -v`

Expected: FAIL with `ImportError` de `parsear`

- [ ] **Step 3: Write minimal implementation**

`parser.py` importa `sqlglot` y `sqlglot.errors.ParseError` y `TokenError`. Traduce el dialecto con `nombre_interno` antes de llamar a `sqlglot.parse`.

- Un `None` entre expresiones se descarta y no consume índice.
- `ParseError`: recorre `error.errors` y usa el campo `description`, nunca `str(error)`. Aplica las seis reglas del spec, en ese orden. La posición sale de `line` y `col`.
- `TokenError`: no es subclase de `ParseError`. Localiza en el texto original el `/*`, la comilla o el delimitador `[`, `` ` `` o `"` que queda abierto, con línea y columna en base 1. No uses `TokenError.start` como columna: en la 30.25.0 puede ser 0.
- Si el resultado solo contiene `None` y el tokenizador solo vio comentarios o espacios, el error es `SOLO_COMENTARIOS`.
- Si no queda ninguna sentencia y el texto no está vacío ni es solo comentarios, el error es `SIN_SENTENCIA`.
- La consulta vacía no se decide aquí: la decide `api.py`.

`Nodo` guarda la expresión en `_expression`. `SentenciaSintactica.tipo` es `type(expression).__name__`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_parser.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/analizador/parser.py tests/test_parser.py
git commit -m "feat: parse scripts and translate syntax errors"
```

---

### Task 3: Nodo, SQL normalizado, bloque y expresión

**Files:**
- Modify: `src/analizador/parser.py`
- Test: `tests/test_parser.py`

**Interfaces:**
- Consumes: `Nodo` de la tarea 2.
- Produces:
  - `normalizar(nodo: Nodo, dialecto: str) -> str`
  - `bloque(nodo: Nodo) -> Bloque`
  - `expresion(nodo: Nodo) -> Expresion`
  - `Bloque` con `ctes`, `ramas`, `union_all`, `subconsultas`, `tablas`, `relaciones`, `clausulas`, `proyecciones`. Cada hijo sigue siendo un `Nodo`.
  - `Expresion.forma` en `columna`, `literal`, `nulo`, `comparacion`, `es_nulo`, `no_es_nulo`, `y`, `o`, `no`, `agregacion`, `ventana`, `asterisco`, `alias`, `otra`.
  - `Expresion` de una columna trae `nombre` y `calificador` escritos, sin tabla deducida.

- [ ] **Step 1: Write the failing test**

```python
from analizador.parser import bloque, expresion, normalizar, parsear


def test_normalizar_no_es_el_texto_original():
    nodo = parsear("select  1", "postgresql").sentencias[0].nodo
    assert normalizar(nodo, "postgresql") == "SELECT 1"


def test_bloque_de_select_no_despliega_la_subconsulta():
    sql = "SELECT id FROM t WHERE id IN (SELECT id FROM u)"
    nodo = parsear(sql, "postgresql").sentencias[0].nodo
    nivel = bloque(nodo)
    assert nivel.subconsultas
    assert [tabla.nombre for tabla in nivel.tablas] == ["t"]


def test_expresion_de_columna_no_inventa_tabla():
    sql = "SELECT salario FROM empleados"
    nodo = parsear(sql, "postgresql").sentencias[0].nodo
    proyeccion = expresion(bloque(nodo).proyecciones[0])
    assert proyeccion.forma == "columna"
    assert proyeccion.nombre == "salario"
    assert proyeccion.calificador is None


def test_asterisco_dentro_de_count_no_es_proyeccion():
    sql = "SELECT COUNT(e.*) FROM empleados AS e"
    nodo = parsear(sql, "postgresql").sentencias[0].nodo
    forma = expresion(bloque(nodo).proyecciones[0])
    assert forma.forma == "agregacion"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_parser.py::test_normalizar_no_es_el_texto_original tests/test_parser.py::test_bloque_de_select_no_despliega_la_subconsulta tests/test_parser.py::test_expresion_de_columna_no_inventa_tabla tests/test_parser.py::test_asterisco_dentro_de_count_no_es_proyeccion -v`

Expected: FAIL porque `normalizar` aún no existe

- [ ] **Step 3: Write minimal implementation**

`normalizar` llama a `nodo._expression.sql(dialect=nombre_interno(dialecto))`.

`bloque` lee solo el nivel directo:

- `with_` produce `ctes` con el alias y el `Nodo` del cuerpo. No copia las tablas de ese cuerpo.
- `exp.Union` produce `ramas=(Nodo(this), Nodo(expression))` y `union_all = args["distinct"] is False`. No lista las tablas de las ramas.
- Las subconsultas directas de `FROM`, `WHERE`, la lista de selección y el origen de un `INSERT` son `subconsultas`. Una subconsulta cuyo cuerpo es `Union` se entrega como ese `Nodo` unión, sin envoltorio.
- Las tablas directas salen de `FROM` y de cada `JOIN` que no sea una subconsulta. Un `FROM` con comas genera relaciones `cross` en orden de escritura.
- Cada `JOIN` directo produce una relación con `tipo` en `inner`, `left`, `right`, `full`, `cross` u `otro`, los dos lados y el `ON` como `Nodo` o `None`.
- Proyecciones, `WHERE`, `GROUP BY`, `HAVING`, `ORDER BY` y límite quedan como cláusulas cuyo valor es un `Nodo`.

`expresion` clasifica el nodo y sus hijos. Una `Column` rellena `nombre` y `calificador` desde el texto escrito. `Star` dentro de una función es hijo de `agregacion`, no una `forma` `asterisco` de la proyección. `Count` y el resto de agregados son `agregacion`. Una ventana es `ventana` y no cuenta como agregación.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_parser.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/analizador/parser.py tests/test_parser.py
git commit -m "feat: expose a SQLGlot-free syntax tree"
```

---

### Task 4: Árbol semántico y certeza de columnas

**Files:**
- Create: `src/analizador/semantica.py`
- Test: `tests/test_semantica.py`

**Interfaces:**
- Consumes: `bloque`, `expresion`, `normalizar`, `Componente`, `Tabla`, `Columna`.
- Produces: `componentes(nodo, indice_sentencia: int) -> Componente`. Los ids salen en preorden: la raíz es `s{indice}.c1`. El componente no publica el `Nodo`; lo guarda en `_nodo` y `a_dict()` lo omite. `explicacion` queda `None` en esta tarea.

- [ ] **Step 1: Write the failing test**

```python
from analizador.parser import parsear
from analizador.semantica import componentes


def _raiz(sql, dialecto="postgresql"):
    return componentes(parsear(sql, dialecto).sentencias[0].nodo, 1)


def test_subconsulta_no_copia_sus_tablas():
    raiz = _raiz("SELECT id FROM t WHERE id IN (SELECT id FROM u)")
    assert [t.nombre for t in raiz.tablas] == ["t"]
    assert raiz.hijos[0].clase == "subconsulta"
    assert [t.nombre for t in raiz.hijos[0].tablas] == ["u"]


def test_calificador_inexistente_es_no_resuelta():
    raiz = _raiz("SELECT x.salario FROM empleados AS e")
    columna = raiz.columnas[0]
    assert columna.certeza == "no_resuelta"
    assert columna.calificador == "x"
    assert columna.tabla is None
    assert columna.certeza != "sin_calificar"


def test_columna_sin_calificador_no_hereda_la_unica_tabla():
    raiz = _raiz("SELECT salario FROM empleados")
    assert raiz.columnas[0].certeza == "sin_calificar"
    assert raiz.columnas[0].tabla is None


def test_cte_anidada():
    raiz = _raiz("WITH a AS (WITH b AS (SELECT 1 AS n) SELECT n FROM b) SELECT n FROM a")
    assert raiz.hijos[0].clase == "cte"
    assert raiz.hijos[0].nombre == "a"
    assert [t.nombre for t in raiz.tablas] == ["a"]
    cte_b = raiz.hijos[0].hijos[0]
    assert cte_b.nombre == "b"
    assert cte_b.tablas == ()


def test_union_dentro_de_subconsulta():
    raiz = _raiz("SELECT * FROM (SELECT id FROM t UNION ALL SELECT id FROM u) AS s")
    assert raiz.hijos[0].clase == "union"
    assert [t.alias for t in raiz.tablas] == ["s"]
    ramas = raiz.hijos[0].hijos
    assert [t.nombre for t in ramas[0].tablas] == ["t"]
    assert [t.nombre for t in ramas[1].tablas] == ["u"]


def test_with_y_union_dejan_la_raiz_vacia():
    sql = (
        "WITH activos AS (SELECT id FROM empleados) "
        "SELECT id FROM activos UNION ALL SELECT id FROM antiguos"
    )
    raiz = _raiz(sql)
    assert raiz.tablas == ()
    assert raiz.hijos[0].clase == "cte"
    assert raiz.hijos[1].clase == "union"


def test_alias_unico_queda_resuelto():
    raiz = _raiz("SELECT e.salario FROM empleados AS e")
    assert raiz.columnas[0].certeza == "resuelta"
    assert raiz.columnas[0].tabla == "empleados"
    assert raiz.columnas[0].calificador == "e"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_semantica.py -v`

Expected: FAIL con `ImportError` de `componentes`

- [ ] **Step 3: Write minimal implementation**

`componentes` recorre `bloque` y asigna ids en preorden.

- Si hay `WITH` y el nodo es una unión, la raíz es `consulta` con listas vacías. Sus hijos son las CTE y, al final, un componente `union` construido sin repetir el `WITH`.
- Si hay `WITH` y el cuerpo es una consulta, las tablas del cuerpo viven en ese componente. Las CTE son los primeros hijos.
- Un hijo cuyo `bloque` tiene `ramas` recibe clase `union`. Si no, y no es una CTE, recibe clase `subconsulta` cuando cuelga de otro componente.
- La certeza se calcula solo con los orígenes directos de ese componente, después de conocer sus tablas: un calificador con un origen, `resuelta`; con varios, `ambigua`; con cero, `no_resuelta`; sin calificador, `sin_calificar`. No rellenes `tabla` en los tres últimos.
- Las columnas de una subconsulta no se añaden al padre. El hueco exterior guarda una columna o cláusula cuyo `expresion` es el SQL normalizado del hueco.
- `INSERT ... SELECT`: la tabla de destino queda en el `INSERT` con papel `destino`. El `SELECT` es un hijo y sus tablas no suben.
- `CREATE` usa papel `definicion` para la tabla y sus columnas. `ALTER` y `DROP` también usan `definicion` para el objeto nombrado.
- `componentes` rellena `pasos` con el orden lógico del spec. `rellenar` no los borra.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_semantica.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/analizador/semantica.py tests/test_semantica.py
git commit -m "feat: build the component tree and column certainty"
```

---

### Task 5: Explicaciones, resumen y formato

**Files:**
- Create: `src/analizador/explicacion.py`
- Create: `src/analizador/formato.py`
- Test: `tests/test_explicacion.py`

**Interfaces:**
- Consumes: `Componente`, `normalizar`, `mensajes.ORDEN_LOGICO`.
- Produces: `rellenar(componente: Componente) -> Componente`, `resumen(componente: Componente) -> str`, `pasos_sentencia(componente: Componente) -> tuple[str, ...]`, `formatear(nodo, dialecto: str) -> str`.

- [ ] **Step 1: Write the failing test**

```python
from analizador.explicacion import resumen
from analizador.formato import formatear
from analizador.parser import parsear
from analizador.semantica import componentes


def test_resumen_de_with_union_no_niega_los_origenes():
    sql = (
        "WITH activos AS (SELECT id FROM empleados) "
        "SELECT id FROM activos UNION ALL SELECT id FROM antiguos"
    )
    raiz = componentes(parsear(sql, "postgresql").sentencias[0].nodo, 1)
    texto = resumen(raiz)
    assert texto == "Combina con UNION ALL filas de activos y antiguos."
    assert "sin tabla de origen" not in texto


def test_create_no_se_explica_como_consulta():
    nodo = parsear("CREATE TABLE clientes (id INT)", "postgresql").sentencias[0].nodo
    texto = resumen(componentes(nodo, 1))
    assert texto == "Define clientes."
    assert not texto.startswith("Consulta")


def test_formato_recibe_nodo_y_dialecto():
    nodo = parsear("select top 1 [nombre] from [clientes]", "sqlserver").sentencias[0].nodo
    assert "TOP" in formatear(nodo, "sqlserver")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_explicacion.py -v`

Expected: FAIL con `ImportError`

- [ ] **Step 3: Write minimal implementation**

`formatear` es una línea: `return normalizar(nodo, dialecto)`. No importa sqlglot.

`explicacion.rellenar` recorre el componente y rellena `explicacion` con las plantillas del spec. Una cláusula cuyo nombre no tiene plantilla usa «Esta parte es un nodo {tipo} y su texto es {texto}.»

`resumen` aplica las reglas del spec. Si la raíz tiene listas vacías y un hijo `union`, el resumen es el de esa unión. No uses la plantilla de consulta sin orígenes solo porque `tablas` esté vacío.

`pasos_sentencia` antepone «Prepara la CTE {nombre}.» por cada CTE directa y después usa los pasos del cuerpo. Si ese cuerpo es la unión hija, los pasos son los de la unión. El orden de una consulta es orígenes, filtro, agrupación, filtro de grupos, columnas, `DISTINCT`, orden y límite.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_explicacion.py tests/test_semantica.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/analizador/explicacion.py src/analizador/formato.py tests/test_explicacion.py
git commit -m "feat: explain clauses and summarize set operations"
```

---

### Task 6: Advertencias

**Files:**
- Create: `src/analizador/advertencias.py`
- Test: `tests/test_advertencias.py`

**Interfaces:**
- Consumes: `Componente`, `expresion`, `bloque`, `normalizar`. `evaluar` lee `_nodo`.
- Produces: `evaluar(componente: Componente, dialecto: str) -> tuple[Advertencia, ...]`. Cada aviso tiene `gravedad="aviso"`.

- [ ] **Step 1: Write the failing test**

```python
from analizador.advertencias import evaluar
from analizador.parser import parsear
from analizador.semantica import componentes


def codigos(sql, dialecto="postgresql"):
    raiz = componentes(parsear(sql, dialecto).sentencias[0].nodo, 1)
    return [a.codigo for a in evaluar(raiz, dialecto)]


def test_where_en_el_lado_derecho_avisa():
    sql = "SELECT * FROM c LEFT JOIN p ON c.id = p.id WHERE p.estado = 'A'"
    assert "outer_join_filtrado" in codigos(sql)


def test_el_mismo_filtro_en_el_on_no_avisa():
    sql = "SELECT * FROM c LEFT JOIN p ON c.id = p.id AND p.estado = 'A'"
    assert "outer_join_filtrado" not in codigos(sql)


def test_is_null_no_avisa():
    sql = "SELECT * FROM c LEFT JOIN p ON c.id = p.id WHERE p.id IS NULL"
    assert "outer_join_filtrado" not in codigos(sql)


def test_or_que_puede_conservar_filas_no_avisa():
    sql = (
        "SELECT * FROM c LEFT JOIN p ON c.id = p.id "
        "WHERE p.estado = 'activo' OR c.prioridad = 'alta'"
    )
    assert "outer_join_filtrado" not in codigos(sql)


def test_where_constante_no_avisa():
    sql = "SELECT p.id FROM pedidos AS p LEFT JOIN clientes AS c ON p.cliente_id = c.id WHERE 1 = 0"
    assert "outer_join_filtrado" not in codigos(sql)


def test_count_estrella_no_avisa_y_select_estrella_si():
    assert "select_asterisco" in codigos("SELECT * FROM empleados")
    assert "select_asterisco" in codigos("SELECT e.* FROM empleados AS e")
    assert "select_asterisco" not in codigos("SELECT COUNT(*) FROM empleados")
    assert "select_asterisco" not in codigos("SELECT COUNT(e.*) FROM empleados AS e")


def test_igual_null_avisa():
    assert "comparacion_con_null" in codigos("SELECT * FROM t WHERE a = NULL")
    assert "comparacion_con_null" not in codigos("SELECT * FROM t WHERE a IS NULL")


def test_salario_mas_cien_no_avisa_si_salario_esta_agrupado():
    sql = "SELECT departamento, salario + 100 FROM empleados GROUP BY departamento, salario"
    assert "select_fuera_de_group_by" not in codigos(sql)


def test_salario_no_esta_cubierto_por_la_suma():
    sql = "SELECT salario FROM empleados GROUP BY salario + 100"
    assert "select_fuera_de_group_by" in codigos(sql)


def test_sqlite_no_avisa_por_agrupacion():
    sql = "SELECT salario FROM empleados GROUP BY departamento"
    assert "select_fuera_de_group_by" not in codigos(sql, "sqlite")


def test_calificador_inexistente_no_se_confunde_con_la_columna_suelta():
    sql = "SELECT x.salario FROM empleados AS e GROUP BY salario"
    assert "select_fuera_de_group_by" not in codigos(sql)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_advertencias.py -v`

Expected: FAIL con `ImportError` de `evaluar`

- [ ] **Step 3: Write minimal implementation**

Implementa las cuatro reglas del spec.

Para `outer_join_filtrado`, representa el predicado con cuatro resultados: `TRUE`, `FALSE`, `UNKNOWN`, `INDETERMINADO`. Una columna del lado anulable vale `NULL`. Una columna de otro lado vale `INDETERMINADO`. Si el predicado no contiene ninguna columna de ese lado, no evalúes y no avises. `AND` queda no verdadero si un operando es `FALSE` o `UNKNOWN`. `OR` solo queda no verdadero si todos los operandos lo están. `IN`, `LIKE`, `BETWEEN`, `CASE`, funciones y subconsultas valen `INDETERMINADO`.

`select_asterisco` solo mira un asterisco que sea la proyección o el hijo inmediato de su alias.

`select_fuera_de_group_by` no se emite en SQLite. Una referencia `no_resuelta` o `ambigua` no queda descubierta. Dos `sin_calificar` con el mismo nombre sí son la misma referencia. `resuelta` solo coincide con otra `resuelta` de la misma tabla y el mismo nombre. No llames a `sqlglot.optimizer.qualify`.

El `fragmento` sale de `normalizar` aplicado al nodo del predicado o de la expresión, no del texto original.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_advertencias.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/analizador/advertencias.py tests/test_advertencias.py
git commit -m "feat: warn only when a rule can prove the risk"
```

---

### Task 7: Coordinación del informe

**Files:**
- Create: `src/analizador/api.py`
- Modify: `src/analizador/__init__.py`
- Test: `tests/test_errores.py`
- Test: `tests/test_analizar.py`
- Test: `tests/test_frontera.py`

**Interfaces:**
- Consumes: `parsear`, `formatear`, `componentes`, `rellenar`, `resumen`, `pasos_sentencia`, `evaluar`, `DialectoNoSoportado`, `ErrorDeFase`, `Informe`, `Sentencia`.
- Produces: `analizar(sql: str, dialecto: str) -> Informe`.

- [ ] **Step 1: Write the failing test**

```python
import ast
from pathlib import Path

import pytest

from analizador import analizar
from analizador.errores import DialectoNoSoportado


def test_dialecto_desconocido_no_devuelve_informe():
    with pytest.raises(DialectoNoSoportado) as error:
        analizar("SELECT 1", "excel")
    assert "excel" in str(error.value)


def test_consulta_vacia():
    informe = analizar("   ", "postgresql")
    assert informe.sentencias == ()
    assert informe.errores[0].mensaje == "La consulta está vacía."


def test_fallo_de_fase_no_filtra_la_excepcion(monkeypatch):
    def romper(nodo, dialecto):
        raise RuntimeError("fallo de prueba")

    monkeypatch.setattr("analizador.api.formatear", romper)
    informe = analizar("SELECT 1; SELECT 2", "postgresql")
    assert informe.errores[0].mensaje == (
        "No se ha podido formatear la sentencia 1 (Select). "
        "El detalle técnico quedó en el registro del servidor."
    )
    assert "fallo de prueba" not in informe.errores[0].mensaje
    assert informe.sentencias[1].sql_formateado is not None


def test_ningun_modulo_de_fase_importa_sqlglot():
    raiz = Path("src/analizador")
    prohibidos = [
        "semantica.py",
        "explicacion.py",
        "advertencias.py",
        "formato.py",
        "api.py",
        "modelo.py",
        "dialectos.py",
        "mensajes.py",
        "errores.py",
    ]
    for nombre in prohibidos:
        arbol = ast.parse((raiz / nombre).read_text())
        importados = [
            nodo.names[0].name if hasattr(nodo, "names") else nodo.module
            for nodo in ast.walk(arbol)
            if isinstance(nodo, (ast.Import, ast.ImportFrom))
        ]
        assert "sqlglot" not in importados
```

`tests/test_analizar.py` usa `analizar` y afirma `errores == ()`, `tipo` relleno y, en `ALTER`, `DROP` y `MERGE`, que el resumen no empieza por «Consulta». Las sentencias son:

```python
COMUN = """
SELECT c.nombre, COUNT(p.id) AS total
FROM clientes AS c
INNER JOIN pedidos AS p ON p.cliente_id = c.id
WHERE c.activo = 1
GROUP BY c.nombre
"""
CASOS = {
    "postgresql": [
        COMUN,
        "SELECT nombre FROM clientes WHERE nombre ILIKE 'a%'",
        "INSERT INTO clientes (id) VALUES (1) ON CONFLICT (id) DO NOTHING",
        "WITH RECURSIVE c AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM c WHERE n < 3) SELECT n FROM c",
        "CREATE TABLE clientes (id INT)",
        "ALTER TABLE clientes ADD COLUMN activo BOOLEAN",
        "DROP TABLE clientes",
    ],
    "mysql": [
        COMUN,
        "SELECT `nombre` FROM `clientes`",
        "INSERT INTO clientes (id, nombre) VALUES (1, 'a') ON DUPLICATE KEY UPDATE nombre = 'b'",
        "WITH RECURSIVE c AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM c WHERE n < 3) SELECT n FROM c",
        "CREATE TABLE clientes (id INT)",
        "ALTER TABLE clientes ADD COLUMN activo BOOL",
        "DROP TABLE IF EXISTS clientes",
    ],
    "sqlite": [
        COMUN,
        'SELECT "nombre" FROM "clientes"',
        "WITH RECURSIVE c AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM c WHERE n < 3) SELECT n FROM c",
        "CREATE TABLE IF NOT EXISTS clientes (id INTEGER)",
        "ALTER TABLE clientes ADD COLUMN activo INTEGER",
        "DROP TABLE IF EXISTS clientes",
    ],
    "sqlserver": [
        COMUN,
        "SELECT TOP 1 [nombre] FROM [clientes]",
        "CREATE TABLE clientes (id INT, nombre NVARCHAR(20))",
        "ALTER TABLE clientes ADD activo BIT",
        "DROP TABLE clientes",
        "MERGE INTO clientes AS t USING (SELECT 1 AS id) AS s ON t.id = s.id WHEN MATCHED THEN UPDATE SET t.nombre = 'a';",
    ],
}
```

Además, en PostgreSQL: `INSERT INTO clientes (id, nombre) VALUES (1, 'Ana')`, `UPDATE clientes SET nombre = 'Ana' WHERE id = 1` y `DELETE FROM clientes WHERE id = 1`. En el `WITH RECURSIVE`, hay una sola CTE llamada `c`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_errores.py tests/test_frontera.py tests/test_analizar.py -v`

Expected: FAIL con `ImportError` de `analizar`

- [ ] **Step 3: Write minimal implementation**

`api.analizar` llama a `nombre_interno` antes de parsear, de modo que un dialecto desconocido lanza `DialectoNoSoportado`.

Si `sql.strip()` está vacío, devuelve un `Informe` con `CONSULTA_VACIA` y ninguna sentencia.

Después llama a `parsear`. Si hay errores, los copia al informe y no construye sentencias.

Por cada sentencia, en este orden, atrapa `ErrorDeFase` y `Exception`:

1. `formatear`. Si falla, la sentencia queda con `sql_formateado`, `arbol` y `resumen` a `None`, y `pasos` y `advertencias` vacíos.
2. `componentes`. Si falla, se conserva el SQL formateado.
3. `rellenar`, `resumen` y `pasos_sentencia`. Si fallan, se conservan formato, árbol y pasos ya calculados por la semántica; `resumen` y cada `explicacion` quedan `None`; no se evalúan advertencias.
4. `evaluar`. Si falla, se conserva lo anterior y `advertencias` queda vacío.

El mensaje de cara al usuario sale de `mensajes.fallo_fase` o de `FALLO_ADVERTENCIAS`. El `except` escribe en el logger el tipo, el mensaje completo y la traza. No los mete en `Error.mensaje`.

`__init__.py` exporta `analizar`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_errores.py tests/test_frontera.py tests/test_analizar.py tests/test_semantica.py tests/test_advertencias.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/analizador/api.py src/analizador/__init__.py tests/test_errores.py tests/test_analizar.py tests/test_frontera.py
git commit -m "feat: coordinate analysis without leaking internal errors"
```

---

### Task 8: Página local

**Files:**
- Create: `web/__init__.py`
- Create: `web/app.py`
- Create: `web/plantillas/index.html`
- Create: `web/estaticos/estilo.css`
- Create: `web/estaticos/app.js`
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `analizar`, `DialectoNoSoportado`, `mensajes`.
- Produces: `GET /` y `POST /analizar`. El cuerpo de éxito es `Informe.a_dict()`. El cuerpo de error es `{"mensaje": "..."}`.

- [ ] **Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient

from web.app import app

cliente = TestClient(app)


def test_formulario_muestra_los_cuatro_dialectos():
    respuesta = cliente.get("/")
    assert respuesta.status_code == 200
    for nombre in ("PostgreSQL", "MySQL", "SQLite", "SQL Server"):
        assert nombre in respuesta.text


def test_post_devuelve_el_informe():
    respuesta = cliente.post("/analizar", json={"sql": "SELECT 1", "dialecto": "postgresql"})
    assert respuesta.status_code == 200
    assert respuesta.json()["sentencias"][0]["tipo"] == "Select"


def test_dialecto_ausente():
    respuesta = cliente.post("/analizar", json={"sql": "SELECT 1"})
    assert respuesta.status_code == 400
    assert respuesta.json()["mensaje"] == "Falta el dialecto. Elige PostgreSQL, MySQL, SQLite o SQL Server."


def test_consulta_grande():
    respuesta = cliente.post(
        "/analizar",
        json={"sql": "a" * 1048577, "dialecto": "postgresql"},
    )
    assert respuesta.status_code == 400
    assert "1048576" in respuesta.json()["mensaje"]


def test_error_interno_no_sale_en_el_cuerpo(monkeypatch):
    def romper(sql, dialecto):
        raise RuntimeError("fallo de prueba")

    monkeypatch.setattr("web.app.analizar", romper)
    respuesta = cliente.post("/analizar", json={"sql": "SELECT 1", "dialecto": "postgresql"})
    assert respuesta.status_code == 500
    assert respuesta.json()["mensaje"] == (
        "No se ha podido construir el informe durante el parseo. "
        "El detalle técnico quedó en el registro del servidor."
    )
    assert "fallo de prueba" not in respuesta.text


def test_el_script_no_usa_innerhtml():
    assert "innerHTML" not in open("web/estaticos/app.js", encoding="utf-8").read()
```

Los otros 400 son: cuerpo `no-json` con cabecera `application/json` y mensaje «El cuerpo de la petición tiene que ser un JSON con sql y dialecto.»; JSON sin `sql` y mensaje «Falta la consulta.»; `"sql": 1` y mensaje «La consulta tiene que ser un texto.»; `"dialecto": "excel"` y el mensaje de dialecto no soportado.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_web.py -v`

Expected: FAIL con `ModuleNotFoundError: web`

- [ ] **Step 3: Write minimal implementation**

`web/app.py` crea FastAPI y monta `web/estaticos`. `GET /` devuelve la plantilla con autoescape. `POST /analizar` lee el JSON, rechaza los cuerpos descritos y, si `len(sql.encode("utf-8")) > 1048576`, responde 400. Llama a `analizar`. `DialectoNoSoportado` es 400. Cualquier otra excepción es 500 con `fallo_informe("el parseo")` si ocurre antes de tener informe; el logger recibe la traza.

`app.js` pide `POST /analizar` con `fetch` y pinta el informe creando nodos y asignando `textContent`. El formulario tiene el selector, el área de texto y el botón Analizar. El primer valor del selector es PostgreSQL. Antes de la respuesta solo se ve el formulario y «Elige un dialecto y pega la sentencia.» Con errores de script no se dibuja el árbol. Con sentencias, el orden es tipo y resumen, pasos con la frase del orden lógico, advertencias, árbol plegable y SQL formateado con botón Copiar.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest -v`

Expected: PASS en toda la suite

- [ ] **Step 5: Commit**

```bash
git add web tests/test_web.py
git commit -m "feat: serve the local report page"
```

---

## Self-review

Cobertura del spec:

- Frontera con SQLGlot: tareas 3 y 7 (`test_frontera`).
- Certeza `no_resuelta`: tarea 4 y el caso de agrupación de la tarea 6.
- Resumen de `WITH` más `UNION`: tarea 5.
- `WHERE 1 = 0`: tarea 6.
- Errores internos sin detalle técnico: tareas 7 y 8.
- DDL, `WITH RECURSIVE` y operaciones de dialecto: tarea 7.
- Página, límite de 1 MB y `textContent`: tarea 8.

No hay tareas de esquema, modelo de lenguaje ni reescritura. Esas quedan fuera del spec.
