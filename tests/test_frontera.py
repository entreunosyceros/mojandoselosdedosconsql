import ast
from pathlib import Path


def test_ningun_modulo_de_fase_importa_sqlglot():
    raiz = Path("src/analizador")
    prohibidos = [
        "semantica.py",
        "explicacion.py",
        "advertencias.py",
        "formato.py",
        "api.py",
        "modelo.py",
        "dialectos.py",
        "mensajes.py",
        "errores.py",
    ]
    for nombre in prohibidos:
        arbol = ast.parse((raiz / nombre).read_text())
        importados = [
            nodo.names[0].name if hasattr(nodo, "names") else nodo.module
            for nodo in ast.walk(arbol)
            if isinstance(nodo, (ast.Import, ast.ImportFrom))
        ]
        assert "sqlglot" not in importados
