from analizador.parser import bloque, expresion, normalizar, parsear


def _nodo(sql, dialecto="postgresql"):
    return parsear(sql, dialecto).sentencias[0].nodo


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


def test_parentesis_se_detiene_en_la_posicion_del_error():
    resultado = parsear("SELECT (1; SELECT (2", "postgresql")
    assert "paréntesis abierto" in resultado.errores[0].mensaje
    assert resultado.errores[0].linea == 1
    assert resultado.errores[0].columna == 8


def test_parentesis_posterior_no_cierra_el_anterior():
    resultado = parsear("SELECT (1; SELECT 2)", "postgresql")
    assert "paréntesis abierto" in resultado.errores[0].mensaje
    assert resultado.errores[0].linea == 1
    assert resultado.errores[0].columna == 8


def test_cadena_e_sin_cerrar_es_comilla():
    resultado = parsear("SELECT E'foo\\'", "postgresql")
    assert resultado.sentencias == ()
    assert "comilla abierta" in resultado.errores[0].mensaje
    assert resultado.errores[0].linea == 1
    assert resultado.errores[0].columna == 9


def test_cadena_e_cerrada_no_oculta_la_comilla_siguiente():
    resultado = parsear("SELECT E'it\\'s'; SELECT 'ab", "postgresql")
    assert "comilla abierta" in resultado.errores[0].mensaje
    assert resultado.errores[0].linea == 1
    assert resultado.errores[0].columna == 25


def test_comilla_mysql_no_trata_la_otra_comilla_como_escape():
    resultado = parsear("""SELECT 'He said "hello"'; SELECT 'ab""", "mysql")
    assert "comilla abierta" in resultado.errores[0].mensaje
    assert resultado.errores[0].linea == 1
    assert resultado.errores[0].columna == 34


def test_date_add_sin_intervalo_es_error_de_sintaxis():
    resultado = parsear("SELECT DATE_ADD('2020-01-01', 1)", "mysql")
    assert resultado.sentencias == ()
    assert len(resultado.errores) == 1
    assert resultado.errores[0].mensaje
    assert "INTERVAL expression expected but got '1'" in resultado.errores[0].mensaje


def test_comentario_anidado_cerrado_no_oculta_la_comilla():
    resultado = parsear("/*/*/ SELECT 'ab", "postgresql")
    assert "comilla abierta" in resultado.errores[0].mensaje
    assert "comentario abierto" not in resultado.errores[0].mensaje


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


def test_normalizar_usa_el_dialecto():
    nodo = _nodo("select top 1 [nombre] from [clientes]", "sqlserver")
    assert "TOP" in normalizar(nodo, "sqlserver")


def test_cte_no_copia_las_tablas_del_cuerpo():
    sql = "WITH a AS (WITH b AS (SELECT 1 AS n) SELECT n FROM b) SELECT n FROM a"
    nivel = bloque(_nodo(sql))
    assert [cte.alias for cte in nivel.ctes] == ["a"]
    assert [tabla.nombre for tabla in nivel.tablas] == ["a"]
    cuerpo = bloque(nivel.ctes[0].nodo)
    assert [cte.alias for cte in cuerpo.ctes] == ["b"]
    assert [tabla.nombre for tabla in cuerpo.tablas] == ["b"]
    assert bloque(cuerpo.ctes[0].nodo).tablas == ()


def test_union_no_lista_las_tablas_de_las_ramas():
    sql = (
        "WITH activos AS (SELECT id FROM empleados) "
        "SELECT id FROM activos UNION ALL SELECT id FROM antiguos"
    )
    nivel = bloque(_nodo(sql))
    assert nivel.union_all is True
    assert nivel.tablas == ()
    assert [cte.alias for cte in nivel.ctes] == ["activos"]
    assert [tabla.nombre for tabla in bloque(nivel.ctes[0].nodo).tablas] == ["empleados"]
    assert [tabla.nombre for tabla in bloque(nivel.ramas[0]).tablas] == ["activos"]
    assert [tabla.nombre for tabla in bloque(nivel.ramas[1]).tablas] == ["antiguos"]


