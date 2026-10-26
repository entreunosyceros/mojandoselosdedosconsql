from __future__ import annotations

from decimal import Decimal, InvalidOperation

from analizador.modelo import Advertencia, Componente, Tabla
from analizador.parser import Expresion, Nodo, bloque, expresion, normalizar

_GRAVEDAD = "aviso"
_COMPARACIONES = {"EQ": "=", "NEQ": "<>", "GT": ">", "GTE": ">=", "LT": "<", "LTE": "<="}
_CONSULTA = {"Select", "Union", "Except", "Intersect", "Subquery", "Values", "Lateral", "Unnest"}
_OUTER = {"left": "LEFT JOIN", "right": "RIGHT JOIN", "full": "FULL JOIN"}


def evaluar(componente: Componente, dialecto: str) -> tuple[Advertencia, ...]:
    avisos = _del_componente(componente, dialecto)
    for hijo in componente.hijos:
        avisos.extend(evaluar(hijo, dialecto))
    return tuple(avisos)


def _del_componente(componente: Componente, dialecto: str) -> list[Advertencia]:
    # El envoltorio WITH y la unión comparten nodo. Solo se evalúa lo que este componente posee.
    if componente._nodo is None or not (
        componente.columnas or componente.clausulas or componente.relaciones
    ):
        return []
    info = bloque(componente._nodo)
    clausulas = [
        (clausula.nombre, sintactica.nodo)
        for clausula, sintactica in zip(componente.clausulas, info.clausulas, strict=False)
        if clausula.nombre == sintactica.nombre
    ]
    relaciones = [
        (relacion, sintactica)
        for relacion, sintactica in zip(componente.relaciones, info.relaciones, strict=False)
        if relacion.tipo == sintactica.tipo
    ]
    columnas = list(zip(componente.columnas, info.proyecciones, strict=False))
    avisos: list[Advertencia] = []
    avisos.extend(_outer_join(componente, clausulas, relaciones, dialecto))
    avisos.extend(_comparaciones_nulas(componente, clausulas, relaciones, columnas, dialecto))
    avisos.extend(_asteriscos(componente, columnas, dialecto))
    avisos.extend(_agrupacion(componente, clausulas, columnas, dialecto))
    return avisos


def _outer_join(componente, clausulas, relaciones, dialecto) -> list[Advertencia]:
    predicados = [_predicado(nodo) for nombre, nodo in clausulas if nombre in {"WHERE", "HAVING"}]
    avisos: list[Advertencia] = []
    for indice, (relacion, sintactica) in enumerate(relaciones):
        forma = _OUTER.get(relacion.tipo)
        if forma is None:
            continue
        posteriores = [
            posterior.condicion
            for siguiente, (_, posterior) in enumerate(relaciones)
            if siguiente > indice and posterior.tipo == "inner" and posterior.condicion is not None
        ]
        for lado in _lados(relacion):
            anulables = _calificadores(lado, componente.tablas)
            if not anulables:
                continue
            for predicado in predicados + posteriores:
                tabla = _mencion(predicado._expression, anulables)
                if tabla is None:
                    continue
                resultado = _resultado(predicado._expression, anulables)
                if resultado not in {"FALSE", "UNKNOWN"}:
                    continue
                fragmento = normalizar(predicado, dialecto)
                avisos.append(
                    _aviso(
                        componente,
                        "outer_join_filtrado",
                        (
                            f"El {forma} con {tabla} deja sus columnas a NULL cuando no hay "
                            f"coincidencia. El filtro posterior `{fragmento}` descarta esos NULL, "
                            "así que las filas sin coincidencia pueden desaparecer."
                        ),
                        fragmento,
                    )
                )
    return avisos


def _lados(relacion) -> tuple[str, ...]:
    if relacion.tipo == "left":
        return (relacion.derecha,)
    if relacion.tipo == "right":
        return (relacion.izquierda,)
    if relacion.tipo == "full":
        return (relacion.izquierda, relacion.derecha)
    return ()


