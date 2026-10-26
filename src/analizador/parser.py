from __future__ import annotations

import re
from dataclasses import dataclass, field

import sqlglot
from sqlglot.errors import ParseError, TokenError
from sqlglot.tokens import TokenType

from analizador.dialectos import nombre_interno
from analizador.mensajes import SIN_SENTENCIA, SOLO_COMENTARIOS
from analizador.modelo import Error

_ESPERADO = re.compile(
    r"^(?:Expecting|Expected)\s+(?P<esperado>.+?)(?:\s+but got\s+(?P<encontrado>.+))?$"
)
_TEXTO_TOKEN = re.compile(r"text:\s*(.*?),\s*line:")
_POSICION_EN_CAUSA = re.compile(r" from \d+:\d+$")
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_LINEA_EN_TEXTO = re.compile(r"Line\s+(\d+),\s*Col:\s*(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class Nodo:
    _expression: object = field(compare=False, hash=False, repr=False)


@dataclass(frozen=True)
class SentenciaSintactica:
    indice: int
    tipo: str
    nodo: Nodo


@dataclass(frozen=True)
class ResultadoParseo:
    sentencias: tuple[SentenciaSintactica, ...]
    errores: tuple[Error, ...]


def parsear(sql: str, dialecto: str) -> ResultadoParseo:
    interno = nombre_interno(dialecto)
    try:
        expresiones = sqlglot.parse(sql, read=interno)
    except ParseError as error:
        return ResultadoParseo((), tuple(_errores_de_parseo(error, sql, interno)))
    except TokenError as error:
        return ResultadoParseo((), (_error_de_token(error, sql, interno),))

    sentencias: list[SentenciaSintactica] = []
    indice = 1
    for expresion in expresiones:
        if expresion is None:
            continue
        sentencias.append(
            SentenciaSintactica(indice, type(expresion).__name__, Nodo(expresion))
        )
        indice += 1

    if sentencias:
        return ResultadoParseo(tuple(sentencias), ())
    if _solo_comentarios_o_espacios(sql, interno):
        return ResultadoParseo((), (_error(SOLO_COMENTARIOS),))
    if sql.strip():
        return ResultadoParseo((), (_error(SIN_SENTENCIA),))
    return ResultadoParseo((), ())


def _errores_de_parseo(error: ParseError, sql: str, interno: str) -> list[Error]:
    if not error.errors:
        return [_error_de_parseo_sin_detalle(error)]
    return [_traducir_parseo(detalle, sql, interno) for detalle in error.errors]


def _error_de_parseo_sin_detalle(error: ParseError) -> Error:
    texto = str(error)
    if _ANSI.search(texto):
        texto = _ANSI.sub("", texto)
    linea, columna, descripcion = _posicion_en_texto(texto)
    return _error(_mensaje_generico(linea, columna, descripcion), linea, columna)


def _posicion_en_texto(texto: str) -> tuple[int | None, int | None, str]:
    coincidencia = _LINEA_EN_TEXTO.search(texto)
    if coincidencia is None:
        return None, None, texto.strip()
    descripcion = texto[: coincidencia.start()].strip()
    if descripcion.endswith("."):
        descripcion = descripcion[:-1].rstrip()
    return int(coincidencia.group(1)), int(coincidencia.group(2)), descripcion


def _traducir_parseo(detalle: dict[str, object], sql: str, interno: str) -> Error:
    descripcion = str(detalle.get("description") or "")
    linea = _entero(detalle.get("line"))
    columna = _entero(detalle.get("col"))
    partes = _partes_esperado(descripcion)
    if partes is None:
        return _error(_mensaje_generico(linea, columna, descripcion), linea, columna)

    esperado, encontrado = partes
    parentesis = (
        _parentesis_abierto(sql, interno, linea, columna) if esperado == ")" else None
    )
    if parentesis is not None:
        linea_parentesis, columna_parentesis = parentesis
        return _error(
            (
                f"El paréntesis abierto en la línea {linea_parentesis}, "
                f"columna {columna_parentesis} no se cierra."
            ),
            linea_parentesis,
            columna_parentesis,
        )

    if linea is None or columna is None:
        return _error(_mensaje_generico(linea, columna, descripcion), linea, columna)

    if _al_final(encontrado, detalle.get("end_context")):
        return _error(
            (
                f"La sentencia termina en la línea {linea}, columna {columna}, "
                f"y ahí se esperaba `{esperado}`."
            ),
            linea,
            columna,
        )

    aparecio = encontrado if encontrado is not None else str(detalle.get("highlight") or "")
    return _error(
        (
            f"En la línea {linea}, columna {columna}, "
            f"se esperaba `{esperado}` y apareció `{aparecio}`."
        ),
        linea,
        columna,
    )


def _error_de_token(error: TokenError, sql: str, interno: str) -> Error:
    # TokenError.start es el recorte del mensaje y en la 30.25.0 puede ser 0.
    abierto = _delimitador_abierto(sql, interno)
    if abierto is None:
        return _error(_mensaje_generico(None, None, _descripcion_token(error)))

    clase, linea, columna, delimitador = abierto
    if clase == "comentario":
        mensaje = f"El comentario abierto en la línea {linea}, columna {columna} no se cierra."
    elif clase == "comilla":
        mensaje = f"La comilla abierta en la línea {linea}, columna {columna} no se cierra."
    elif clase == "identificador":
        mensaje = (
            f"El identificador abierto con `{delimitador}` en la línea {linea}, "
            f"columna {columna} no se cierra."
        )
    else:
        mensaje = _mensaje_generico(linea, columna, _descripcion_token(error))
    return _error(mensaje, linea, columna)


def _error(mensaje: str, linea: int | None = None, columna: int | None = None) -> Error:
    return Error(mensaje=mensaje, linea=linea, columna=columna, sentencia=None)


def _mensaje_generico(linea: int | None, columna: int | None, descripcion: str) -> str:
    if linea is not None and columna is not None:
        lugar = f"en la línea {linea}, columna {columna}"
    elif linea is not None:
        lugar = f"en la línea {linea}"
    elif columna is not None:
        lugar = f"en la columna {columna}"
    else:
        lugar = ""
    if lugar:
        return f"SQLGlot no interpreta la sentencia {lugar}: {descripcion}."
    return f"SQLGlot no interpreta la sentencia: {descripcion}."


def _partes_esperado(descripcion: str) -> tuple[str, str | None] | None:
    coincidencia = _ESPERADO.match(descripcion.strip())
    if coincidencia is None:
        return None
    esperado = coincidencia.group("esperado").strip().rstrip(".")
    encontrado = coincidencia.group("encontrado")
    if encontrado is None:
        return esperado, None
    return esperado, _texto_de_token(encontrado.strip())


def _texto_de_token(encontrado: str) -> str:
    coincidencia = _TEXTO_TOKEN.search(encontrado)
    if coincidencia is None:
        return encontrado
    return coincidencia.group(1).strip()


def _al_final(encontrado: str | None, end_context: object) -> bool:
    if encontrado == "SENTINEL":
        return True
    if encontrado is not None:
        return False
    return not str(end_context or "").strip()


def _descripcion_token(error: TokenError) -> str:
    causa = error.__cause__
    if isinstance(causa, TokenError):
        return _POSICION_EN_CAUSA.sub("", str(causa))
    return "No se ha podido tokenizar la consulta."


def _entero(valor: object) -> int | None:
    if isinstance(valor, int):
        return valor
    return None


def _solo_comentarios_o_espacios(sql: str, interno: str) -> bool:
    tokenizador = sqlglot.Dialect.get_or_raise(interno).tokenizer()
    try:
        tokens = tokenizador.tokenize(sql)
    except TokenError:
        return False
    if tokens:
        return False
    if tokenizador._core._comments:
        return True
    return bool(sql) and not sql.strip()


def _parentesis_abierto(
    sql: str, interno: str, linea: int | None, columna: int | None
) -> tuple[int, int] | None:
    pila: list[tuple[int, int]] = []
    for token in sqlglot.tokenize(sql, read=interno):
        if linea is not None and columna is not None and (token.line, token.col) > (linea, columna):
            break
        if token.token_type == TokenType.L_PAREN:
            pila.append((token.line, token.col))
        elif token.token_type == TokenType.R_PAREN and pila:
            pila.pop()
    if not pila:
        return None
    return pila[-1]


def _delimitador_abierto(sql: str, interno: str) -> tuple[str, int, int, str] | None:
    clase = sqlglot.Dialect.get_or_raise(interno).tokenizer_class
    identificadores = sorted(clase._IDENTIFIERS, key=len, reverse=True)
    comentarios = sorted(clase._COMMENTS, key=len, reverse=True)
    comillas = sorted(clase._QUOTES, key=len, reverse=True)
    prefijos = _cadenas_con_prefijo(clase)
    indice = 0
    linea = 1
    columna = 1
    tamano = len(sql)

    while indice < tamano:
        identificador = _coincide(sql, indice, identificadores)
        if identificador is not None:
            apertura = (linea, columna)
            indice, linea, columna = _avanzar(sql, indice, linea, columna, len(identificador))
            cierre = clase._IDENTIFIERS[identificador]
            cerrado, indice, linea, columna = _consumir(
                sql, indice, linea, columna, cierre, clase._IDENTIFIER_ESCAPES | {cierre}
            )
            if not cerrado:
                return ("identificador", apertura[0], apertura[1], identificador)
            continue

        comentario = _coincide(sql, indice, comentarios)
        if comentario == "--" and clase.DASH_COMMENT_REQUIRES_BOUNDARY and not _tras_raya(sql, indice):
            comentario = None
        if comentario is not None:
            apertura = (linea, columna)
            fin = clase._COMMENTS[comentario]
            indice, linea, columna = _avanzar(sql, indice, linea, columna, len(comentario))
            if fin is None:
                indice, linea, columna = _saltar_comentario_de_linea(
                    sql, indice, linea, columna, clase.COMMENTS_TERMINATE_AT_NEWLINE_ONLY
                )
                continue
            cerrado, indice, linea, columna = _saltar_comentario_de_bloque(
                sql, indice, linea, columna, comentario, fin, clase.NESTED_COMMENTS
            )
            if not cerrado:
                return ("comentario", apertura[0], apertura[1], comentario)
            continue

        prefijo = _prefijo_en(sql, indice, prefijos) if _puede_abrir_prefijo(sql, indice) else None
        if prefijo is not None:
            inicio, cierre, escapes = prefijo
            antes = len(inicio) - len(cierre)
            indice, linea, columna = _avanzar(sql, indice, linea, columna, antes)
            apertura = (linea, columna)
            indice, linea, columna = _avanzar(sql, indice, linea, columna, len(cierre))
            cerrado, indice, linea, columna = _consumir(sql, indice, linea, columna, cierre, escapes)
            if not cerrado:
                return ("comilla", apertura[0], apertura[1], cierre)
            continue

        comilla = _coincide(sql, indice, comillas)
        if comilla is not None:
            apertura = (linea, columna)
            indice, linea, columna = _avanzar(sql, indice, linea, columna, len(comilla))
            cerrado, indice, linea, columna = _consumir(
                sql, indice, linea, columna, clase._QUOTES[comilla], clase._STRING_ESCAPES
            )
            if not cerrado:
                return ("comilla", apertura[0], apertura[1], comilla)
            continue

        if clase.HEREDOC_STRINGS and sql[indice] == "$":
            heredoc = _saltar_heredoc(sql, indice, linea, columna)
            if heredoc is not None:
                cerrado, indice, linea, columna, apertura = heredoc
                if not cerrado:
                    return ("dolar", apertura[0], apertura[1], "")
                continue

        indice, linea, columna = _avanzar(sql, indice, linea, columna, 1)

    return None


def _cadenas_con_prefijo(clase: type) -> list[tuple[str, str, set[str]]]:
    cadenas: list[tuple[str, str, set[str]]] = []
    for inicio, (cierre, tipo) in clase._FORMAT_STRINGS.items():
        if not cierre or tipo == TokenType.HEREDOC_STRING:
            continue
        if tipo == TokenType.BYTE_STRING:
            escapes = set(clase._BYTE_STRING_ESCAPES)
        elif (
            tipo in (TokenType.RAW_STRING, TokenType.NATIONAL_RAW_STRING)
            and not clase.STRING_ESCAPES_ALLOWED_IN_RAW_STRINGS
        ):
            escapes = set()
        else:
            escapes = set(clase._STRING_ESCAPES)
        cadenas.append((inicio, cierre, escapes))
    cadenas.sort(key=lambda cadena: len(cadena[0]), reverse=True)
    return cadenas


def _puede_abrir_prefijo(sql: str, indice: int) -> bool:
    if indice == 0:
        return True
    anterior = sql[indice - 1]
    return not (anterior.isalnum() or anterior == "_")


def _prefijo_en(
    sql: str, indice: int, prefijos: list[tuple[str, str, set[str]]]
) -> tuple[str, str, set[str]] | None:
    for inicio, cierre, escapes in prefijos:
        if sql.startswith(inicio, indice):
            return inicio, cierre, escapes
    return None


def _coincide(sql: str, indice: int, opciones: list[str]) -> str | None:
    for opcion in opciones:
        if sql.startswith(opcion, indice):
            return opcion
    return None


def _tras_raya(sql: str, indice: int) -> bool:
    siguiente = indice + 2
    if siguiente >= len(sql):
        return True
    caracter = sql[siguiente]
    return caracter.isspace() or ord(caracter) < 32 or ord(caracter) == 127


def _consumir(
    sql: str,
    indice: int,
    linea: int,
    columna: int,
    cierre: str,
    escapes: set[str],
) -> tuple[bool, int, int, int]:
    tamano = len(cierre)
    while indice < len(sql):
        # Una comilla solo escapa cuando es el cierre y está duplicada.
        # La barra invertida, si el dialecto la usa, consume el carácter siguiente.
        if "\\" in escapes and sql[indice] == "\\" and indice + 1 < len(sql):
            indice, linea, columna = _avanzar(sql, indice, linea, columna, 2)
            continue
        if sql.startswith(cierre, indice):
            if cierre in escapes and sql.startswith(cierre + cierre, indice):
                indice, linea, columna = _avanzar(sql, indice, linea, columna, tamano * 2)
                continue
            indice, linea, columna = _avanzar(sql, indice, linea, columna, tamano)
            return True, indice, linea, columna
        indice, linea, columna = _avanzar(sql, indice, linea, columna, 1)
    return False, indice, linea, columna


def _saltar_comentario_de_linea(
    sql: str,
    indice: int,
    linea: int,
    columna: int,
    solo_salto_de_linea: bool,
) -> tuple[int, int, int]:
    while indice < len(sql):
        caracter = sql[indice]
        if caracter == "\n" or (caracter == "\r" and not solo_salto_de_linea):
            break
        indice, linea, columna = _avanzar(sql, indice, linea, columna, 1)
    return indice, linea, columna


def _saltar_comentario_de_bloque(
    sql: str,
    indice: int,
    linea: int,
    columna: int,
    apertura: str,
    cierre: str,
    anidados: bool,
) -> tuple[bool, int, int, int]:
    profundidad = 1
    while indice < len(sql) and profundidad:
        if anidados and sql.startswith(apertura, indice):
            profundidad += 1
            indice, linea, columna = _avanzar(sql, indice, linea, columna, len(apertura))
            continue
        if sql.startswith(cierre, indice):
            profundidad -= 1
            indice, linea, columna = _avanzar(sql, indice, linea, columna, len(cierre))
            continue
        indice, linea, columna = _avanzar(sql, indice, linea, columna, 1)
    return profundidad == 0, indice, linea, columna


def _saltar_heredoc(
    sql: str, indice: int, linea: int, columna: int
) -> tuple[bool, int, int, int, tuple[int, int]] | None:
    if indice + 1 >= len(sql):
        return None
    apertura = (linea, columna)
    if sql[indice + 1] == "$":
        cierre = "$$"
        inicio_contenido = indice + 2
    else:
        cursor = indice + 1
        while cursor < len(sql) and (sql[cursor].isalnum() or sql[cursor] == "_"):
            cursor += 1
        if cursor == indice + 1 or cursor >= len(sql) or sql[cursor] != "$":
            return None
        if sql[indice + 1 : cursor].isdigit():
            return None
        cierre = sql[indice : cursor + 1]
        inicio_contenido = cursor + 1

    indice, linea, columna = _avanzar(sql, indice, linea, columna, inicio_contenido - indice)
    encontrado = sql.find(cierre, indice)
    if encontrado < 0:
        return False, indice, linea, columna, apertura
    indice, linea, columna = _avanzar(sql, indice, linea, columna, encontrado - indice + len(cierre))
    return True, indice, linea, columna, apertura


def _avanzar(
    sql: str, indice: int, linea: int, columna: int, cantidad: int
) -> tuple[int, int, int]:
    restantes = cantidad
    while restantes > 0 and indice < len(sql):
        caracter = sql[indice]
        indice += 1
        restantes -= 1
        if caracter == "\n" or (caracter == "\r" and (indice >= len(sql) or sql[indice] != "\n")):
            linea += 1
            columna = 1
        else:
            columna += 1
    return indice, linea, columna