def test_union_distinto_no_marca_union_all():
    nivel = bloque(_nodo("SELECT id FROM t UNION SELECT id FROM u"))
    assert nivel.union_all is False
    assert bloque(_nodo("SELECT 1")).union_all is None
    assert bloque(_nodo("SELECT 1")).ramas is None


def test_alias_de_subconsulta_en_from():
    nivel = bloque(_nodo("SELECT * FROM (SELECT id FROM t UNION ALL SELECT id FROM u) AS s"))
    assert nivel.tablas == ()
    assert nivel.subconsultas[0].alias == "s"
    assert bloque(nivel.subconsultas[0].nodo).ramas is not None
    where = bloque(_nodo("SELECT id FROM t WHERE id IN (SELECT id FROM u)"))
    assert where.subconsultas[0].alias is None


def test_alias_de_la_proyeccion_no_es_origen():
    nivel = bloque(_nodo("SELECT (SELECT id FROM t) AS s FROM u"))
    assert nivel.subconsultas[0].alias is None
    proyeccion = expresion(nivel.proyecciones[0])
    assert proyeccion.forma == "alias"
    assert proyeccion.nombre == "s"
    assert [tabla.nombre for tabla in nivel.tablas] == ["u"]


def test_union_expone_order_by_y_limite_en_el_bloque():
    nivel = bloque(_nodo("SELECT id FROM t UNION SELECT id FROM u ORDER BY id LIMIT 5"))
    assert [clausula.nombre for clausula in nivel.clausulas] == ["ORDER BY", "LIMIT"]
    assert all(bloque(rama).clausulas == () for rama in nivel.ramas)
    fetch = bloque(
        _nodo(
            "SELECT id FROM t UNION SELECT id FROM u "
            "ORDER BY id OFFSET 2 FETCH FIRST 1 ROW ONLY"
        )
    )
    assert [clausula.nombre for clausula in fetch.clausulas] == ["ORDER BY", "OFFSET", "FETCH"]
    assert all(bloque(rama).clausulas == () for rama in fetch.ramas)


def test_envoltorio_conserva_order_by_y_limite():
    orden = bloque(_nodo("SELECT * FROM ((SELECT id FROM t) ORDER BY id) AS s"))
    assert "ORDER BY" in normalizar(orden.subconsultas[0].nodo, "postgresql")
    limitado = bloque(_nodo("SELECT * FROM ((SELECT id FROM t) ORDER BY id LIMIT 1) s"))
    texto = normalizar(limitado.subconsultas[0].nodo, "postgresql")
    assert "ORDER BY" in texto
    assert "LIMIT" in texto
    assert limitado.subconsultas[0].alias == "s"
    interno = bloque(_nodo("SELECT * FROM (SELECT id FROM t ORDER BY id) AS s"))
    assert "ORDER BY" in normalizar(interno.subconsultas[0].nodo, "postgresql")


def test_all_y_some_dejan_la_subconsulta():
    mayor = bloque(_nodo("SELECT * FROM t WHERE id > ALL (SELECT id FROM u)"))
    assert len(mayor.subconsultas) == 1
    assert mayor.subconsultas[0].alias is None
    assert [tabla.nombre for tabla in bloque(mayor.subconsultas[0].nodo).tablas] == ["u"]
    alguno = bloque(_nodo("SELECT * FROM t WHERE id = SOME (SELECT id FROM u)"))
    assert len(alguno.subconsultas) == 1
    assert alguno.subconsultas[0].alias is None
    conjunto = bloque(
        _nodo("SELECT * FROM t WHERE id > ALL (SELECT id FROM u UNION SELECT id FROM v)")
    )
    assert len(conjunto.subconsultas) == 1
    assert conjunto.subconsultas[0].alias is None
    assert bloque(conjunto.subconsultas[0].nodo).ramas is not None
    lista = bloque(_nodo("SELECT id > ALL (SELECT id FROM u) FROM t"))
    assert len(lista.subconsultas) == 1
    assert lista.subconsultas[0].alias is None