def _calificadores(lado: str, tablas: tuple[Tabla, ...]) -> set[str]:
    nombres: set[str] = set()
    for tabla in tablas:
        if not _lado_contiene(lado, tabla):
            continue
        nombres.add(tabla.nombre)
        if tabla.alias:
            nombres.add(tabla.alias)
    return nombres


def _lado_contiene(lado: str, tabla: Tabla) -> bool:
    if lado.startswith("("):
        return bool(tabla.alias) and (
            lado.endswith(f" AS {tabla.alias}") or lado.endswith(f' AS "{tabla.alias}"')
        )
    if tabla.alias:
        return lado.endswith(f" AS {tabla.alias}") or lado.endswith(f' AS "{tabla.alias}"')
    citado = f'"{tabla.nombre}"'
    return lado in {tabla.nombre, citado} or lado.endswith(f".{tabla.nombre}") or lado.endswith(
        f".{citado}"
    )


def _comparaciones_nulas(componente, clausulas, relaciones, columnas, dialecto) -> list[Advertencia]:
    raices: list[object] = []
    for columna, proyeccion in columnas:
        if columna.papel == "proyeccion":
            raices.append(proyeccion._expression)
    raices.extend(nodo._expression for _, nodo in clausulas)
    raices.extend(
        sintactica.condicion._expression
        for _, sintactica in relaciones
        if sintactica.condicion is not None
    )
    avisos: list[Advertencia] = []
    vistos: set[int] = set()
    for raiz in raices:
        _buscar_nulos(raiz, componente, dialecto, vistos, avisos)
    return avisos


def _buscar_nulos(expr, componente, dialecto, vistos, avisos) -> None:
    if id(expr) in vistos or not _es_expr(expr):
        return
    vistos.add(id(expr))
    nombre = type(expr).__name__
    if nombre in _CONSULTA:
        return
    if nombre in {"EQ", "NEQ"} and (_es_nulo(expr.this) or _es_nulo(expr.expression)):
        fragmento = normalizar(Nodo(expr), dialecto)
        operador = _COMPARACIONES[nombre]
        avisos.append(
            _aviso(
                componente,
                "comparacion_con_null",
                (
                    f"La comparación `{fragmento}` usa {operador} con NULL. Con este operador "
                    "el resultado es desconocido, así que el filtro no selecciona esas filas. "
                    "Para comprobar NULL usa IS NULL o IS NOT NULL."
                ),
                fragmento,
            )
        )
    for hijo in _subexpresiones(expr):
        _buscar_nulos(hijo, componente, dialecto, vistos, avisos)


def _asteriscos(componente, columnas, dialecto) -> list[Advertencia]:
    avisos: list[Advertencia] = []
    for columna, proyeccion in columnas:
        if columna.papel != "proyeccion":
            continue
        forma = expresion(proyeccion)
        if forma.forma == "asterisco":
            estrella = forma
            nodo = _desnudar(proyeccion, False)
        elif forma.forma == "alias" and forma.hijos and forma.hijos[0].forma == "asterisco":
            estrella = forma.hijos[0]
            nodo = _desnudar(proyeccion, True)
        else:
            continue
        fragmento = normalizar(nodo, dialecto)
        if estrella.calificador:
            tablas = columna.tabla if columna.certeza == "resuelta" and columna.tabla else estrella.calificador
            mensaje = f"`{fragmento}` recupera todas las columnas de {tablas}."
        else:
            mensaje = "`*` recupera todas las columnas de las tablas de esta consulta."
        avisos.append(_aviso(componente, "select_asterisco", mensaje, fragmento))
    return avisos


