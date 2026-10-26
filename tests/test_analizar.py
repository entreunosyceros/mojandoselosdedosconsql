import pytest

from analizador import analizar

COMUN = """
SELECT c.nombre, COUNT(p.id) AS total
FROM clientes AS c
INNER JOIN pedidos AS p ON p.cliente_id = c.id
WHERE c.activo = 1
GROUP BY c.nombre
"""
CASOS = {
    "postgresql": [
        COMUN,
        "SELECT nombre FROM clientes WHERE nombre ILIKE 'a%'",
        "INSERT INTO clientes (id) VALUES (1) ON CONFLICT (id) DO NOTHING",
        "WITH RECURSIVE c AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM c WHERE n < 3) SELECT n FROM c",
        "CREATE TABLE clientes (id INT)",
        "ALTER TABLE clientes ADD COLUMN activo BOOLEAN",
        "DROP TABLE clientes",
    ],
    "mysql": [
        COMUN,
        "SELECT `nombre` FROM `clientes`",
        "INSERT INTO clientes (id, nombre) VALUES (1, 'a') ON DUPLICATE KEY UPDATE nombre = 'b'",
        "WITH RECURSIVE c AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM c WHERE n < 3) SELECT n FROM c",
        "CREATE TABLE clientes (id INT)",
        "ALTER TABLE clientes ADD COLUMN activo BOOL",
        "DROP TABLE IF EXISTS clientes",
    ],
    "sqlite": [
        COMUN,
        'SELECT "nombre" FROM "clientes"',
        "WITH RECURSIVE c AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM c WHERE n < 3) SELECT n FROM c",
        "CREATE TABLE IF NOT EXISTS clientes (id INTEGER)",
        "ALTER TABLE clientes ADD COLUMN activo INTEGER",
        "DROP TABLE IF EXISTS clientes",
    ],
    "sqlserver": [
        COMUN,
        "SELECT TOP 1 [nombre] FROM [clientes]",
        "CREATE TABLE clientes (id INT, nombre NVARCHAR(20))",
        "ALTER TABLE clientes ADD activo BIT",
        "DROP TABLE clientes",
        "MERGE INTO clientes AS t USING (SELECT 1 AS id) AS s ON t.id = s.id WHEN MATCHED THEN UPDATE SET t.nombre = 'a';",
    ],
}
_EXTRA_POSTGRESQL = [
    "INSERT INTO clientes (id, nombre) VALUES (1, 'Ana')",
    "UPDATE clientes SET nombre = 'Ana' WHERE id = 1",
    "DELETE FROM clientes WHERE id = 1",
]


def _casos():
    for dialecto, sentencias in CASOS.items():
        for sql in sentencias:
            yield dialecto, sql
    for sql in _EXTRA_POSTGRESQL:
        yield "postgresql", sql


def _ctes(componente):
    if componente is None:
        return
    if componente.clase == "cte":
        yield componente.nombre
    for hijo in componente.hijos:
        yield from _ctes(hijo)


@pytest.mark.parametrize("dialecto,sql", list(_casos()))
def test_analiza_la_sentencia(dialecto, sql):
    informe = analizar(sql, dialecto)
    assert informe.errores == ()
    assert informe.sentencias
    for sentencia in informe.sentencias:
        assert sentencia.tipo
        if sql.lstrip().upper().startswith(("ALTER", "DROP", "MERGE")):
            assert sentencia.resumen is not None
            assert not sentencia.resumen.startswith("Consulta")
        if "WITH RECURSIVE" in sql:
            assert list(_ctes(sentencia.arbol)) == ["c"]
