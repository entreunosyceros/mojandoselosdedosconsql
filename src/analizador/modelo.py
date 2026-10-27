from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any


def _serializar(valor: Any) -> Any:
    if hasattr(valor, "a_dict"):
        return valor.a_dict()
    if isinstance(valor, tuple):
        return [_serializar(elemento) for elemento in valor]
    return valor


class _Pieza:
    def a_dict(self) -> dict[str, Any]:
        return {
            campo.name: _serializar(getattr(self, campo.name))
            for campo in fields(self)
            if not campo.name.startswith("_")
        }


@dataclass(frozen=True)
class Error(_Pieza):
    mensaje: str
    linea: int | None
    columna: int | None
    sentencia: int | None


@dataclass(frozen=True)
class Advertencia(_Pieza):
    codigo: str
    gravedad: str
    mensaje: str
    componente_id: str
    fragmento: str


@dataclass(frozen=True)
class Tabla(_Pieza):
    nombre: str
    alias: str | None
    papel: str
    explicacion: str | None


@dataclass(frozen=True)
class Columna(_Pieza):
    expresion: str
    nombre: str | None
    calificador: str | None
    tabla: str | None
    certeza: str
    alias: str | None
    papel: str
    explicacion: str | None


@dataclass(frozen=True)
class Clausula(_Pieza):
    nombre: str
    texto: str
    explicacion: str | None


@dataclass(frozen=True)
class Relacion(_Pieza):
    tipo: str
    izquierda: str
    derecha: str
    condicion: str | None
    explicacion: str | None
    _forma: str | None = field(default=None, compare=False, hash=False, repr=False)


@dataclass(frozen=True)
class Componente(_Pieza):
    id: str
    clase: str
    nombre: str | None
    tipo: str
    tablas: tuple[Tabla, ...]
    columnas: tuple[Columna, ...]
    clausulas: tuple[Clausula, ...]
    relaciones: tuple[Relacion, ...]
    pasos: tuple[str, ...]
    hijos: tuple[Componente, ...]
    explicacion: str | None
    _nodo: object | None = field(default=None, compare=False, hash=False, repr=False)


@dataclass(frozen=True)
class Sentencia(_Pieza):
    indice: int
    tipo: str
    sql_formateado: str | None
    resumen: str | None
    pasos: tuple[str, ...]
    arbol: Componente | None
    advertencias: tuple[Advertencia, ...]


@dataclass(frozen=True)
class Informe(_Pieza):
    dialecto: str
    sql_original: str
    sentencias: tuple[Sentencia, ...]
    errores: tuple[Error, ...]
