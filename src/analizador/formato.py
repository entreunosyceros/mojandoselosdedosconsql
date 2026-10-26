from analizador.parser import normalizar


def formatear(nodo, dialecto: str) -> str:
    return normalizar(nodo, dialecto)
