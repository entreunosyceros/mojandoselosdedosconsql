from analizador.errores import DialectoNoSoportado
from analizador.mensajes import dialecto_no_soportado

_NOMBRES = {
    "postgresql": "postgres",
    "mysql": "mysql",
    "sqlite": "sqlite",
    "sqlserver": "tsql",
}


def nombre_interno(dialecto: str) -> str:
    try:
        return _NOMBRES[dialecto]
    except KeyError:
        raise DialectoNoSoportado(dialecto_no_soportado(dialecto)) from None
