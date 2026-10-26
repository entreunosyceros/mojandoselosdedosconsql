from __future__ import annotations

import re
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
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


@dataclass(frozen=True)
class Cte:
    alias: str
    nodo: Nodo


@dataclass(frozen=True)
class Subconsulta:
    nodo: Nodo
    alias: str | None


@dataclass(frozen=True)
class TablaSintactica:
    nombre: str
    alias: str | None


@dataclass(frozen=True)
class RelacionSintactica:
    tipo: str
    izquierda: Nodo
    derecha: Nodo
    condicion: Nodo | None


@dataclass(frozen=True)
class ClausulaSintactica:
    nombre: str
    nodo: Nodo


@dataclass(frozen=True)
class Bloque:
    tipo: str
    ctes: tuple[Cte, ...]
    ramas: tuple[Nodo, Nodo] | None
    union_all: bool | None
    subconsultas: tuple[Subconsulta, ...]
    tablas: tuple[TablaSintactica, ...]
    relaciones: tuple[RelacionSintactica, ...]
    clausulas: tuple[ClausulaSintactica, ...]
    proyecciones: tuple[Nodo, ...]


@dataclass(frozen=True)
class Expresion:
    forma: str
    nombre: str | None
    calificador: str | None
    hijos: tuple[Expresion, ...]


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


def normalizar(nodo: Nodo, dialecto: str) -> str:
    return nodo._expression.sql(dialect=nombre_interno(dialecto))


def bloque(nodo: Nodo) -> Bloque:
    arbol, heredadas = _entrada(nodo._expression)
    clausulas = heredadas + _clausulas(arbol)
    if isinstance(arbol, exp.SetOperation):
        # SQLGlot guarda UNION ALL con distinct=False. Ese booleano no es una cláusula DISTINCT.
        return Bloque(
            type(arbol).__name__,
            _ctes(arbol),
            (Nodo(arbol.this), Nodo(arbol.expression)),
            arbol.args.get("distinct") is False,
            (),
            (),
            (),
            clausulas,
            (),
        )

    tablas: list[TablaSintactica] = []
    relaciones: list[RelacionSintactica] = []
    subconsultas: list[Subconsulta] = []
    proyecciones: list[Nodo] = []
    if isinstance(arbol, exp.Select):
        tablas, relaciones, de_origen = _origenes(arbol)
        subconsultas.extend(de_origen)
        for proyeccion in arbol.expressions:
            proyecciones.append(Nodo(proyeccion))
            subconsultas.extend(_subconsultas_directas(proyeccion))
    elif isinstance(arbol, exp.Insert):
        tabla = _tabla_de(arbol.this)
        if tabla is not None:
            tablas.append(tabla)
        origen = arbol.args.get("expression")
        if isinstance(origen, exp.Expression):
            origen_consulta = _subconsulta_de_origen(origen)
            if origen_consulta is not None:
                subconsultas.append(origen_consulta)
    else:
        tablas.extend(_tablas_de_objeto(arbol))
        if isinstance(arbol, exp.Create):
            proyecciones.extend(Nodo(columna) for columna in _columnas_definidas(arbol))

    where = arbol.args.get("where")
    if isinstance(where, exp.Where) and isinstance(where.this, exp.Expression):
        subconsultas.extend(_subconsultas_directas(where.this))

    return Bloque(
        type(arbol).__name__,
        _ctes(arbol),
        None,
        None,
        tuple(subconsultas),
        tuple(tablas),
        tuple(relaciones),
        clausulas,
        tuple(proyecciones),
    )


def expresion(nodo: Nodo) -> Expresion:
    return _clasificar(nodo._expression)


def _entrada(arbol: object) -> tuple[exp.Expression, tuple[ClausulaSintactica, ...]]:
    if not isinstance(arbol, exp.Expression):
        raise TypeError("El nodo no contiene una expresión SQL.")
    heredadas: list[ClausulaSintactica] = []
    while isinstance(arbol, (exp.Subquery, exp.Lateral)) and isinstance(arbol.this, exp.Expression):
        if _tiene_modificadores(arbol):
            heredadas.extend(_clausulas(arbol))
        arbol = arbol.this
    return arbol, tuple(heredadas)


def _ctes(arbol: exp.Expression) -> tuple[Cte, ...]:
    clausula = arbol.args.get("with_")
    if not isinstance(clausula, exp.With):
        return ()
    return tuple(
        Cte(cte.alias if isinstance(cte.alias, str) else "", Nodo(cte.this))
        for cte in clausula.expressions
    )


