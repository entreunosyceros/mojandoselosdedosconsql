from __future__ import annotations

from dataclasses import replace

from analizador.mensajes import ORDEN_LOGICO
from analizador.modelo import Clausula, Columna, Componente, Relacion, Tabla
from analizador.parser import Nodo, bloque, normalizar

__all__ = ["ORDEN_LOGICO", "pasos_sentencia", "rellenar", "resumen"]

_DIALECTO = "postgresql"
_FORMA_JOIN = {
    "inner": "INNER JOIN",
    "left": "LEFT JOIN",
    "right": "RIGHT JOIN",
    "full": "FULL JOIN",
    "cross": "CROSS JOIN",
    "otro": "JOIN",
}
_LIMITES = {"LIMIT", "FETCH", "OFFSET", "TOP"}


def rellenar(componente: Componente) -> Componente:
    return replace(
        componente,
        tablas=tuple(_rellenar_tabla(tabla, componente.tipo) for tabla in componente.tablas),
        columnas=tuple(_rellenar_columna(columna) for columna in componente.columnas),
        clausulas=tuple(_rellenar_clausula(clausula) for clausula in componente.clausulas),
        relaciones=tuple(_rellenar_relacion(relacion) for relacion in componente.relaciones),
        hijos=tuple(rellenar(hijo) for hijo in componente.hijos),
        explicacion=_explicacion_componente(componente),
    )


def resumen(componente: Componente) -> str:
    delegado = _union_delegada(componente)
    if delegado is not None:
        return resumen(delegado)
    if componente.clase == "union":
        return _resumen_conjunto(componente)
    if componente.tipo == "Insert":
        destino = _nombre_papel(componente, "destino")
        if destino:
            return f"Inserta filas en {destino}."
    elif componente.tipo == "Update":
        destino = _nombre_papel(componente, "destino")
        if destino:
            return f"Modifica filas de {destino}."
    elif componente.tipo == "Delete":
        destino = _nombre_papel(componente, "destino")
        if destino:
            return f"Elimina filas de {destino}."
    elif componente.tipo == "Create":
        nombre = _nombre_papel(componente, "definicion")
        if nombre:
            return f"Define {nombre}."
        return f"Define un objeto {componente.tipo}."
    if componente.tipo == "Select":
        return _resumen_consulta(componente)
    return f"Ejecuta una sentencia {componente.tipo}."


def pasos_sentencia(componente: Componente) -> tuple[str, ...]:
    preparacion = tuple(
        f"Prepara la CTE {hijo.nombre}." for hijo in componente.hijos if hijo.clase == "cte"
    )
    cuerpo = _union_delegada(componente) or componente
    return preparacion + cuerpo.pasos


def _rellenar_tabla(tabla: Tabla, tipo: str) -> Tabla:
    return replace(tabla, explicacion=_explicacion_tabla(tabla, tipo))


def _rellenar_columna(columna: Columna) -> Columna:
    return replace(columna, explicacion=_explicacion_columna(columna))


def _rellenar_clausula(clausula: Clausula) -> Clausula:
    return replace(clausula, explicacion=_explicacion_clausula(clausula))


def _rellenar_relacion(relacion: Relacion) -> Relacion:
    return replace(relacion, explicacion=_explicacion_relacion(relacion))


def _explicacion_componente(componente: Componente) -> str:
    nombres = [hijo.nombre for hijo in componente.hijos if hijo.clase == "cte" and hijo.nombre]
    if nombres:
        return (
            f"Define las expresiones de tabla {_unir(nombres)}. "
            "La consulta exterior las usa después."
        )
    if componente.tipo == "Select":
        expresiones = ", ".join(columna.expresion for columna in componente.columnas)
        return f"Selecciona {expresiones}."
    if componente.tipo == "Insert":
        destino = _nombre_papel(componente, "destino")
        if destino:
            return f"Inserta filas en {destino}."
    elif componente.tipo == "Update":
        destino = _nombre_papel(componente, "destino")
        if destino:
            return f"Modifica filas de {destino}."
    elif componente.tipo == "Delete":
        destino = _nombre_papel(componente, "destino")
        if destino:
            return f"Elimina filas de {destino}."
    return _nodo_desconocido(componente.tipo, _texto(componente))


