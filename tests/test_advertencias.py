from analizador.advertencias import evaluar
from analizador.parser import parsear
from analizador.semantica import componentes


def codigos(sql, dialecto="postgresql"):
    raiz = componentes(parsear(sql, dialecto).sentencias[0].nodo, 1, dialecto)
    return [a.codigo for a in evaluar(raiz, dialecto)]


def avisos(sql, dialecto="postgresql"):
    raiz = componentes(parsear(sql, dialecto).sentencias[0].nodo, 1, dialecto)
    return evaluar(raiz, dialecto)


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


def test_full_join_avisa_una_vez_por_lado():
    sql = "SELECT * FROM a FULL JOIN b ON a.id = b.id WHERE a.x = 1 AND b.y = 2"
    encontrados = [a for a in avisos(sql) if a.codigo == "outer_join_filtrado"]
    assert len(encontrados) == 2
    assert any("con a " in a.mensaje for a in encontrados)
    assert any("con b " in a.mensaje for a in encontrados)


def test_or_de_dos_columnas_anulables_avisa():
    sql = (
        "SELECT * FROM c LEFT JOIN p ON c.id = p.id "
        "WHERE p.estado = 'activo' OR p.tipo = 'vip'"
    )
    assert "outer_join_filtrado" in codigos(sql)


def test_inner_posterior_avisa_y_left_posterior_no():
    interno = (
        "SELECT * FROM c LEFT JOIN p ON c.id = p.id "
        "INNER JOIN x ON p.id = x.id"
    )
    assert "outer_join_filtrado" in codigos(interno)
    izquierdo = (
        "SELECT * FROM c LEFT JOIN p ON c.id = p.id "
        "LEFT JOIN x ON p.id = x.id"
    )
    assert "outer_join_filtrado" not in codigos(izquierdo)


def test_suma_dentro_de_agregado_no_avisa():
    sql = "SELECT SUM(salario) FROM empleados GROUP BY departamento"
    assert "select_fuera_de_group_by" not in codigos(sql)


def test_partition_by_fuera_del_grupo_avisa():
    sql = (
        "SELECT SUM(salario) OVER (PARTITION BY departamento ORDER BY id) "
        "FROM empleados GROUP BY id"
    )
    assert "select_fuera_de_group_by" in codigos(sql)
    assert "select_fuera_de_group_by" not in codigos(sql, "sqlite")


def test_alias_con_from_no_queda_demostrado():
    sql = "SELECT salario + 100 AS total FROM empleados GROUP BY total"
    assert "select_fuera_de_group_by" not in codigos(sql)


def test_alias_sin_from_no_avisa():
    sql = "SELECT salario + 100 AS total GROUP BY total"
    assert "select_fuera_de_group_by" not in codigos(sql)


def test_la_otra_tabla_del_grupo_si_avisa():
    sql = "SELECT a.id, b.id FROM a, b GROUP BY a.id"
    encontrados = [a for a in avisos(sql) if a.codigo == "select_fuera_de_group_by"]
    assert len(encontrados) == 1
    assert "b.id" in encontrados[0].fragmento


def test_mensajes_citan_el_fragmento_normalizado():
    sql = "SELECT * FROM c LEFT JOIN p ON c.id = p.id WHERE p.estado = 'A'"
    aviso = next(a for a in avisos(sql) if a.codigo == "outer_join_filtrado")
    assert aviso.gravedad == "aviso"
    assert aviso.fragmento == "p.estado = 'A'"
    assert aviso.mensaje == (
        "El LEFT JOIN con p deja sus columnas a NULL cuando no hay coincidencia. "
        "El filtro posterior `p.estado = 'A'` descarta esos NULL, así que las filas "
        "sin coincidencia pueden desaparecer."
    )

    nulo = next(a for a in avisos("SELECT * FROM t WHERE a != NULL") if a.codigo == "comparacion_con_null")
    assert nulo.fragmento == "a <> NULL"
    assert nulo.mensaje == (
        "La comparación `a <> NULL` usa <> con NULL. Con este operador el resultado "
        "es desconocido, así que el filtro no selecciona esas filas. Para comprobar "
        "NULL usa IS NULL o IS NOT NULL."
    )

    estrella = next(a for a in avisos("SELECT * FROM empleados") if a.codigo == "select_asterisco")
    assert estrella.mensaje == "`*` recupera todas las columnas de las tablas de esta consulta."
    calificada = next(
        a for a in avisos("SELECT e.* FROM empleados AS e") if a.codigo == "select_asterisco"
    )
    assert calificada.fragmento == "e.*"
    assert calificada.mensaje == "`e.*` recupera todas las columnas de empleados."

    grupo = next(
        a
        for a in avisos("SELECT salario FROM empleados GROUP BY departamento")
        if a.codigo == "select_fuera_de_group_by"
    )
    assert grupo.fragmento == "salario"
    assert grupo.mensaje == (
        "`salario` está en el SELECT, no está en el GROUP BY y no está dentro de "
        "una función de agregación. Según el dialecto, el motor puede rechazar la "
        "consulta o devolver un valor cualquiera del grupo."
    )