def _agrupacion(componente, clausulas, columnas, dialecto) -> list[Advertencia]:
    if dialecto == "sqlite":
        return []
    grupo = next((nodo for nombre, nodo in clausulas if nombre == "GROUP BY"), None)
    if grupo is None:
        return []
    elementos = _elementos_grupo(grupo)
    claves = [
        _referencia(columna, componente.tablas)
        for elemento in elementos
        if (columna := _columna_simple(expresion(elemento))) is not None
    ]
    alias = [
        forma.nombre
        for _, proyeccion in columnas
        if (forma := expresion(proyeccion)).forma == "alias" and forma.nombre
    ]
    avisos: list[Advertencia] = []
    for columna, proyeccion in columnas:
        if columna.papel != "proyeccion":
            continue
        forma = expresion(proyeccion)
        if _misma_expresion(proyeccion, elementos, dialecto):
            continue
        if _alias_impide_aviso(forma, alias, claves):
            continue
        referencias = [_referencia(ref, componente.tablas) for ref in _referencias(forma)]
        if not any(_descubierta(ref, claves) for ref in referencias):
            continue
        fragmento = normalizar(proyeccion, dialecto)
        avisos.append(
            _aviso(
                componente,
                "select_fuera_de_group_by",
                (
                    f"`{fragmento}` está en el SELECT, no está en el GROUP BY y no está dentro "
                    "de una función de agregación. Según el dialecto, el motor puede rechazar "
                    "la consulta o devolver un valor cualquiera del grupo."
                ),
                fragmento,
            )
        )
    return avisos


def _alias_impide_aviso(forma: Expresion, alias: list[str | None], claves: list[_Ref]) -> bool:
    if forma.forma != "alias" or not forma.nombre or alias.count(forma.nombre) != 1:
        return False
    return any(clave.certeza == "sin_calificar" and clave.nombre == forma.nombre for clave in claves)


def _misma_expresion(proyeccion: Nodo, elementos: list[Nodo], dialecto: str) -> bool:
    izquierda = _canon(normalizar(_nucleo(proyeccion), dialecto))
    return any(_canon(normalizar(_nucleo(elemento), dialecto)) == izquierda for elemento in elementos)


def _referencias(forma: Expresion):
    if forma.forma == "agregacion":
        return
    if forma.forma == "columna":
        yield forma
        return
    for hijo in forma.hijos:
        yield from _referencias(hijo)


def _columna_simple(forma: Expresion) -> Expresion | None:
    if forma.forma == "columna":
        return forma
    return None


def _descubierta(ref: _Ref, claves: list[_Ref]) -> bool:
    if ref.certeza in {"ambigua", "no_resuelta"}:
        return False
    return not any(_misma(ref, clave) or _incierta(ref, clave) for clave in claves)


def _misma(izquierda: _Ref, derecha: _Ref) -> bool:
    if not izquierda.nombre or not derecha.nombre:
        return False
    if izquierda.certeza == "resuelta" and derecha.certeza == "resuelta":
        return izquierda.tabla == derecha.tabla and izquierda.nombre == derecha.nombre
    if izquierda.certeza == "sin_calificar" and derecha.certeza == "sin_calificar":
        return izquierda.nombre == derecha.nombre
    return False


def _incierta(seleccion: _Ref, clave: _Ref) -> bool:
    if not seleccion.nombre or not clave.nombre or seleccion.nombre != clave.nombre:
        return False
    if clave.certeza in {"ambigua", "no_resuelta"}:
        return True
    return {seleccion.certeza, clave.certeza} == {"resuelta", "sin_calificar"}


class _Ref:
    def __init__(self, nombre: str | None, certeza: str, tabla: str | None) -> None:
        self.nombre = nombre
        self.certeza = certeza
        self.tabla = tabla


def _referencia(forma: Expresion, tablas: tuple[Tabla, ...]) -> _Ref:
    certeza, tabla = _resolver(forma.calificador, tablas)
    return _Ref(forma.nombre, certeza, tabla)


def _resolver(calificador: str | None, tablas: tuple[Tabla, ...]) -> tuple[str, str | None]:
    if not calificador:
        return "sin_calificar", None
    coincidencias = [
        tabla.nombre for tabla in tablas if calificador == tabla.nombre or calificador == tabla.alias
    ]
    if len(coincidencias) == 1:
        return "resuelta", coincidencias[0]
    if not coincidencias:
        return "no_resuelta", None
    return "ambigua", None


