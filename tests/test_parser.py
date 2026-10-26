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