def test_subconsulta_de_union_no_tiene_envoltorio():
    sql = "SELECT * FROM (SELECT id FROM t UNION ALL SELECT id FROM u) AS s"
    nivel = bloque(_nodo(sql))
    assert len(nivel.subconsultas) == 1
    interno = bloque(nivel.subconsultas[0].nodo)
    assert interno.union_all is True
    assert [tabla.nombre for tabla in bloque(interno.ramas[0]).tablas] == ["t"]
    assert [tabla.nombre for tabla in bloque(interno.ramas[1]).tablas] == ["u"]
    assert [tabla.nombre for tabla in nivel.tablas] == []


def test_from_con_comas_relaciona_en_orden_de_escritura():
    nivel = bloque(_nodo("SELECT a.id FROM a, b, c"))
    assert [tabla.nombre for tabla in nivel.tablas] == ["a", "b", "c"]
    assert [relacion.tipo for relacion in nivel.relaciones] == ["cross", "cross"]
    assert [relacion.condicion for relacion in nivel.relaciones] == [None, None]
    assert normalizar(nivel.relaciones[0].izquierda, "postgresql") == "a"
    assert normalizar(nivel.relaciones[0].derecha, "postgresql") == "b"
    assert normalizar(nivel.relaciones[1].izquierda, "postgresql") == "b"
    assert normalizar(nivel.relaciones[1].derecha, "postgresql") == "c"


def test_using_es_la_condicion_del_join():
    relacion = bloque(_nodo("SELECT * FROM a LEFT JOIN b USING (id)")).relaciones[0]
    assert relacion.tipo == "left"
    assert relacion.condicion is not None
    texto = normalizar(relacion.condicion, "postgresql")
    assert "USING" in texto
    assert "id" in texto


def test_natural_no_guarda_condicion():
    relacion = bloque(_nodo("SELECT * FROM a NATURAL JOIN b")).relaciones[0]
    assert relacion.tipo == "otro"
    assert relacion.condicion is None
    assert relacion.forma == "NATURAL JOIN"
    izquierda = bloque(_nodo("SELECT * FROM a NATURAL LEFT JOIN b")).relaciones[0]
    assert izquierda.forma == "NATURAL LEFT JOIN"
    assert izquierda.condicion is None


def test_values_y_funcion_conservan_el_origen():
    valores = bloque(_nodo("SELECT * FROM (VALUES (1)) AS v(c)"))
    assert [(tabla.nombre, tabla.alias) for tabla in valores.tablas] == [("v", "v")]
    serie = bloque(_nodo("SELECT * FROM generate_series(1, 3) AS g"))
    assert serie.tablas[0].alias == "g"
    assert "GENERATE_SERIES" in serie.tablas[0].nombre.upper()


def test_having_y_on_dejan_la_subconsulta_abajo():
    having = bloque(
        _nodo("SELECT id FROM t GROUP BY id HAVING id IN (SELECT id FROM secretos WHERE x = NULL)")
    )
    assert [tabla.nombre for tabla in having.tablas] == ["t"]
    assert [tabla.nombre for tabla in bloque(having.subconsultas[0].nodo).tablas] == ["secretos"]
    unido = bloque(_nodo("SELECT * FROM a JOIN b ON a.id = (SELECT id FROM secretos WHERE x = NULL)"))
    assert [tabla.nombre for tabla in unido.tablas] == ["a", "b"]
    assert [tabla.nombre for tabla in bloque(unido.subconsultas[0].nodo).tablas] == ["secretos"]


def test_update_from_y_delete_using_conservan_el_origen():
    actualizado = bloque(_nodo("UPDATE t SET nombre = 'a' FROM s WHERE t.id = s.id"))
    assert [tabla.nombre for tabla in actualizado.tablas] == ["t", "s"]
    assert any(clausula.nombre == "SET" for clausula in actualizado.clausulas)
    borrado = bloque(_nodo("DELETE FROM t USING s WHERE t.id = s.id"))
    assert [tabla.nombre for tabla in borrado.tablas] == ["t", "s"]