def _origenes(
    select: exp.Select,
) -> tuple[list[TablaSintactica], list[RelacionSintactica], list[Subconsulta]]:
    tablas: list[TablaSintactica] = []
    relaciones: list[RelacionSintactica] = []
    subconsultas: list[Subconsulta] = []
    from_ = select.args.get("from_")
    joins = [join for join in (select.args.get("joins") or []) if isinstance(join, exp.Join)]
    fuentes: list[exp.Expression] = []
    if isinstance(from_, exp.From) and isinstance(from_.this, exp.Expression):
        fuentes.append(from_.this)
    fuentes.extend(join.this for join in joins if isinstance(join.this, exp.Expression))
    for fuente in fuentes:
        if isinstance(fuente, exp.Table):
            tabla = _tabla_de(fuente)
            if tabla is not None:
                tablas.append(tabla)
            continue
        consulta = _subconsulta_de_origen(fuente)
        if consulta is not None:
            subconsultas.append(consulta)

    if isinstance(from_, exp.From) and isinstance(from_.this, exp.Expression):
        # FROM a, b llega como JOIN sin tipo ni ON: un producto cruzado, en el orden escrito.
        anterior = from_.this
        for join in joins:
            if not isinstance(join.this, exp.Expression):
                continue
            condicion = join.args.get("on")
            relaciones.append(
                RelacionSintactica(
                    _tipo_join(join),
                    Nodo(anterior),
                    Nodo(join.this),
                    Nodo(condicion) if isinstance(condicion, exp.Expression) else None,
                )
            )
            anterior = join.this
    return tablas, relaciones, subconsultas


def _tipo_join(join: exp.Join) -> str:
    kind = str(join.args.get("kind") or "").upper()
    side = str(join.args.get("side") or "").upper()
    method = str(join.args.get("method") or "").upper()
    if kind in {"SEMI", "ANTI"} or method:
        return "otro"
    if side == "LEFT":
        return "left"
    if side == "RIGHT":
        return "right"
    if side == "FULL":
        return "full"
    if kind == "CROSS":
        return "cross"
    if join.args.get("on") is None and not join.args.get("using") and not side and not kind:
        return "cross"
    if kind in {"", "INNER"}:
        return "inner"
    return "otro"


def _subconsulta_de_origen(fuente: exp.Expression) -> Subconsulta | None:
    if isinstance(fuente, exp.Table):
        return None
    if isinstance(fuente, (exp.Subquery, exp.Lateral)):
        return Subconsulta(Nodo(_cuerpo(fuente)), _texto_alias(fuente))
    if isinstance(fuente, (exp.Select, exp.SetOperation)):
        return Subconsulta(Nodo(fuente), None)
    return None


def _cuerpo(arbol: exp.Expression) -> exp.Expression:
    # ORDER BY, LIMIT u OFFSET pueden vivir en el Subquery, no en el Select interior.
    while isinstance(arbol, (exp.Subquery, exp.Lateral)) and isinstance(arbol.this, exp.Expression):
        if _tiene_modificadores(arbol):
            return arbol
        arbol = arbol.this
    return arbol


def _tiene_modificadores(arbol: exp.Expression) -> bool:
    for clave in ("order", "offset", "limit"):
        if arbol.args.get(clave) not in (None, [], False, ""):
            return True
    return False


def _subconsultas_directas(arbol: exp.Expression) -> list[Subconsulta]:
    if isinstance(arbol, exp.Alias) and isinstance(arbol.this, exp.Expression):
        # El alias de la expresión es de la columna, no un origen de lectura.
        return _subconsultas_directas(arbol.this)
    if isinstance(arbol, (exp.Subquery, exp.Lateral)):
        hecha = _subconsulta_de_origen(arbol)
        return [hecha] if hecha is not None else []
    if isinstance(arbol, exp.Exists) and isinstance(arbol.this, exp.Expression):
        return [Subconsulta(Nodo(_cuerpo(arbol.this)), None)]
    if isinstance(arbol, (exp.Select, exp.SetOperation)):
        # ALL y SOME dejan el Select o la unión al descubierto, sin Subquery.
        return [Subconsulta(Nodo(arbol), None)]
    encontradas: list[Subconsulta] = []
    for parte in _partes(arbol):
        encontradas.extend(_subconsultas_directas(parte))
    return encontradas


def _tabla_de(arbol: exp.Expression) -> TablaSintactica | None:
    tabla = arbol.this if isinstance(arbol, exp.Schema) else arbol
    if not isinstance(tabla, exp.Table):
        return None
    alias = tabla.alias if isinstance(tabla.alias, str) and tabla.alias else None
    return TablaSintactica(tabla.name, alias)