def _explicacion_tabla(tabla: Tabla, tipo: str) -> str:
    if tabla.papel == "lectura":
        return f"Toma las filas de {tabla.nombre}."
    if tabla.papel == "destino" and tipo == "Insert":
        return f"Inserta filas en {tabla.nombre}."
    if tabla.papel == "destino" and tipo == "Update":
        return f"Modifica filas de {tabla.nombre}."
    if tabla.papel == "destino" and tipo == "Delete":
        return f"Elimina filas de {tabla.nombre}."
    if tabla.papel == "definicion" and tipo == "Create":
        return f"Define {tabla.nombre}."
    return _nodo_desconocido(tipo, tabla.nombre)


def _explicacion_columna(columna: Columna) -> str:
    if columna.papel == "proyeccion":
        return f"Selecciona {columna.expresion}."
    if columna.papel == "definicion" and columna.nombre:
        return f"Define {columna.nombre}."
    return _nodo_desconocido(columna.papel, columna.expresion)


def _explicacion_clausula(clausula: Clausula) -> str:
    contenido = _sin_prefijo(clausula.texto, clausula.nombre)
    if clausula.nombre == "WHERE":
        return f"Filtra las filas según {contenido}."
    if clausula.nombre == "GROUP BY":
        return f"Agrupa las filas por {contenido}."
    if clausula.nombre == "HAVING":
        return f"Filtra los grupos según {contenido}."
    if clausula.nombre == "ORDER BY":
        return f"Ordena el resultado por {contenido}."
    if clausula.nombre in _LIMITES:
        return f"Limita el resultado a {clausula.texto}."
    if clausula.nombre == "SET":
        return f"Asigna {contenido}."
    if clausula.nombre == "VALUES":
        return f"Usa los valores {contenido}."
    return _nodo_desconocido(clausula.nombre, clausula.texto)


def _explicacion_relacion(relacion: Relacion) -> str:
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


def _resumen_conjunto(componente: Componente) -> str:
    if componente.tipo != "Union":
        return f"Ejecuta una sentencia {componente.tipo}."
    operador = "UNION ALL" if _es_union_all(componente) else "UNION"
    nombres = _tablas_de_ramas(componente)
    if not nombres:
        return f"Combina con {operador} consultas sin tabla de origen."
    return f"Combina con {operador} filas de {_unir(nombres)}."


def _resumen_consulta(componente: Componente) -> str:
    cantidad = len(componente.columnas)
    if not componente.tablas:
        return f"Consulta sin tabla de origen. Devuelve {cantidad} expresiones."
    tablas = _unir([tabla.nombre for tabla in componente.tablas])
    return f"Consulta sobre {tablas}. Devuelve {cantidad} expresiones."


def _union_delegada(componente: Componente) -> Componente | None:
    if componente.clase == "union" or not _listas_vacias(componente):
        return None
    for hijo in componente.hijos:
        if hijo.clase == "union":
            return hijo
    return None


def _listas_vacias(componente: Componente) -> bool:
    return not (
        componente.tablas or componente.columnas or componente.clausulas or componente.relaciones
    )


def _tablas_de_ramas(componente: Componente) -> list[str]:
    nombres: list[str] = []
    for hijo in componente.hijos:
        if hijo.clase == "cte":
            continue
        if hijo.clase == "union":
            nombres.extend(_tablas_de_ramas(hijo))
            continue
        delegado = _union_delegada(hijo)
        if delegado is not None:
            nombres.extend(_tablas_de_ramas(delegado))
            continue
        nombres.extend(tabla.nombre for tabla in hijo.tablas)
    return nombres


def _es_union_all(componente: Componente) -> bool:
    nodo = componente._nodo
    if not isinstance(nodo, Nodo):
        return False
    return bloque(nodo).union_all is True


def _nombre_papel(componente: Componente, papel: str) -> str | None:
    for tabla in componente.tablas:
        if tabla.papel == papel and tabla.nombre:
            return tabla.nombre
    return None


def _texto(componente: Componente) -> str:
    nodo = componente._nodo
    if not isinstance(nodo, Nodo):
        return ""
    return normalizar(nodo, _DIALECTO)


def _nodo_desconocido(tipo: str, texto: str) -> str:
    return f"Esta parte es un nodo {tipo} y su texto es {texto}."


def _sin_prefijo(texto: str, nombre: str) -> str:
    prefijo = f"{nombre} "
    if texto.startswith(prefijo):
        return texto[len(prefijo) :]
    return texto


def _unir(nombres: list[str]) -> str:
    if len(nombres) == 1:
        return nombres[0]
    if len(nombres) == 2:
        return f"{nombres[0]} y {nombres[1]}"
    return f"{', '.join(nombres[:-1])} y {nombres[-1]}"
