from analizador import analizar
from analizador.explicacion import resumen
from analizador.formato import formatear
from analizador.parser import parsear
from analizador.semantica import componentes


def _sentencia(sql, dialecto="postgresql"):
    informe = analizar(sql, dialecto)
    assert informe.errores == ()
    return informe.sentencias[0]


def test_resumen_de_with_union_no_niega_los_origenes():
    sql = (
        "WITH activos AS (SELECT id FROM empleados) "
        "SELECT id FROM activos UNION ALL SELECT id FROM antiguos"
    )
    raiz = componentes(parsear(sql, "postgresql").sentencias[0].nodo, 1, "postgresql")
    texto = resumen(raiz)
    assert texto == "Combina con UNION ALL filas de activos y antiguos."
    assert "sin tabla de origen" not in texto


def test_create_no_se_explica_como_consulta():
    nodo = parsear("CREATE TABLE clientes (id INT)", "postgresql").sentencias[0].nodo
    texto = resumen(componentes(nodo, 1, "postgresql"))
    assert texto == "Define clientes."
    assert not texto.startswith("Consulta")


def test_formato_recibe_nodo_y_dialecto():
    nodo = parsear("select top 1 [nombre] from [clientes]", "sqlserver").sentencias[0].nodo
    assert "TOP" in formatear(nodo, "sqlserver")


def test_left_join_using_no_es_producto_cruzado():
    sentencia = _sentencia("SELECT * FROM a LEFT JOIN b USING (id)")
    relacion = sentencia.arbol.relaciones[0]
    assert relacion.tipo == "left"
    assert relacion.condicion is not None
    assert "USING" in relacion.condicion
    assert "id" in relacion.condicion
    textos = list(sentencia.pasos) + [relacion.explicacion or ""]
    assert all("producto cruzado" not in texto for texto in textos)
    assert any("por " in paso and "USING" in paso for paso in sentencia.pasos)


def test_natural_join_no_es_producto_cruzado():
    sentencia = _sentencia("SELECT * FROM a NATURAL JOIN b")
    relacion = sentencia.arbol.relaciones[0]
    textos = list(sentencia.pasos) + [relacion.explicacion or ""]
    assert all("producto cruzado" not in texto for texto in textos)
    assert any("NATURAL JOIN" in texto for texto in textos)
    exterior = _sentencia("SELECT * FROM a NATURAL LEFT JOIN b")
    assert any("NATURAL LEFT JOIN" in paso for paso in exterior.pasos)
    assert all("producto cruzado" not in paso for paso in exterior.pasos)


def test_coma_y_cross_join_siguen_en_producto_cruzado():
    for sql in ("SELECT * FROM a, b", "SELECT * FROM a CROSS JOIN b"):
        sentencia = _sentencia(sql)
        assert any("producto cruzado" in paso for paso in sentencia.pasos)


def test_top_de_sql_server_no_se_llama_limit():
    sentencia = _sentencia("SELECT TOP 1 [nombre] FROM [clientes]", "sqlserver")
    limites = [clausula for clausula in sentencia.arbol.clausulas if clausula.nombre in {"LIMIT", "TOP", "FETCH"}]
    assert [clausula.nombre for clausula in limites] == ["TOP"]
    assert "LIMIT" not in limites[0].texto
    assert "TOP" in limites[0].texto
    assert all("LIMIT" not in paso for paso in sentencia.pasos)
    assert any("TOP" in paso for paso in sentencia.pasos)


def test_mysql_conserva_los_backticks():
    sentencia = _sentencia("SELECT `nombre` FROM `clientes` WHERE `nombre` = 'a'", "mysql")
    where = next(clausula for clausula in sentencia.arbol.clausulas if clausula.nombre == "WHERE")
    assert "`nombre`" in where.texto
    assert '"nombre"' not in where.texto
    assert any("`nombre`" in paso for paso in sentencia.pasos)
    assert all('"nombre"' not in paso for paso in sentencia.pasos)


def test_values_no_niega_el_origen():
    sentencia = _sentencia("SELECT * FROM (VALUES (1)) AS v(c)")
    assert "sin tabla de origen" not in sentencia.resumen
    assert [(tabla.nombre, tabla.alias) for tabla in sentencia.arbol.tablas] == [("v", "v")]


def test_generate_series_conserva_el_nombre():
    sentencia = _sentencia("SELECT * FROM generate_series(1, 3) AS g")
    assert "sin tabla de origen" not in sentencia.resumen
    assert "sobre ." not in sentencia.resumen
    assert sentencia.arbol.tablas[0].alias == "g"
    assert "GENERATE_SERIES" in sentencia.arbol.tablas[0].nombre.upper()


def test_insert_on_conflict_menciona_la_clausula():
    sentencia = _sentencia("INSERT INTO dest (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
    texto = " ".join(sentencia.pasos)
    assert "dest" in texto
    assert "id" in texto
    assert "valores" in texto
    assert "ON CONFLICT" in texto
    assert [tabla.nombre for tabla in sentencia.arbol.tablas] == ["dest"]


def test_update_set_menciona_la_asignacion():
    sentencia = _sentencia("UPDATE t SET nombre = 'a' WHERE id = 1")
    assert any(paso.startswith("Asigna ") and "nombre" in paso for paso in sentencia.pasos)


def test_update_from_y_delete_using_conservan_el_origen():
    actualizado = _sentencia("UPDATE t SET nombre = 'a' FROM s WHERE t.id = s.id")
    assert [tabla.nombre for tabla in actualizado.arbol.tablas] == ["t", "s"]
    assert actualizado.arbol.tablas[0].papel == "destino"
    assert any(paso.startswith("Asigna ") for paso in actualizado.pasos)
    assert any("s" in paso for paso in actualizado.pasos)
    borrado = _sentencia("DELETE FROM t USING s WHERE t.id = s.id")
    assert [tabla.nombre for tabla in borrado.arbol.tablas] == ["t", "s"]
    assert borrado.arbol.tablas[0].papel == "destino"
    assert any("s" in paso for paso in borrado.pasos)


def test_origen_de_update_no_copia_las_tablas_del_hijo():
    sentencia = _sentencia("UPDATE t SET a = 1 FROM (SELECT id FROM secretos) AS x WHERE t.id = x.id")
    assert "secretos" not in [tabla.nombre for tabla in sentencia.arbol.tablas]
    assert [tabla.nombre for tabla in sentencia.arbol.tablas if tabla.papel == "destino"] == ["t"]
    assert any(tabla.nombre == "secretos" for hijo in sentencia.arbol.hijos for tabla in hijo.tablas)
