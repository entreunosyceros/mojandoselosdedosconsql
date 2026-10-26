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
