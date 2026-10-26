import pytest

from analizador import analizar
from analizador.errores import DialectoNoSoportado
from analizador.formato import formatear as formatear_real


def test_dialecto_desconocido_no_devuelve_informe():
    with pytest.raises(DialectoNoSoportado) as error:
        analizar("SELECT 1", "excel")
    assert "excel" in str(error.value)


def test_consulta_vacia():
    informe = analizar("   ", "postgresql")
    assert informe.sentencias == ()
    assert informe.errores[0].mensaje == "La consulta está vacía."


def test_fallo_de_fase_no_filtra_la_excepcion(monkeypatch):
    def romper(nodo, dialecto):
        romper.veces += 1
        if romper.veces == 1:
            raise RuntimeError("fallo de prueba")
        return formatear_real(nodo, dialecto)

    romper.veces = 0
    monkeypatch.setattr("analizador.api.formatear", romper)
    informe = analizar("SELECT 1; SELECT 2", "postgresql")
    assert informe.errores[0].mensaje == (
        "No se ha podido formatear la sentencia 1 (Select). "
        "El detalle técnico quedó en el registro del servidor."
    )
    assert "fallo de prueba" not in informe.errores[0].mensaje
    assert informe.sentencias[1].sql_formateado is not None