def _resultado(expr: object, anulables: set[str]) -> str:
    nombre = type(expr).__name__
    if nombre in _CONSULTA:
        return "INDETERMINADO"
    if nombre == "Paren":
        return _resultado(expr.this, anulables)
    if nombre == "Not":
        return _negar(_resultado(expr.this, anulables))
    if nombre == "And":
        return _conjuncion(_resultado(expr.this, anulables), _resultado(expr.expression, anulables))
    if nombre == "Or":
        return _disyuncion(_resultado(expr.this, anulables), _resultado(expr.expression, anulables))
    if nombre == "Is":
        return _es_nulo_predicado(expr, anulables)
    if nombre in _COMPARACIONES:
        return _comparar(nombre, expr.this, expr.expression, anulables)
    if nombre == "Boolean":
        return "TRUE" if expr.args.get("this") else "FALSE"
    if nombre == "Column":
        return "UNKNOWN" if _operando(expr, anulables) == "NULL" else "INDETERMINADO"
    if nombre == "Null":
        return "UNKNOWN"
    return "INDETERMINADO"


def _es_nulo_predicado(expr, anulables: set[str]) -> str:
    if type(expr.args.get("expression")).__name__ != "Null":
        return "INDETERMINADO"
    valor = _operando(expr.this, anulables)
    if valor == "NULL":
        resultado = "TRUE"
    elif isinstance(valor, tuple):
        resultado = "FALSE"
    else:
        resultado = "INDETERMINADO"
    if expr.args.get("negate"):
        return _negar(resultado)
    return resultado


def _comparar(operador: str, izquierda, derecha, anulables: set[str]) -> str:
    izq = _operando(izquierda, anulables)
    der = _operando(derecha, anulables)
    if izq == "NULL" or der == "NULL":
        return "UNKNOWN"
    if not isinstance(izq, tuple) or not isinstance(der, tuple):
        return "INDETERMINADO"
    concreto = _literales(operador, izq, der)
    if concreto is None:
        return "INDETERMINADO"
    return "TRUE" if concreto else "FALSE"


def _operando(expr, anulables: set[str]):
    nombre = type(expr).__name__
    if nombre == "Paren":
        return _operando(expr.this, anulables)
    if nombre == "Null":
        return "NULL"
    if nombre == "Boolean":
        return ("lit", "bool", bool(expr.args.get("this")))
    if nombre == "Literal":
        if expr.args.get("is_string"):
            return ("lit", "str", expr.args.get("this"))
        return ("lit", "num", expr.args.get("this"))
    if nombre == "Column":
        forma = expresion(Nodo(expr))
        if forma.forma == "columna" and forma.calificador in anulables:
            return "NULL"
        return "INDETERMINADO"
    return "INDETERMINADO"


def _literales(operador: str, izquierda: tuple, derecha: tuple) -> bool | None:
    if izquierda[1] != derecha[1]:
        return None
    if izquierda[1] == "bool":
        valores = (bool(izquierda[2]), bool(derecha[2]))
    elif izquierda[1] == "str":
        valores = (izquierda[2], derecha[2])
    else:
        try:
            valores = (Decimal(str(izquierda[2])), Decimal(str(derecha[2])))
        except (InvalidOperation, ValueError):
            return None
    izq, der = valores
    return {
        "EQ": izq == der,
        "NEQ": izq != der,
        "GT": izq > der,
        "GTE": izq >= der,
        "LT": izq < der,
        "LTE": izq <= der,
    }[operador]


def _conjuncion(izquierda: str, derecha: str) -> str:
    if "FALSE" in {izquierda, derecha}:
        return "FALSE"
    if "UNKNOWN" in {izquierda, derecha}:
        return "UNKNOWN"
    if "INDETERMINADO" in {izquierda, derecha}:
        return "INDETERMINADO"
    if izquierda == "TRUE" and derecha == "TRUE":
        return "TRUE"
    return "INDETERMINADO"


