from analizador.parser import parsear
from analizador.semantica import componentes


def _raiz(sql, dialecto="postgresql"):
    return componentes(parsear(sql, dialecto).sentencias[0].nodo, 1, dialecto)


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


def test_ventana_no_se_clasifica_como_columna_sin_calificar():
    raiz = _raiz(
        "WITH ventas_por_cliente AS ("
        " SELECT cliente_id, SUM(importe) AS importe FROM ventas GROUP BY cliente_id"
        ") "
        "SELECT ROW_NUMBER() OVER (ORDER BY importe DESC) AS numero_fila, "
        "SUM(v.importe) OVER (PARTITION BY v.cliente_id) AS total_cliente "
        "FROM ventas_por_cliente AS v"
    )
    numero_fila, total_cliente = raiz.columnas
    assert numero_fila.alias == "numero_fila"
    assert total_cliente.alias == "total_cliente"
    for columna in (numero_fila, total_cliente):
        assert columna.certeza is None
        assert columna.nombre is None
        assert columna.calificador is None
        assert columna.tabla is None