def _tablas_de_objeto(arbol: exp.Expression) -> list[TablaSintactica]:
    candidatos: list[exp.Expression] = []
    if isinstance(arbol, exp.Drop):
        candidatos.extend(
            item for item in (arbol.args.get("tables") or []) if isinstance(item, exp.Expression)
        )
    elif isinstance(arbol, exp.Merge):
        for clave in ("this", "using"):
            valor = arbol.args.get(clave)
            if isinstance(valor, exp.Expression):
                candidatos.append(valor)
    else:
        this = arbol.args.get("this")
        if isinstance(this, exp.Expression):
            candidatos.append(this)
    tablas: list[TablaSintactica] = []
    for candidato in candidatos:
        tabla = _tabla_de(candidato)
        if tabla is not None:
            tablas.append(tabla)
    return tablas


def _columnas_definidas(arbol: exp.Expression) -> list[exp.ColumnDef]:
    esquema = arbol.args.get("this")
    if not isinstance(esquema, exp.Schema):
        return []
    return [columna for columna in esquema.expressions if isinstance(columna, exp.ColumnDef)]


def _clausulas(arbol: exp.Expression) -> tuple[ClausulaSintactica, ...]:
    encontradas: list[ClausulaSintactica] = []
    for clave, nombre in (
        ("where", "WHERE"),
        ("group", "GROUP BY"),
        ("having", "HAVING"),
        ("distinct", "DISTINCT"),
        ("order", "ORDER BY"),
        ("offset", "OFFSET"),
    ):
        valor = arbol.args.get(clave)
        if isinstance(valor, exp.Expression):
            encontradas.append(ClausulaSintactica(nombre, Nodo(valor)))
    limite = arbol.args.get("limit")
    if isinstance(limite, exp.Fetch):
        encontradas.append(ClausulaSintactica("FETCH", Nodo(limite)))
    elif isinstance(limite, exp.Expression):
        encontradas.append(ClausulaSintactica("LIMIT", Nodo(limite)))
    return tuple(encontradas)


_COMPARACION = (
    exp.EQ,
    exp.NEQ,
    exp.GT,
    exp.GTE,
    exp.LT,
    exp.LTE,
    exp.NullSafeEQ,
    exp.NullSafeNEQ,
)
_IGNORAR = (exp.Identifier, exp.DataType, exp.TableAlias)


def _clasificar(arbol: object) -> Expresion:
    if isinstance(arbol, exp.Paren) and isinstance(arbol.this, exp.Expression):
        return _clasificar(arbol.this)
    if isinstance(arbol, (exp.Where, exp.Having)) and isinstance(arbol.this, exp.Expression):
        return _clasificar(arbol.this)
    if isinstance(arbol, exp.Group):
        return Expresion("otra", None, None, tuple(_clasificar(hijo) for hijo in arbol.expressions))
    if isinstance(arbol, exp.Order):
        claves = tuple(_clasificar(_clave_orden(hijo)) for hijo in arbol.expressions)
        return Expresion("otra", None, None, claves)
    if isinstance(arbol, (exp.Limit, exp.Fetch, exp.Offset)):
        valor = arbol.args.get("expression") or arbol.args.get("count")
        if isinstance(valor, exp.Expression):
            return _clasificar(valor)
        return Expresion("otra", None, None, ())
    if isinstance(arbol, exp.Alias):
        return Expresion("alias", _texto_alias(arbol), None, (_clasificar(arbol.this),))
    if isinstance(arbol, exp.Window):
        # La ventana no es una agregación. El agregado interior sí lo es; PARTITION BY y ORDER BY quedan fuera.
        return Expresion("ventana", None, None, tuple(_hijos_ventana(arbol)))
    if isinstance(arbol, exp.Column):
        if isinstance(arbol.this, exp.Star):
            return Expresion("asterisco", None, _calificador(arbol), ())
        return Expresion("columna", arbol.name, _calificador(arbol), ())
    if isinstance(arbol, exp.Star):
        return Expresion("asterisco", None, None, ())
    if isinstance(arbol, exp.Null):
        return Expresion("nulo", None, None, ())
    if isinstance(arbol, (exp.Literal, exp.Boolean)):
        return Expresion("literal", None, None, ())
    if isinstance(arbol, exp.Is) and isinstance(arbol.args.get("expression"), exp.Null):
        forma = "no_es_nulo" if arbol.args.get("negate") else "es_nulo"
        return Expresion(forma, None, None, (_clasificar(arbol.this),))
    if isinstance(arbol, exp.Not) and isinstance(arbol.this, exp.Expression):
        return Expresion("no", None, None, (_clasificar(arbol.this),))
    if isinstance(arbol, exp.And):
        return Expresion("y", None, None, _binarios(arbol))
    if isinstance(arbol, exp.Or):
        return Expresion("o", None, None, _binarios(arbol))
    if isinstance(arbol, _COMPARACION):
        return Expresion("comparacion", None, None, _binarios(arbol))
    if isinstance(arbol, exp.Filter) and isinstance(arbol.this, exp.AggFunc):
        return _agregado(arbol.this, arbol.args.get("expression"))
    if isinstance(arbol, exp.AggFunc):
        return _agregado(arbol, None)
    if isinstance(arbol, exp.ColumnDef):
        return Expresion("otra", arbol.name or None, None, ())
    if isinstance(arbol, (exp.Select, exp.SetOperation, exp.Subquery)):
        return Expresion("otra", None, None, ())
    if not isinstance(arbol, exp.Expression):
        return Expresion("otra", None, None, ())
    nombre = arbol.sql_name() if isinstance(arbol, exp.Func) else None
    return Expresion(
        "otra",
        nombre,
        None,
        tuple(_clasificar(parte) for parte in _partes(arbol)),
    )


