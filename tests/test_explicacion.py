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