def test_is_distinct_y_null_safe_no_avisan():
    assert "comparacion_con_null" not in codigos("SELECT * FROM t WHERE a IS DISTINCT FROM NULL")
    assert "comparacion_con_null" not in codigos("SELECT * FROM t WHERE a <=> NULL", "mysql")


def test_el_with_de_union_no_repite_el_aviso():
    sql = (
        "WITH activos AS (SELECT id FROM empleados WHERE id = NULL) "
        "SELECT id FROM activos UNION ALL SELECT id FROM antiguos WHERE id = NULL"
    )
    assert codigos(sql).count("comparacion_con_null") == 2


def test_right_join_posterior_incluye_la_entrada_izquierda():
    sql = (
        "SELECT * FROM a JOIN b ON a.id = b.id "
        "RIGHT JOIN c ON b.id = c.id WHERE a.x = 1"
    )
    assert "outer_join_filtrado" in codigos(sql)


def test_full_join_posterior_incluye_la_entrada_izquierda():
    sql = (
        "SELECT * FROM a JOIN b ON a.id = b.id "
        "FULL JOIN c ON b.id = c.id WHERE a.x = 1"
    )
    assert "outer_join_filtrado" in codigos(sql)


def test_columna_exterior_en_subconsulta_avisa():
    sql = "SELECT (SELECT e.id) FROM empleados AS e GROUP BY e.departamento"
    assert "select_fuera_de_group_by" in codigos(sql)
    assert "select_fuera_de_group_by" not in codigos(sql, "sqlite")


def test_columna_de_la_subconsulta_no_avisa():
    sql = "SELECT (SELECT id FROM otros) FROM empleados GROUP BY departamento"
    assert "select_fuera_de_group_by" not in codigos(sql)


def test_la_coma_no_entra_en_el_right_join():
    base = "SELECT * FROM a, b RIGHT JOIN c ON b.id = c.id "
    assert "outer_join_filtrado" not in codigos(base + "WHERE a.x = 1")
    assert "outer_join_filtrado" in codigos(base + "WHERE b.x = 1")
    assert "outer_join_filtrado" not in codigos(base + "WHERE c.x = 1")


def test_cross_join_si_entra_en_el_right_join():
    sql = "SELECT * FROM a CROSS JOIN b RIGHT JOIN c ON b.id = c.id WHERE a.x = 1"
    assert "outer_join_filtrado" in codigos(sql)


def test_filtro_de_agregado_fuera_del_grupo():
    sql = "SELECT SUM(salario) FILTER (WHERE departamento = 1) FROM empleados GROUP BY id"
    assert "select_fuera_de_group_by" in codigos(sql)
    assert "select_fuera_de_group_by" not in codigos(sql, "sqlite")


def test_order_by_de_agregado_fuera_del_grupo():
    sql = "SELECT array_agg(id ORDER BY salario) FROM empleados GROUP BY id"
    assert "select_fuera_de_group_by" in codigos(sql)
    assert "select_fuera_de_group_by" not in codigos(sql, "sqlite")


def test_el_nombre_base_aliasado_no_es_el_lado_anulable():
    base = "SELECT * FROM a LEFT JOIN a AS a2 ON a.id = a2.id "
    assert "outer_join_filtrado" not in codigos(base + "WHERE a.x = 1")
    assert "outer_join_filtrado" in codigos(base + "WHERE a2.x = 1")
    pedidos = "SELECT * FROM pedidos AS p LEFT JOIN clientes AS c ON p.id = c.id "
    assert "outer_join_filtrado" not in codigos(pedidos + "WHERE clientes.estado = 'A'")
    assert "outer_join_filtrado" in codigos(pedidos + "WHERE c.estado = 'A'")


