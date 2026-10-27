import ast
from pathlib import Path

from fastapi.testclient import TestClient

from analizador.mensajes import (
    CONSULTA_NO_ES_TEXTO,
    CUERPO_NO_ES_JSON,
    FALTA_CONSULTA,
    consulta_demasiado_grande,
    dialecto_no_soportado,
    fallo_informe,
)
from web.app import app

cliente = TestClient(app)
RAIZ = Path(__file__).resolve().parents[1]


def test_formulario_muestra_los_cuatro_dialectos():
    respuesta = cliente.get("/")
    assert respuesta.status_code == 200
    for nombre in ("PostgreSQL", "MySQL", "SQLite", "SQL Server"):
        assert nombre in respuesta.text


def test_estado_inicial_y_valores_del_selector():
    respuesta = cliente.get("/")
    texto = respuesta.text
    assert "Elige un dialecto y pega la sentencia." in texto
    assert 'value="postgresql"' in texto
    assert 'value="mysql"' in texto
    assert 'value="sqlite"' in texto
    assert 'value="sqlserver"' in texto
    assert texto.index('value="postgresql"') < texto.index('value="mysql"')
    assert texto.index('value="mysql"') < texto.index('value="sqlite"')
    assert texto.index('value="sqlite"') < texto.index('value="sqlserver"')
    assert "Analizar" in texto
    assert "/estaticos/estilo.css" in texto
    assert "/estaticos/app.js" in texto
    assert 'rel="icon" href="/estaticos/logo.png"' in texto


def test_post_devuelve_el_informe():
    respuesta = cliente.post("/analizar", json={"sql": "SELECT 1", "dialecto": "postgresql"})
    assert respuesta.status_code == 200
    assert respuesta.json()["sentencias"][0]["tipo"] == "Select"


def test_dialecto_ausente():
    respuesta = cliente.post("/analizar", json={"sql": "SELECT 1"})
    assert respuesta.status_code == 400
    assert respuesta.json()["mensaje"] == "Falta el dialecto. Elige PostgreSQL, MySQL, SQLite o SQL Server."


def test_consulta_grande():
    respuesta = cliente.post(
        "/analizar",
        json={"sql": "a" * 1048577, "dialecto": "postgresql"},
    )
    assert respuesta.status_code == 400
    assert respuesta.json()["mensaje"] == consulta_demasiado_grande(1048577)
    assert "1048576" in respuesta.json()["mensaje"]


def test_cuerpo_no_es_json():
    respuesta = cliente.post(
        "/analizar",
        content="no-json",
        headers={"Content-Type": "application/json"},
    )
    assert respuesta.status_code == 400
    assert respuesta.json()["mensaje"] == CUERPO_NO_ES_JSON


def test_consulta_ausente():
    respuesta = cliente.post("/analizar", json={"dialecto": "postgresql"})
    assert respuesta.status_code == 400
    assert respuesta.json()["mensaje"] == FALTA_CONSULTA


def test_consulta_no_es_texto():
    respuesta = cliente.post("/analizar", json={"sql": 1, "dialecto": "postgresql"})
    assert respuesta.status_code == 400
    assert respuesta.json()["mensaje"] == CONSULTA_NO_ES_TEXTO


def test_dialecto_desconocido():
    respuesta = cliente.post("/analizar", json={"sql": "SELECT 1", "dialecto": "excel"})
    assert respuesta.status_code == 400
    assert respuesta.json()["mensaje"] == dialecto_no_soportado("excel")


def test_error_interno_no_sale_en_el_cuerpo(monkeypatch, caplog):
    def romper(sql, dialecto):
        raise RuntimeError("fallo de prueba")

    monkeypatch.setattr("web.app.analizar", romper)
    with caplog.at_level("ERROR", logger="web.app"):
        respuesta = cliente.post("/analizar", json={"sql": "SELECT 1", "dialecto": "postgresql"})
    assert respuesta.status_code == 500
    assert respuesta.json()["mensaje"] == fallo_informe("el parseo")
    assert "fallo de prueba" not in respuesta.text
    assert "fallo de prueba" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "Traceback" in caplog.text


def test_el_script_no_usa_innerhtml():
    assert "innerHTML" not in open("web/estaticos/app.js", encoding="utf-8").read()


def test_el_script_pide_el_informe_con_fetch_y_textcontent():
    script = (RAIZ / "web/estaticos/app.js").read_text(encoding="utf-8")
    assert "fetch" in script
    assert "textContent" in script
    assert "Copiar" in script


def test_estaticos_montados():
    assert cliente.get("/estaticos/estilo.css").status_code == 200
    assert cliente.get("/estaticos/app.js").status_code == 200
    assert cliente.get("/estaticos/logo.png").status_code == 200


def test_la_plantilla_tiene_autoescape():
    from web.app import plantillas

    assert plantillas.env.autoescape is True


def test_web_no_importa_sqlglot():
    for ruta in (RAIZ / "web").rglob("*.py"):
        arbol = ast.parse(ruta.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Import):
                modulos = [alias.name.split(".")[0] for alias in nodo.names]
            elif isinstance(nodo, ast.ImportFrom) and nodo.module:
                modulos = [nodo.module.split(".")[0]]
            else:
                continue
            assert "sqlglot" not in modulos