def _agregado(funcion: exp.AggFunc, predicado: object) -> Expresion:
    hijos = [_clasificar(argumento) for argumento in _argumentos(funcion)]
    if isinstance(predicado, exp.Expression):
        hijos.append(_clasificar(predicado))
    return Expresion("agregacion", funcion.sql_name(), None, tuple(hijos))


def _hijos_ventana(arbol: exp.Window) -> list[Expresion]:
    hijos: list[Expresion] = []
    if isinstance(arbol.this, exp.Expression):
        hijos.append(_clasificar(arbol.this))
    for parte in arbol.args.get("partition_by") or []:
        if isinstance(parte, exp.Expression):
            hijos.append(_clasificar(parte))
    orden = arbol.args.get("order")
    if isinstance(orden, exp.Order):
        hijos.extend(_clasificar(_clave_orden(clave)) for clave in orden.expressions)
    return hijos


def _clave_orden(clave: exp.Expression) -> exp.Expression:
    if isinstance(clave, exp.Ordered) and isinstance(clave.this, exp.Expression):
        return clave.this
    return clave


def _argumentos(funcion: exp.Expression) -> list[exp.Expression]:
    encontrados: list[exp.Expression] = []

    def agregar(valor: object) -> None:
        if isinstance(valor, exp.Distinct):
            for expresion_interna in valor.expressions:
                agregar(expresion_interna)
            return
        if isinstance(valor, exp.Expression) and not isinstance(valor, exp.Identifier):
            encontrados.append(valor)

    agregar(funcion.args.get("this"))
    for extra in funcion.args.get("expressions") or []:
        agregar(extra)
    return encontrados


def _binarios(arbol: exp.Expression) -> tuple[Expresion, ...]:
    hijos: list[Expresion] = []
    for clave in ("this", "expression"):
        valor = arbol.args.get(clave)
        if isinstance(valor, exp.Expression):
            hijos.append(_clasificar(valor))
    return tuple(hijos)


def _partes(arbol: exp.Expression) -> list[exp.Expression]:
    partes: list[exp.Expression] = []
    for valor in arbol.args.values():
        candidatos = valor if isinstance(valor, list) else (valor,)
        for candidato in candidatos:
            if isinstance(candidato, exp.Expression) and not isinstance(candidato, _IGNORAR):
                partes.append(candidato)
    return partes


def _calificador(columna: exp.Column) -> str | None:
    tabla = columna.args.get("table")
    if isinstance(tabla, exp.Identifier) and tabla.name:
        return tabla.name
    if isinstance(tabla, str) and tabla:
        return tabla
    return None


def _texto_alias(arbol: exp.Expression) -> str | None:
    alias = arbol.alias
    if isinstance(alias, str) and alias:
        return alias
    return None


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
    # SQLGlot mira primero `*/` y solo busca un `/*` anidado después de consumir un carácter.
    profundidad = 1
    while indice < len(sql) and profundidad:
        if sql.startswith(cierre, indice):
            profundidad -= 1
            if profundidad == 0:
                indice, linea, columna = _avanzar(sql, indice, linea, columna, len(cierre))
                return True, indice, linea, columna
        indice, linea, columna = _avanzar(sql, indice, linea, columna, 1)
        if anidados and indice < len(sql) and sql.startswith(apertura, indice):
            profundidad += 1
            indice, linea, columna = _avanzar(sql, indice, linea, columna, len(apertura))
    return False, indice, linea, columna


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
