from __future__ import annotations

from analizador.modelo import Clausula, Columna, Componente, Relacion, Tabla
from analizador.parser import (
    Bloque,
    Nodo,
    Subconsulta,
    TablaSintactica,
    bloque,
    expresion,
    normalizar,
)

_FORMA_JOIN = {
    "inner": "INNER JOIN",
    "left": "LEFT JOIN",
    "right": "RIGHT JOIN",
    "full": "FULL JOIN",
}
_CLAUSULAS_SELECT = (
    "WHERE",
    "GROUP BY",
    "HAVING",
    "DISTINCT",
    "ORDER BY",
    "OFFSET",
    "LIMIT",
    "TOP",
    "FETCH",
)


class _Contador:
    def __init__(self) -> None:
        self._n = 1

    def tomar(self, indice: int) -> str:
        ident = f"s{indice}.c{self._n}"
        self._n += 1
        return ident


def componentes(
    nodo: Nodo, indice_sentencia: int, dialecto: str = "postgresql"
) -> Componente:
    return _construir(nodo, indice_sentencia, _Contador(), "raiz", None, dialecto)


def _construir(
    nodo: Nodo,
    indice: int,
    contador: _Contador,
    rol: str,
    nombre: str | None,
    dialecto: str,
) -> Componente:
    info = bloque(nodo)
    if rol == "cte" and info.ramas is not None and not info.ctes:
        return _cte_sobre_union(nodo, info, indice, contador, nombre, dialecto)
    if info.ramas is not None and info.ctes:
        return _envoltura(nodo, info, indice, contador, rol, nombre, dialecto)
    if info.ramas is not None:
        return _union(nodo, info, indice, contador, dialecto)
    return _consulta(nodo, info, indice, contador, rol, nombre, dialecto)


def _envoltura(
    nodo: Nodo,
    info: Bloque,
    indice: int,
    contador: _Contador,
    rol: str,
    nombre: str | None,
    dialecto: str,
) -> Componente:
    ident = contador.tomar(indice)
    hijos = [
        _construir(cte.nodo, indice, contador, "cte", cte.alias, dialecto) for cte in info.ctes
    ]
    hijos.append(_union(nodo, info, indice, contador, dialecto))
    return _componente(
        ident,
        "cte" if rol == "cte" else "consulta",
        nombre if rol == "cte" else None,
        info,
        (),
        (),
        (),
        (),
        (),
        tuple(hijos),
        nodo,
    )


def _cte_sobre_union(
    nodo: Nodo,
    info: Bloque,
    indice: int,
    contador: _Contador,
    nombre: str | None,
    dialecto: str,
) -> Componente:
    ident = contador.tomar(indice)
    return _componente(
        ident,
        "cte",
        nombre,
        info,
        (),
        (),
        (),
        (),
        (),
        (_union(nodo, info, indice, contador, dialecto),),
        nodo,
    )


def _union(
    nodo: Nodo, info: Bloque, indice: int, contador: _Contador, dialecto: str
) -> Componente:
    ident = contador.tomar(indice)
    hijos = tuple(
        _construir(rama, indice, contador, "rama", None, dialecto) for rama in info.ramas or ()
    )
    clausulas = _clausulas_de(info, dialecto)
    return _componente(
        ident,
        "union",
        None,
        info,
        (),
        (),
        clausulas,
        (),
        _pasos(info, (), (), clausulas, dialecto),
        hijos,
        nodo,
    )


def _consulta(
    nodo: Nodo,
    info: Bloque,
    indice: int,
    contador: _Contador,
    rol: str,
    nombre: str | None,
    dialecto: str,
) -> Componente:
    ident = contador.tomar(indice)
    tablas = _tablas_de(info, dialecto)
    columnas = _columnas_de(info, tablas, dialecto)
    clausulas = _clausulas_de(info, dialecto)
    relaciones = _relaciones_de(info, dialecto)
    hijos = [
        _construir(cte.nodo, indice, contador, "cte", cte.alias, dialecto) for cte in info.ctes
    ]
    hijos.extend(
        _construir(sub.nodo, indice, contador, "hijo", None, dialecto) for sub in info.subconsultas
    )
    return _componente(
        ident,
        _clase(rol),
        nombre if rol == "cte" else None,
        info,
        tablas,
        columnas,
        clausulas,
        relaciones,
        _pasos(info, tablas, relaciones, clausulas, dialecto),
        tuple(hijos),
        nodo,
    )


