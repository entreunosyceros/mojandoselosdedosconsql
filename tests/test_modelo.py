from analizador.dialectos import nombre_interno
from analizador.errores import DialectoNoSoportado, ErrorAnalizador, ErrorDeFase
from analizador.mensajes import (
    FALLO_ADVERTENCIAS,
    FALTA_DIALECTO,
    consulta_demasiado_grande,
    fallo_fase,
    fallo_informe,
)
from analizador.modelo import (
    Columna,
    Componente,
    Informe,
    Sentencia,
    Tabla,
)


def test_nombre_interno_de_sql_server():
    assert nombre_interno("sqlserver") == "tsql"


def test_nombres_internos_de_los_cuatro_dialectos():
    assert nombre_interno("postgresql") == "postgres"
    assert nombre_interno("mysql") == "mysql"
    assert nombre_interno("sqlite") == "sqlite"
    assert nombre_interno("sqlserver") == "tsql"


def test_dialecto_desconocido():
    try:
        nombre_interno("excel")
    except DialectoNoSoportado as error:
        assert str(error) == 'El dialecto «excel» no está soportado. Elige PostgreSQL, MySQL, SQLite o SQL Server.'
        assert isinstance(error, ErrorAnalizador)
    else:
        raise AssertionError("debía fallar")


def test_error_de_fase_conserva_la_causa():
    causa = RuntimeError("fallo de prueba")
    error = ErrorDeFase("formatear", 1, "Select", causa)
    assert error.fase == "formatear"
    assert error.indice == 1
    assert error.tipo == "Select"
    assert error.causa is causa
    assert str(error) == "fallo de prueba"
    assert isinstance(error, ErrorAnalizador)


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


def test_componente_a_dict_omite_lo_privado_y_serializa_tuplas():
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
    componente = Componente(
        id="s1.c1",
        clase="consulta",
        nombre=None,
        tipo="Select",
        tablas=(Tabla(nombre="empleados", alias="e", papel="lectura", explicacion=None),),
        columnas=(columna,),
        clausulas=(),
        relaciones=(),
        pasos=("Toma las filas de empleados.",),
        hijos=(),
        explicacion=None,
        _nodo=object(),
    )
    datos = componente.a_dict()
    assert "_nodo" not in datos
    assert all(not clave.startswith("_") for clave in datos)
    assert datos["tablas"] == [
        {"nombre": "empleados", "alias": "e", "papel": "lectura", "explicacion": None}
    ]
    assert datos["columnas"][0]["tabla"] is None
    assert datos["pasos"] == ["Toma las filas de empleados."]
    assert datos["hijos"] == []
    assert datos["explicacion"] is None


def test_sentencia_admite_formato_y_arbol_nulos():
    sentencia = Sentencia(
        indice=1,
        tipo="Select",
        sql_formateado=None,
        resumen=None,
        pasos=(),
        arbol=None,
        advertencias=(),
    )
    informe = Informe(
        dialecto="postgresql",
        sql_original="SELECT 1",
        sentencias=(sentencia,),
        errores=(),
    )
    datos = informe.a_dict()["sentencias"][0]
    assert datos["sql_formateado"] is None
    assert datos["arbol"] is None
    assert datos["pasos"] == []
    assert datos["advertencias"] == []


def test_mensajes_de_fase_y_tamano():
    assert consulta_demasiado_grande(1048577) == (
        "La consulta ocupa 1048577 bytes y el límite es 1 MB (1048576 bytes)."
    )
    assert fallo_fase("formatear", 1, "Select") == (
        "No se ha podido formatear la sentencia 1 (Select). "
        "El detalle técnico quedó en el registro del servidor."
    )
    assert fallo_fase("recorrer", 2, "Update") == (
        "No se ha podido recorrer la sentencia 2 (Update). "
        "El detalle técnico quedó en el registro del servidor."
    )
    assert fallo_fase("explicar", 3, "Delete") == (
        "No se ha podido explicar la sentencia 3 (Delete). "
        "El detalle técnico quedó en el registro del servidor."
    )
    assert fallo_informe("el parseo") == (
        "No se ha podido construir el informe durante el parseo. "
        "El detalle técnico quedó en el registro del servidor."
    )
    assert FALLO_ADVERTENCIAS.format(indice=2, tipo="Update") == (
        "No se han podido evaluar las advertencias de la sentencia 2 (Update). "
        "El detalle técnico quedó en el registro del servidor."
    )
