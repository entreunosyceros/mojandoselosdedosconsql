from __future__ import annotations

import logging

from analizador.advertencias import evaluar
from analizador.dialectos import nombre_interno
from analizador.errores import ErrorDeFase
from analizador.explicacion import pasos_sentencia, rellenar, resumen
from analizador.formato import formatear
from analizador.mensajes import CONSULTA_VACIA, FALLO_ADVERTENCIAS, fallo_fase
from analizador.modelo import Error, Informe, Sentencia
from analizador.parser import parsear
from analizador.semantica import componentes

logger = logging.getLogger("analizador.api")


def analizar(sql: str, dialecto: str) -> Informe:
    nombre_interno(dialecto)
    if not sql.strip():
        return Informe(
            dialecto=dialecto,
            sql_original=sql,
            sentencias=(),
            errores=(
                Error(mensaje=CONSULTA_VACIA, linea=None, columna=None, sentencia=None),
            ),
        )

    resultado = parsear(sql, dialecto)
    if resultado.errores:
        return Informe(
            dialecto=dialecto,
            sql_original=sql,
            sentencias=(),
            errores=resultado.errores,
        )

    sentencias: list[Sentencia] = []
    errores: list[Error] = []
    for sintactica in resultado.sentencias:
        sentencia, error = _construir(sintactica.nodo, sintactica.indice, sintactica.tipo, dialecto)
        sentencias.append(sentencia)
        if error is not None:
            errores.append(error)
    return Informe(
        dialecto=dialecto,
        sql_original=sql,
        sentencias=tuple(sentencias),
        errores=tuple(errores),
    )


def _construir(nodo, indice: int, tipo: str, dialecto: str) -> tuple[Sentencia, Error | None]:
    try:
        sql_formateado = formatear(nodo, dialecto)
    except (ErrorDeFase, Exception):
        return _rota(indice, tipo, "formatear", None, None, None, ())

    try:
        arbol = componentes(nodo, indice)
    except (ErrorDeFase, Exception):
        return _rota(indice, tipo, "recorrer", sql_formateado, None, None, ())

    try:
        explicado = rellenar(arbol)
        texto = resumen(explicado)
        pasos = pasos_sentencia(explicado)
    except (ErrorDeFase, Exception):
        return _rota(indice, tipo, "explicar", sql_formateado, arbol, None, arbol.pasos)

    try:
        advertencias = evaluar(explicado, dialecto)
    except (ErrorDeFase, Exception):
        mensaje = FALLO_ADVERTENCIAS.format(indice=indice, tipo=tipo)
        logger.exception("%s", mensaje)
        return (
            Sentencia(
                indice=indice,
                tipo=tipo,
                sql_formateado=sql_formateado,
                resumen=texto,
                pasos=pasos,
                arbol=explicado,
                advertencias=(),
            ),
            _error(mensaje, indice),
        )

    return (
        Sentencia(
            indice=indice,
            tipo=tipo,
            sql_formateado=sql_formateado,
            resumen=texto,
            pasos=pasos,
            arbol=explicado,
            advertencias=advertencias,
        ),
        None,
    )


def _rota(indice, tipo, verbo, sql_formateado, arbol, texto, pasos):
    mensaje = fallo_fase(verbo, indice, tipo)
    logger.exception("%s", mensaje)
    return (
        Sentencia(
            indice=indice,
            tipo=tipo,
            sql_formateado=sql_formateado,
            resumen=texto,
            pasos=pasos,
            arbol=arbol,
            advertencias=(),
        ),
        _error(mensaje, indice),
    )


def _error(mensaje: str, sentencia: int) -> Error:
    return Error(mensaje=mensaje, linea=None, columna=None, sentencia=sentencia)