def test_insert_expone_columnas_valores_y_conflicto():
    nivel = bloque(_nodo("INSERT INTO dest (id) VALUES (1) ON CONFLICT (id) DO NOTHING"))
    nombres = [clausula.nombre for clausula in nivel.clausulas]
    assert "VALUES" in nombres
    assert "ON CONFLICT" in nombres
    assert [tabla.nombre for tabla in nivel.tablas] == ["dest"]
    assert nivel.subconsultas == ()


def test_join_guarda_tipo_lados_y_on():
    consultas = {
        "SELECT * FROM a JOIN b ON a.id = b.id": "inner",
        "SELECT * FROM a LEFT JOIN b ON a.id = b.id": "left",
        "SELECT * FROM a RIGHT JOIN b ON a.id = b.id": "right",
        "SELECT * FROM a FULL JOIN b ON a.id = b.id": "full",
        "SELECT * FROM a CROSS JOIN b": "cross",
        "SELECT * FROM a NATURAL JOIN b": "otro",
    }
    for sql, tipo in consultas.items():
        relacion = bloque(_nodo(sql)).relaciones[0]
        assert relacion.tipo == tipo
        assert normalizar(relacion.izquierda, "postgresql") == "a"
        assert normalizar(relacion.derecha, "postgresql") == "b"
        if tipo == "cross" or tipo == "otro":
            assert relacion.condicion is None
        else:
            assert normalizar(relacion.condicion, "postgresql") == "a.id = b.id"


def test_subconsulta_de_where_no_sube_su_tabla():
    sql = "SELECT id FROM t WHERE id IN (SELECT id FROM u WHERE id IN (SELECT id FROM v))"
    nivel = bloque(_nodo(sql))
    assert [tabla.nombre for tabla in nivel.tablas] == ["t"]
    assert len(nivel.subconsultas) == 1
    interna = bloque(nivel.subconsultas[0].nodo)
    assert [tabla.nombre for tabla in interna.tablas] == ["u"]
    assert [tabla.nombre for tabla in bloque(interna.subconsultas[0].nodo).tablas] == ["v"]


def test_insert_separa_destino_y_origen():
    nivel = bloque(_nodo("INSERT INTO dest SELECT id FROM src"))
    assert [tabla.nombre for tabla in nivel.tablas] == ["dest"]
    assert [tabla.nombre for tabla in bloque(nivel.subconsultas[0].nodo).tablas] == ["src"]


def test_delete_no_sube_la_tabla_de_la_subconsulta():
    nivel = bloque(_nodo("DELETE FROM t WHERE id IN (SELECT id FROM u)"))
    assert [tabla.nombre for tabla in nivel.tablas] == ["t"]
    assert [tabla.nombre for tabla in bloque(nivel.subconsultas[0].nodo).tablas] == ["u"]


def test_create_expone_la_tabla_y_sus_columnas():
    nivel = bloque(_nodo("CREATE TABLE clientes (id INT, nombre TEXT)"))
    assert nivel.tipo == "Create"
    assert [(tabla.nombre, tabla.alias) for tabla in nivel.tablas] == [("clientes", None)]
    assert [expresion(columna).nombre for columna in nivel.proyecciones] == ["id", "nombre"]


def test_drop_y_alter_exponen_el_objeto():
    assert [tabla.nombre for tabla in bloque(_nodo("DROP TABLE clientes")).tablas] == ["clientes"]
    assert [tabla.nombre for tabla in bloque(_nodo("ALTER TABLE clientes ADD COLUMN edad INT")).tablas] == [
        "clientes"
    ]


def test_clausulas_directas_no_incluyen_la_proyeccion():
    sql = (
        "SELECT DISTINCT d FROM e WHERE d > 1 GROUP BY d "
        "HAVING d > 1 ORDER BY d LIMIT 10 OFFSET 2"
    )
    nivel = bloque(_nodo(sql))
    assert [clausula.nombre for clausula in nivel.clausulas] == [
        "WHERE",
        "GROUP BY",
        "HAVING",
        "DISTINCT",
        "ORDER BY",
        "OFFSET",
        "LIMIT",
    ]
    assert len(nivel.proyecciones) == 1
    assert expresion(nivel.proyecciones[0]).forma == "columna"