def _componente(
    ident: str,
    clase: str,
    nombre: str | None,
    info: Bloque,
    tablas: tuple[Tabla, ...],
    columnas: tuple[Columna, ...],
    clausulas: tuple[Clausula, ...],
    relaciones: tuple[Relacion, ...],
    pasos: tuple[str, ...],
    hijos: tuple[Componente, ...],
    nodo: Nodo,
) -> Componente:
    return Componente(
        id=ident,
        clase=clase,
        nombre=nombre,
        tipo=info.tipo,
        tablas=tablas,
        columnas=columnas,
        clausulas=clausulas,
        relaciones=relaciones,
        pasos=pasos,
        hijos=hijos,
        explicacion=None,
        _nodo=nodo,
    )


def _clase(rol: str) -> str:
    if rol == "cte":
        return "cte"
    if rol == "hijo":
        return "subconsulta"
    return "consulta"


def _tablas_de(info: Bloque, dialecto: str) -> tuple[Tabla, ...]:
    tablas: list[Tabla] = []
    for clase, indice, pieza in _origenes(info, dialecto):
        if clase == "base" and isinstance(pieza, TablaSintactica):
            tablas.append(
                Tabla(
                    nombre=pieza.nombre,
                    alias=pieza.alias,
                    papel=_papel_tabla(info.tipo, indice),
                    explicacion=None,
                )
            )
        elif isinstance(pieza, Subconsulta) and pieza.alias:
            tablas.append(
                Tabla(nombre=pieza.alias, alias=pieza.alias, papel="lectura", explicacion=None)
            )
    return tuple(tablas)


def _origenes(
    info: Bloque, dialecto: str
) -> list[tuple[str, int, TablaSintactica | Subconsulta]]:
    bases = list(enumerate(info.tablas))
    derivadas = [(indice, sub) for indice, sub in enumerate(info.subconsultas) if sub.alias]
    if not info.relaciones:
        return [("base", indice, tabla) for indice, tabla in bases] + [
            ("derivada", indice, sub) for indice, sub in derivadas
        ]

    lados = [normalizar(info.relaciones[0].izquierda, dialecto)]
    lados.extend(normalizar(relacion.derecha, dialecto) for relacion in info.relaciones)
    orden: list[tuple[str, int, TablaSintactica | Subconsulta]] = []
    bases_usadas: set[int] = set()
    derivadas_usadas: set[int] = set()
    for lado in lados:
        if _tomar_base(lado, bases, bases_usadas, orden):
            continue
        _tomar_derivada(lado, derivadas, derivadas_usadas, orden)
    for indice, tabla in bases:
        if indice not in bases_usadas:
            orden.append(("base", indice, tabla))
    for indice, sub in derivadas:
        if indice not in derivadas_usadas:
            orden.append(("derivada", indice, sub))
    return orden


def _tomar_base(
    lado: str,
    bases: list[tuple[int, TablaSintactica]],
    usadas: set[int],
    orden: list[tuple[str, int, TablaSintactica | Subconsulta]],
) -> bool:
    for indice, tabla in bases:
        if indice in usadas or not _lado_es_base(lado, tabla):
            continue
        orden.append(("base", indice, tabla))
        usadas.add(indice)
        return True
    return False


def _tomar_derivada(
    lado: str,
    derivadas: list[tuple[int, Subconsulta]],
    usadas: set[int],
    orden: list[tuple[str, int, TablaSintactica | Subconsulta]],
) -> None:
    for indice, sub in derivadas:
        if indice in usadas or not sub.alias or not _lado_es_derivada(lado, sub.alias):
            continue
        orden.append(("derivada", indice, sub))
        usadas.add(indice)
        return


def _formas(nombre: str) -> tuple[str, ...]:
    return (nombre, f'"{nombre}"', f"`{nombre}`", f"[{nombre}]")


def _lado_es_base(lado: str, tabla: TablaSintactica) -> bool:
    if lado.startswith("("):
        return False
    if tabla.alias:
        return any(lado.endswith(f" AS {forma}") for forma in _formas(tabla.alias))
    return any(lado == forma or lado.endswith(f".{forma}") for forma in _formas(tabla.nombre))


def _lado_es_derivada(lado: str, alias: str) -> bool:
    return lado.startswith("(") and any(
        lado.endswith(f" AS {forma}") for forma in _formas(alias)
    )


def _papel_tabla(tipo: str, indice: int) -> str:
    if tipo in {"Insert", "Update", "Delete", "Merge"}:
        return "destino" if indice == 0 else "lectura"
    if tipo in {"Create", "Alter", "Drop"}:
        return "definicion"
    return "lectura"


