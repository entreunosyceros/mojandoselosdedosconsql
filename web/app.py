from __future__ import annotations

import json
import logging
from pathlib import Path

import jinja2
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from analizador.api import analizar
from analizador.errores import DialectoNoSoportado
from analizador.mensajes import (
    CONSULTA_NO_ES_TEXTO,
    CUERPO_NO_ES_JSON,
    FALTA_CONSULTA,
    FALTA_DIALECTO,
    ORDEN_LOGICO,
    consulta_demasiado_grande,
    dialecto_no_soportado,
    fallo_informe,
)

logger = logging.getLogger("web.app")

RAIZ = Path(__file__).resolve().parent
LIMITE_BYTES = 1048576
DIALECTOS = ("postgresql", "mysql", "sqlite", "sqlserver")

app = FastAPI()
plantillas = Jinja2Templates(
    env=jinja2.Environment(
        loader=jinja2.FileSystemLoader(RAIZ / "plantillas"),
        autoescape=True,
    )
)
app.mount(
    "/estaticos",
    StaticFiles(directory=RAIZ / "estaticos"),
    name="estaticos",
)


def _rechazo(estado: int, mensaje: str) -> JSONResponse:
    return JSONResponse(status_code=estado, content={"mensaje": mensaje})


@app.get("/", response_class=HTMLResponse)
def indice(request: Request) -> HTMLResponse:
    return plantillas.TemplateResponse(
        request,
        "index.html",
        {
            "orden_logico": ORDEN_LOGICO,
            "hay_logo": (RAIZ / "estaticos" / "logo.png").is_file(),
        },
    )


@app.post("/analizar")
async def analizar_peticion(request: Request):
    try:
        datos = json.loads(await request.body())
    except json.JSONDecodeError:
        return _rechazo(400, CUERPO_NO_ES_JSON)
    if not isinstance(datos, dict):
        return _rechazo(400, CUERPO_NO_ES_JSON)

    if "sql" not in datos or datos["sql"] is None:
        return _rechazo(400, FALTA_CONSULTA)
    if "dialecto" not in datos or datos["dialecto"] is None:
        return _rechazo(400, FALTA_DIALECTO)

    sql = datos["sql"]
    dialecto = datos["dialecto"]
    if not isinstance(sql, str):
        return _rechazo(400, CONSULTA_NO_ES_TEXTO)
    if not isinstance(dialecto, str) or dialecto not in DIALECTOS:
        valor = dialecto if isinstance(dialecto, str) else str(dialecto)
        return _rechazo(400, dialecto_no_soportado(valor))

    nbytes = len(sql.encode("utf-8"))
    if nbytes > LIMITE_BYTES:
        return _rechazo(400, consulta_demasiado_grande(nbytes))

    try:
        informe = analizar(sql, dialecto)
    except DialectoNoSoportado as exc:
        return _rechazo(400, str(exc))
    except Exception:
        mensaje = fallo_informe("el parseo")
        logger.exception("%s", mensaje)
        return _rechazo(500, mensaje)

    return informe.a_dict()