def test_calificador_escrito_no_es_la_tabla_del_from():
    proyeccion = expresion(bloque(_nodo("SELECT e.salario FROM empleados AS e")).proyecciones[0])
    assert proyeccion.forma == "columna"
    assert proyeccion.nombre == "salario"
    assert proyeccion.calificador == "e"
    citada_nivel = bloque(_nodo('SELECT "E"."Salario" FROM "Empleados" AS "E"'))
    citada = expresion(citada_nivel.proyecciones[0])
    assert citada.nombre == "Salario"
    assert citada.calificador == "E"
    assert citada_nivel.tablas[0].nombre == "Empleados"
    assert citada_nivel.tablas[0].alias == "E"


def test_estrella_calificada_es_asterisco_y_dentro_de_count_es_hija():
    estrella = expresion(bloque(_nodo("SELECT e.* FROM empleados AS e")).proyecciones[0])
    assert estrella.forma == "asterisco"
    assert estrella.calificador == "e"
    cuenta = expresion(bloque(_nodo("SELECT COUNT(*) FROM empleados")).proyecciones[0])
    assert cuenta.forma == "agregacion"
    assert [hijo.forma for hijo in cuenta.hijos] == ["asterisco"]
    calificada = expresion(
        bloque(_nodo("SELECT COUNT(e.*) FROM empleados AS e")).proyecciones[0]
    )
    assert calificada.forma == "agregacion"
    assert [(hijo.forma, hijo.calificador) for hijo in calificada.hijos] == [("asterisco", "e")]


def test_ventana_no_es_agregacion():
    sql = "SELECT SUM(salario) OVER (PARTITION BY departamento ORDER BY id) FROM empleados"
    forma = expresion(bloque(_nodo(sql)).proyecciones[0])
    assert forma.forma == "ventana"
    agregados = [hijo for hijo in forma.hijos if hijo.forma == "agregacion"]
    assert len(agregados) == 1
    assert [(hijo.forma, hijo.nombre) for hijo in agregados[0].hijos] == [("columna", "salario")]
    fuera = [hijo.nombre for hijo in forma.hijos if hijo.forma == "columna"]
    assert "departamento" in fuera
    assert "id" in fuera
    assert "salario" not in fuera


def test_alias_envuelve_la_expresion():
    forma = expresion(bloque(_nodo("SELECT salario + 100 AS total FROM empleados")).proyecciones[0])
    assert forma.forma == "alias"
    assert forma.nombre == "total"
    assert [hijo.forma for hijo in forma.hijos[0].hijos] == ["columna", "literal"]


def test_predicados_conservan_su_forma():
    def predicado(sql):
        where = next(clausula for clausula in bloque(_nodo(sql)).clausulas if clausula.nombre == "WHERE")
        return expresion(where.nodo)

    assert predicado("SELECT * FROM t WHERE a = NULL").forma == "comparacion"
    assert [hijo.forma for hijo in predicado("SELECT * FROM t WHERE a = NULL").hijos] == [
        "columna",
        "nulo",
    ]
    assert predicado("SELECT * FROM t WHERE a IS NULL").forma == "es_nulo"
    assert predicado("SELECT * FROM t WHERE a IS NOT NULL").forma == "no_es_nulo"
    negado = predicado("SELECT * FROM t WHERE NOT (a = 1 AND b = 2 OR c = 3)")
    assert negado.forma == "no"
    assert negado.hijos[0].forma == "o"
    assert negado.hijos[0].hijos[0].forma == "y"
    assert expresion(bloque(_nodo("SELECT NULL")).proyecciones[0]).forma == "nulo"
    assert expresion(bloque(_nodo("SELECT 1")).proyecciones[0]).forma == "literal"
