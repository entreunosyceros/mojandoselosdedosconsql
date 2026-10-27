#!/usr/bin/env python3
"""Arranca el analizador dentro de su entorno virtual."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
VENV_DIR = PROJECT_DIR / ".venv"
URL = "http://127.0.0.1:8000/"


def get_venv_dir() -> Path:
    """Directorio del entorno virtual del proyecto."""
    return VENV_DIR


def get_venv_python() -> Path:
    """Ejecutable de Python dentro del entorno virtual."""
    if sys.platform == "win32":
        return get_venv_dir() / "Scripts" / "python.exe"
    return get_venv_dir() / "bin" / "python"


def is_running_in_venv() -> bool:
    """
    Comprueba si el intérprete actual es el del entorno del proyecto.

    Se compara sys.prefix, no sys.executable: en Linux el Python del
    entorno suele ser un enlace al del sistema y ambos resolverían igual.
    """
    if not get_venv_dir().exists():
        return False
    return Path(sys.prefix).resolve() == get_venv_dir().resolve()


def create_venv() -> None:
    """Crea el entorno virtual con el Python que lanzó este archivo."""
    if sys.version_info < (3, 11):
        raise RuntimeError("Hace falta Python 3.11 o superior para crear el entorno.")
    print(f"Creando el entorno virtual en {get_venv_dir()} …", flush=True)
    subprocess.run(
        [sys.executable, "-m", "venv", str(get_venv_dir())],
        check=True,
        cwd=PROJECT_DIR,
    )
    print("Entorno virtual creado.", flush=True)


def ensure_venv() -> Path:
    """Garantiza que existe .venv y devuelve su ejecutable de Python."""
    venv_python = get_venv_python()
    if not venv_python.exists():
        create_venv()
        venv_python = get_venv_python()
    if not venv_python.exists():
        raise RuntimeError("No se pudo crear el entorno virtual.")
    return venv_python


def dependencias_listas(python: Path) -> bool:
    """Comprueba que el entorno puede importar la aplicación."""
    comprobacion = "import analizador, fastapi, jinja2, sqlglot, uvicorn"
    resultado = subprocess.run(
        [str(python), "-c", comprobacion],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
    )
    return resultado.returncode == 0


def install_dependencies(venv_python: Path) -> None:
    """Instala el proyecto y sus dependencias dentro del entorno virtual."""
    print("Instalando dependencias en el entorno virtual …", flush=True)
    subprocess.run(
        [str(venv_python), "-m", "pip", "install", "-q", "--upgrade", "pip"],
        check=True,
        cwd=PROJECT_DIR,
    )
    subprocess.run(
        [str(venv_python), "-m", "pip", "install", "-e", ".[dev]"],
        check=True,
        cwd=PROJECT_DIR,
    )
    print("Dependencias instaladas.", flush=True)


def _abrir_navegador() -> None:
    """Abre la página cuando el servidor responde."""
    for _ in range(50):
        try:
            with urllib.request.urlopen(URL, timeout=0.5) as respuesta:
                if respuesta.status == 200:
                    webbrowser.open(URL)
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.2)


def launch_app() -> None:
    """Arranca la página con el Python del entorno virtual."""
    import uvicorn

    print(f"Analizador SQL en {URL}", flush=True)
    print("Pulsa Ctrl+C para detenerlo.", flush=True)
    threading.Thread(target=_abrir_navegador, daemon=True).start()
    uvicorn.run(
        "web.app:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )


def main() -> int:
    """Prepara el entorno virtual y arranca la aplicación."""
    os.chdir(PROJECT_DIR)
    if str(PROJECT_DIR) not in sys.path:
        sys.path.insert(0, str(PROJECT_DIR))

    try:
        if is_running_in_venv():
            if not dependencias_listas(Path(sys.executable)):
                install_dependencies(Path(sys.executable))
            launch_app()
            return 0

        venv_python = ensure_venv()
        if not dependencias_listas(venv_python):
            install_dependencies(venv_python)

        print("Iniciando el analizador …", flush=True)
        os.execv(str(venv_python), [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]])
    except subprocess.CalledProcessError as exc:
        print(f"No se pudo preparar el entorno: {exc}", file=sys.stderr)
        print(
            "Puedes rehacerlo a mano:\n"
            "  python -m venv .venv\n"
            "  .venv/bin/python -m pip install -e \".[dev]\"\n"
            "  .venv/bin/python -m uvicorn web.app:app --reload",
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        print("\nAplicación detenida.")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
