# MojandoseLosDedosConSQL

<p align="center">
<img width="1249" height="1249" alt="Mojándose los dedos con SQL_sinfondo_sinfondo" src="https://github.com/user-attachments/assets/65fb80af-611c-45df-8506-89554c370d6c" />
</p>

Aplicación local que explica una sentencia SQL en español. Elige el dialecto, pega una o varias sentencias y obtienes un informe: errores de sintaxis, árbol de componentes, pasos en orden lógico, advertencias y el SQL formateado.

El programa no ejecuta el SQL ni abre conexiones. El análisis lo hace un núcleo determinista sobre SQLGlot 30.25.0.

Dialectos: PostgreSQL, MySQL, SQLite y SQL Server.

## Requisitos

Python 3.11 o superior.

## Uso

Desde la raíz del proyecto:

```bash
python run_app.py
```

La primera vez crea `.venv`, instala las dependencias ahí y abre http://127.0.0.1:8000/. El selector empieza en PostgreSQL. Para detenerlo, pulsa Ctrl+C.

Para arrancarla a mano, con el entorno ya creado:

```bash
.venv/bin/python -m uvicorn web.app:app --reload
```

La biblioteca también se puede usar sin la página:

```python
from analizador import analizar

informe = analizar("SELECT 1", "postgresql")
print(informe.a_dict())
```

Los dialectos aceptados son `postgresql`, `mysql`, `sqlite` y `sqlserver`.

## Pruebas

```bash
.venv/bin/python -m pytest
```

No hace falta una base de datos ni red.