def _disyuncion(izquierda: str, derecha: str) -> str:
    if "TRUE" in {izquierda, derecha}:
        return "TRUE"
    if "INDETERMINADO" in {izquierda, derecha}:
        return "INDETERMINADO"
    if "UNKNOWN" in {izquierda, derecha}:
        return "UNKNOWN"
    if izquierda == "FALSE" and derecha == "FALSE":
        return "FALSE"
    return "INDETERMINADO"


def _negar(resultado: str) -> str:
    return {
        "TRUE": "FALSE",
        "FALSE": "TRUE",
        "UNKNOWN": "UNKNOWN",
        "INDETERMINADO": "INDETERMINADO",
    }.get(resultado, "INDETERMINADO")


def _mencion(expr, anulables: set[str]) -> str | None:
    nombre = type(expr).__name__
    if nombre in _CONSULTA or not _es_expr(expr):
        return None
    if nombre == "Column":
        forma = expresion(Nodo(expr))
        if forma.forma == "columna" and forma.calificador in anulables:
            return forma.calificador
        return None
    for hijo in _subexpresiones(expr):
        encontrado = _mencion(hijo, anulables)
        if encontrado:
            return encontrado
    return None


def _elementos_grupo(nodo: Nodo) -> list[Nodo]:
    expr = nodo._expression
    if type(expr).__name__ != "Group":
        return []
    return [Nodo(parte) for parte in expr.expressions if _es_expr(parte)]


def _predicado(nodo: Nodo) -> Nodo:
    expr = nodo._expression
    if type(expr).__name__ in {"Where", "Having"} and _es_expr(getattr(expr, "this", None)):
        return Nodo(expr.this)
    return nodo


def _nucleo(nodo: Nodo) -> Nodo:
    expr = nodo._expression
    while type(expr).__name__ in {"Alias", "Paren"} and _es_expr(getattr(expr, "this", None)):
        expr = expr.this
    return Nodo(expr)


def _desnudar(nodo: Nodo, alias: bool) -> Nodo:
    expr = nodo._expression
    quitables = {"Paren", "Alias"} if alias else {"Paren"}
    while type(expr).__name__ in quitables and _es_expr(getattr(expr, "this", None)):
        expr = expr.this
    return Nodo(expr)


def _canon(texto: str) -> str:
    texto = texto.strip()
    while len(texto) >= 2 and texto[0] == "(" and texto[-1] == ")" and _envuelve(texto):
        texto = texto[1:-1].strip()
    return texto


def _envuelve(texto: str) -> bool:
    profundidad = 0
    for indice, caracter in enumerate(texto):
        if caracter == "(":
            profundidad += 1
        elif caracter == ")":
            profundidad -= 1
            if profundidad == 0:
                return indice == len(texto) - 1
    return False


def _es_nulo(expr) -> bool:
    while type(expr).__name__ == "Paren" and _es_expr(getattr(expr, "this", None)):
        expr = expr.this
    return type(expr).__name__ == "Null"


def _es_expr(valor: object) -> bool:
    return hasattr(valor, "args") and hasattr(valor, "sql")


def _subexpresiones(expr) -> list:
    args = getattr(expr, "args", None)
    if not isinstance(args, dict):
        return []
    hijos = []
    for valor in args.values():
        if isinstance(valor, list):
            hijos.extend(item for item in valor if _es_expr(item))
        elif _es_expr(valor):
            hijos.append(valor)
    return hijos


def _aviso(componente: Componente, codigo: str, mensaje: str, fragmento: str) -> Advertencia:
    return Advertencia(
        codigo=codigo,
        gravedad=_GRAVEDAD,
        mensaje=mensaje,
        componente_id=componente.id,
        fragmento=fragmento,
    )