def _columnas_de(info: Bloque, tablas: tuple[Tabla, ...], dialecto: str) -> tuple[Columna, ...]:
    papel = "definicion" if info.tipo == "Create" else "proyeccion"
    return tuple(_columna(proyeccion, tablas, papel, dialecto) for proyeccion in info.proyecciones)


def _columna(nodo: Nodo, tablas: tuple[Tabla, ...], papel: str, dialecto: str) -> Columna:
    forma = expresion(nodo)
    alias = None
    nucleo = forma
    if forma.forma == "alias" and forma.hijos:
        alias = forma.nombre
        nucleo = forma.hijos[0]
    if nucleo.forma in {"columna", "asterisco"}:
        nombre = nucleo.nombre
        calificador = nucleo.calificador
    elif papel == "definicion":
        nombre = nucleo.nombre
        calificador = None
    else:
        nombre = None
        calificador = None
    certeza, tabla = _resolver(calificador, tablas)
    return Columna(
        expresion=normalizar(nodo, dialecto),
        nombre=nombre,
        calificador=calificador,
        tabla=tabla,
        certeza=certeza,
        alias=alias,
        papel=papel,
        explicacion=None,
    )


def _resolver(calificador: str | None, tablas: tuple[Tabla, ...]) -> tuple[str, str | None]:
    if not calificador:
        return "sin_calificar", None
    coincidencias = [
        tabla.nombre
        for tabla in tablas
        if calificador == tabla.nombre or calificador == tabla.alias
    ]
    if len(coincidencias) == 1:
        return "resuelta", coincidencias[0]
    if not coincidencias:
        return "no_resuelta", None
    return "ambigua", None


def _clausulas_de(info: Bloque, dialecto: str) -> tuple[Clausula, ...]:
    return tuple(_clausula_de(clausula.nombre, clausula.nodo, dialecto) for clausula in info.clausulas)


def _clausula_de(nombre: str, nodo: Nodo, dialecto: str) -> Clausula:
    texto = normalizar(nodo, dialecto)
    if nombre == "LIMIT" and dialecto == "sqlserver":
        nombre = "TOP"
        if texto.startswith("LIMIT"):
            texto = "TOP" + texto[len("LIMIT") :]
    return Clausula(nombre=nombre, texto=texto, explicacion=None)


def _relaciones_de(info: Bloque, dialecto: str) -> tuple[Relacion, ...]:
    return tuple(
        Relacion(
            tipo=relacion.tipo,
            izquierda=normalizar(relacion.izquierda, dialecto),
            derecha=normalizar(relacion.derecha, dialecto),
            condicion=None
            if relacion.condicion is None
            else normalizar(relacion.condicion, dialecto),
            explicacion=None,
            _forma=relacion.forma,
        )
        for relacion in info.relaciones
    )


def _pasos(
    info: Bloque,
    tablas: tuple[Tabla, ...],
    relaciones: tuple[Relacion, ...],
    clausulas: tuple[Clausula, ...],
    dialecto: str,
) -> tuple[str, ...]:
    if info.tipo == "Select":
        return _pasos_select(info, tablas, relaciones, clausulas, dialecto)
    if info.tipo == "Insert":
        return _pasos_insert(info, tablas, clausulas)
    if info.tipo == "Update":
        return _pasos_update(tablas, clausulas)
    if info.tipo == "Delete":
        return _pasos_delete(tablas, clausulas)
    return _pasos_otra(info.tipo, clausulas)


def _pasos_select(
    info: Bloque,
    tablas: tuple[Tabla, ...],
    relaciones: tuple[Relacion, ...],
    clausulas: tuple[Clausula, ...],
    dialecto: str,
) -> tuple[str, ...]:
    pasos = _pasos_origenes(tablas, relaciones)
    por_nombre = {clausula.nombre: clausula for clausula in clausulas}
    for nombre in ("WHERE", "GROUP BY", "HAVING"):
        clausula = por_nombre.get(nombre)
        if clausula is not None:
            pasos.append(_paso_clausula(clausula))
    if info.proyecciones:
        expresiones = ", ".join(
            normalizar(proyeccion, dialecto) for proyeccion in info.proyecciones
        )
        pasos.append(f"Selecciona {expresiones}.")
    for nombre in ("DISTINCT", "ORDER BY", "OFFSET", "LIMIT", "TOP", "FETCH"):
        clausula = por_nombre.get(nombre)
        if clausula is not None:
            pasos.append(_paso_clausula(clausula))
    conocidos = set(_CLAUSULAS_SELECT)
    for clausula in clausulas:
        if clausula.nombre not in conocidos:
            pasos.append(_paso_clausula(clausula))
    return tuple(pasos)