def test_dos_alias_de_la_misma_relacion_no_son_el_mismo_origen():
    sql = "SELECT a2.id FROM a AS a1 JOIN a AS a2 ON a1.id = a2.id GROUP BY a1.id"
    assert "select_fuera_de_group_by" in codigos(sql)
    assert "select_fuera_de_group_by" not in codigos(sql, "sqlite")


def test_el_nombre_base_y_el_alias_unico_son_el_mismo_origen():
    sql = "SELECT e.id FROM empleados AS e GROUP BY empleados.id"
    assert "select_fuera_de_group_by" not in codigos(sql)


def test_la_correlacion_no_se_esconde_tras_el_nombre_base_interno():
    sql = "SELECT (SELECT a.id FROM a AS a1) FROM a GROUP BY a.x"
    assert "select_fuera_de_group_by" in codigos(sql)
    assert "select_fuera_de_group_by" not in codigos(sql, "sqlite")
    propio = "SELECT (SELECT a1.id FROM a AS a1) FROM a GROUP BY a.x"
    assert "select_fuera_de_group_by" not in codigos(propio)


def _fragmentos(sql, codigo, dialecto="postgresql"):
    return [aviso.fragmento for aviso in avisos(sql, dialecto) if aviso.codigo == codigo]


def test_el_ordinal_cubre_solo_esa_expresion():
    sql = "SELECT departamento, salario FROM empleados GROUP BY 1"
    assert _fragmentos(sql, "select_fuera_de_group_by") == ["salario"]
    assert "select_fuera_de_group_by" not in codigos(sql, "sqlite")
    assert "select_fuera_de_group_by" not in codigos(
        "SELECT departamento, salario FROM empleados GROUP BY 1, 2"
    )


def test_rollup_cubre_lo_nombrado_y_avisa_por_el_resto():
    assert _fragmentos("SELECT a, b FROM t GROUP BY ROLLUP (a)", "select_fuera_de_group_by") == ["b"]
    assert "select_fuera_de_group_by" not in codigos(
        "SELECT departamento, salario FROM empleados GROUP BY ROLLUP (departamento, salario)"
    )


def test_cube_avisa_por_la_columna_no_nombrada():
    sql = "SELECT departamento, salario FROM empleados GROUP BY CUBE (departamento)"
    assert _fragmentos(sql, "select_fuera_de_group_by") == ["salario"]


def test_grouping_sets_cubre_las_columnas_nombradas():
    parcial = "SELECT departamento, salario FROM empleados GROUP BY GROUPING SETS ((departamento))"
    assert _fragmentos(parcial, "select_fuera_de_group_by") == ["salario"]
    completo = (
        "SELECT departamento, salario FROM empleados "
        "GROUP BY GROUPING SETS ((departamento), (salario))"
    )
    assert "select_fuera_de_group_by" not in codigos(completo)


def test_ordinal_dentro_de_rollup_cube_y_grouping_sets():
    consultas = (
        "SELECT departamento, salario FROM empleados GROUP BY ROLLUP (1)",
        "SELECT departamento, salario FROM empleados GROUP BY CUBE (1)",
        "SELECT departamento, salario FROM empleados GROUP BY GROUPING SETS ((1))",
    )
    for sql in consultas:
        assert _fragmentos(sql, "select_fuera_de_group_by") == ["salario"]
    assert "select_fuera_de_group_by" not in codigos(consultas[0], "sqlite")


def test_el_constructor_de_fila_no_se_abre():
    consultas = (
        "SELECT departamento, salario FROM empleados GROUP BY (departamento, salario)",
        "SELECT departamento, salario FROM empleados GROUP BY (1, 2)",
        "SELECT departamento, salario FROM empleados GROUP BY ROLLUP ((departamento, salario))",
        "SELECT departamento, salario FROM empleados GROUP BY CUBE ((1, 2))",
    )
    for sql in consultas:
        assert _fragmentos(sql, "select_fuera_de_group_by") == ["departamento", "salario"]
    assert "select_fuera_de_group_by" not in codigos(consultas[0], "sqlite")
    assert _fragmentos(
        "SELECT salario FROM empleados GROUP BY (salario + 100)",
        "select_fuera_de_group_by",
    ) == ["salario"]
    assert "select_fuera_de_group_by" not in codigos(
        "SELECT salario + 100 FROM empleados GROUP BY (salario + 100)"
    )