def _pasos_origenes(tablas: tuple[Tabla, ...], relaciones: tuple[Relacion, ...]) -> list[str]:
    if not tablas:
        return []
    if not relaciones:
        return [f"Toma las filas de {tabla.nombre}." for tabla in tablas]
    pasos = [f"Toma las filas de {tablas[0].nombre}."]
    pasos.extend(_paso_relacion(relacion) for relacion in relaciones)
    return pasos


def _paso_relacion(relacion: Relacion) -> str:
    return _texto_relacion(relacion)


def _texto_relacion(relacion: Relacion) -> str:
    if relacion.condicion:
        forma = relacion._forma or _FORMA_JOIN.get(relacion.tipo, "JOIN")
        return (
            f"Une {relacion.izquierda} con {relacion.derecha} con un {forma}, "
            f"por {relacion.condicion}."
        )
    if relacion.tipo == "cross":
        return f"Une {relacion.izquierda} con {relacion.derecha} con un producto cruzado."
    forma = relacion._forma or _FORMA_JOIN.get(relacion.tipo, "JOIN")
    return f"Une {relacion.izquierda} con {relacion.derecha} con un {forma}."


def _pasos_insert(
    info: Bloque, tablas: tuple[Tabla, ...], clausulas: tuple[Clausula, ...]
) -> tuple[str, ...]:
    pasos: list[str] = []
    if tablas:
        pasos.append(f"Inserta filas en {tablas[0].nombre}.")
    emitidas: set[str] = set()
    for nombre in ("COLUMNAS", "VALUES"):
        clausula = next((item for item in clausulas if item.nombre == nombre), None)
        if clausula is None:
            continue
        pasos.append(_paso_clausula(clausula))
        emitidas.add(nombre)
    if "VALUES" not in emitidas and info.subconsultas:
        pasos.append("Usa la consulta de origen.")
    pasos.extend(
        _paso_clausula(clausula) for clausula in clausulas if clausula.nombre not in emitidas
    )
    return tuple(pasos)


def _pasos_update(tablas: tuple[Tabla, ...], clausulas: tuple[Clausula, ...]) -> tuple[str, ...]:
    return tuple(_pasos_modificacion("Modifica filas de", tablas, clausulas))


def _pasos_delete(tablas: tuple[Tabla, ...], clausulas: tuple[Clausula, ...]) -> tuple[str, ...]:
    return tuple(_pasos_modificacion("Elimina filas de", tablas, clausulas))


def _pasos_modificacion(
    verbo: str, tablas: tuple[Tabla, ...], clausulas: tuple[Clausula, ...]
) -> list[str]:
    pasos: list[str] = []
    if tablas:
        pasos.append(f"{verbo} {tablas[0].nombre}.")
    pasos.extend(f"Toma las filas de {tabla.nombre}." for tabla in tablas[1:])
    pasos.extend(_paso_clausula(clausula) for clausula in clausulas)
    return pasos


def _pasos_otra(tipo: str, clausulas: tuple[Clausula, ...]) -> tuple[str, ...]:
    return (f"Ejecuta una sentencia {tipo}.",) + tuple(
        _paso_clausula(clausula) for clausula in clausulas
    )


def _paso_clausula(clausula: Clausula) -> str:
    contenido = _sin_prefijo(clausula.texto, clausula.nombre)
    if clausula.nombre == "WHERE":
        return f"Filtra las filas según {contenido}."
    if clausula.nombre == "GROUP BY":
        return f"Agrupa las filas por {contenido}."
    if clausula.nombre == "HAVING":
        return f"Filtra los grupos según {contenido}."
    if clausula.nombre == "ORDER BY":
        return f"Ordena el resultado por {contenido}."
    if clausula.nombre in {"LIMIT", "TOP", "FETCH", "OFFSET"}:
        return f"Limita el resultado a {clausula.texto}."
    if clausula.nombre == "SET":
        return f"Asigna {contenido}."
    if clausula.nombre == "VALUES":
        return f"Usa los valores {contenido}."
    return f"Esta parte es un nodo {clausula.nombre} y su texto es {clausula.texto}."


def _sin_prefijo(texto: str, nombre: str) -> str:
    prefijo = f"{nombre} "
    if texto.startswith(prefijo):
        return texto[len(prefijo) :]
    return texto