def test_grouping_sets_abre_la_tupla():
    columnas = (
        "SELECT departamento, salario FROM empleados "
        "GROUP BY GROUPING SETS ((departamento, salario))"
    )
    assert "select_fuera_de_group_by" not in codigos(columnas)
    ordinales = "SELECT departamento, salario FROM empleados GROUP BY GROUPING SETS ((1, 2))"
    assert "select_fuera_de_group_by" not in codigos(ordinales)
    assert "select_fuera_de_group_by" not in codigos(
        "SELECT departamento, salario FROM empleados GROUP BY departamento, salario"
    )
    assert _fragmentos(
        "SELECT departamento, salario FROM empleados GROUP BY GROUPING SETS ((departamento))",
        "select_fuera_de_group_by",
    ) == ["salario"]


def test_la_expresion_repetida_dentro_de_rollup_no_avisa():
    consultas = (
        "SELECT salario + 100 FROM empleados GROUP BY ROLLUP (salario + 100)",
        "SELECT salario + 100 FROM empleados GROUP BY CUBE (salario + 100)",
        "SELECT salario + 100 FROM empleados GROUP BY GROUPING SETS ((salario + 100))",
    )
    for sql in consultas:
        assert "select_fuera_de_group_by" not in codigos(sql)
    assert "select_fuera_de_group_by" not in codigos(
        "SELECT salario + 100 FROM empleados GROUP BY salario + 100"
    )
    assert _fragmentos(
        "SELECT salario FROM empleados GROUP BY ROLLUP (salario + 100)",
        "select_fuera_de_group_by",
    ) == ["salario"]


def test_expresion_dentro_de_rollup_no_cubre_la_columna():
    consultas = (
        "SELECT salario FROM empleados GROUP BY ROLLUP (salario + 100)",
        "SELECT salario FROM empleados GROUP BY CUBE (salario + 100)",
        "SELECT salario FROM empleados GROUP BY GROUPING SETS ((salario + 100))",
    )
    for sql in consultas:
        assert _fragmentos(sql, "select_fuera_de_group_by") == ["salario"]


def test_group_by_plano_avisa_por_salario():
    sql = "SELECT departamento, salario FROM empleados GROUP BY departamento"
    assert _fragmentos(sql, "select_fuera_de_group_by") == ["salario"]
    assert "select_fuera_de_group_by" not in codigos(sql, "sqlite")


def test_columna_sin_cubrir_sigue_avisando_y_el_agregado_no():
    assert "select_fuera_de_group_by" in codigos(
        "SELECT departamento, salario, extra FROM empleados GROUP BY departamento, salario"
    )
    assert "select_fuera_de_group_by" not in codigos(
        "SELECT departamento, SUM(salario) FROM empleados GROUP BY departamento"
    )


def test_having_y_on_avisan_sin_copiar_secretos():
    having = "SELECT id FROM t GROUP BY id HAVING id IN (SELECT id FROM secretos WHERE x = NULL)"
    raiz = componentes(parsear(having, "postgresql").sentencias[0].nodo, 1, "postgresql")
    assert [tabla.nombre for tabla in raiz.tablas] == ["t"]
    assert any(tabla.nombre == "secretos" for hijo in raiz.hijos for tabla in hijo.tablas)
    assert "comparacion_con_null" in codigos(having)
    unido = "SELECT * FROM a JOIN b ON a.id = (SELECT id FROM secretos WHERE x = NULL)"
    raiz = componentes(parsear(unido, "postgresql").sentencias[0].nodo, 1, "postgresql")
    assert "secretos" not in [tabla.nombre for tabla in raiz.tablas]
    assert any(tabla.nombre == "secretos" for hijo in raiz.hijos for tabla in hijo.tablas)
    assert "comparacion_con_null" in codigos(unido)
