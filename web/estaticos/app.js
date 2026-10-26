const formulario = document.querySelector("#formulario");
const vacio = document.querySelector("#vacio");
const errores = document.querySelector("#errores");
const resultado = document.querySelector("#resultado");
const ordenLogico = document.body.dataset.ordenLogico || "";

formulario.addEventListener("submit", (evento) => {
  evento.preventDefault();
  const sql = document.querySelector("#sql").value;
  const dialecto = document.querySelector("#dialecto").value;
  fetch("/analizar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sql: sql, dialecto: dialecto }),
  })
    .then((respuesta) => respuesta.json().then((cuerpo) => ({ ok: respuesta.ok, cuerpo: cuerpo })))
    .then((datos) => {
      limpiar();
      vacio.hidden = true;
      if (!datos.ok) {
        mostrarMensaje(datos.cuerpo && datos.cuerpo.mensaje);
        return;
      }
      pintarInforme(datos.cuerpo);
    })
    .catch(() => {
      limpiar();
      vacio.hidden = true;
      mostrarMensaje("No se ha podido leer la respuesta del servidor.");
    });
});

function limpiar() {
  errores.replaceChildren();
  resultado.replaceChildren();
}

function mostrarMensaje(mensaje) {
  const parrafo = document.createElement("p");
  parrafo.className = "error";
  parrafo.textContent = mensaje || "";
  errores.appendChild(parrafo);
}

function pintarInforme(informe) {
  const lista = informe.errores || [];
  for (const error of lista) {
    errores.appendChild(bloqueError(error));
  }
  const errorDeScript = lista.some((error) => error.sentencia == null);
  if (errorDeScript) {
    return;
  }
  for (const sentencia of informe.sentencias || []) {
    resultado.appendChild(bloqueSentencia(sentencia));
  }
}

function bloqueError(error) {
  const parrafo = document.createElement("p");
  parrafo.className = "error";
  parrafo.textContent = error.mensaje || "";
  if (error.linea != null || error.columna != null) {
    const donde = document.createElement("span");
    const partes = [];
    if (error.linea != null) {
      partes.push("línea " + error.linea);
    }
    if (error.columna != null) {
      partes.push("columna " + error.columna);
    }
    donde.textContent = " (" + partes.join(", ") + ")";
    parrafo.appendChild(donde);
  }
  return parrafo;
}

function bloqueSentencia(sentencia) {
  const articulo = document.createElement("article");
  articulo.className = "sentencia";

  const tipo = document.createElement("h2");
  tipo.textContent = sentencia.tipo || "";
  articulo.appendChild(tipo);

  if (sentencia.resumen) {
    const resumen = document.createElement("p");
    resumen.className = "resumen";
    resumen.textContent = sentencia.resumen;
    articulo.appendChild(resumen);
  }

  const pasos = document.createElement("section");
  pasos.className = "pasos";
  pasos.appendChild(listaTextos(sentencia.pasos));
  const frase = document.createElement("p");
  frase.className = "orden-logico";
  frase.textContent = ordenLogico;
  pasos.appendChild(frase);
  articulo.appendChild(pasos);

  const avisos = sentencia.advertencias || [];
  if (avisos.length) {
    const seccion = document.createElement("section");
    seccion.className = "advertencias";
    for (const aviso of avisos) {
      seccion.appendChild(bloqueAviso(aviso));
    }
    articulo.appendChild(seccion);
  }

  if (sentencia.arbol) {
    articulo.appendChild(nodoComponente(sentencia.arbol));
  }

  if (sentencia.sql_formateado != null) {
    articulo.appendChild(bloqueSql(sentencia.sql_formateado));
  }

  return articulo;
}

function bloqueAviso(aviso) {
  const parrafo = document.createElement("p");
  parrafo.className = "advertencia";
  const mensaje = document.createElement("span");
  mensaje.textContent = aviso.mensaje || "";
  parrafo.appendChild(mensaje);
  if (aviso.fragmento) {
    const fragmento = document.createElement("code");
    fragmento.textContent = aviso.fragmento;
    parrafo.appendChild(fragmento);
  }
  return parrafo;
}

function bloqueSql(sql) {
  const seccion = document.createElement("section");
  seccion.className = "sql";
  const pre = document.createElement("pre");
  pre.textContent = sql;
  const boton = document.createElement("button");
  boton.type = "button";
  boton.textContent = "Copiar";
  boton.addEventListener("click", () => {
    copiar(sql);
  });
  seccion.appendChild(pre);
  seccion.appendChild(boton);
  return seccion;
}

function nodoComponente(componente) {
  const details = document.createElement("details");
  details.className = "componente";
  const summary = document.createElement("summary");
  summary.textContent = tituloComponente(componente);
  details.appendChild(summary);
  details.appendChild(grupo("Tablas", componente.tablas, filaTabla));
  details.appendChild(grupo("Columnas", componente.columnas, filaColumna));
  details.appendChild(grupo("Cláusulas", componente.clausulas, filaClausula));
  details.appendChild(grupo("JOIN", componente.relaciones, filaRelacion));
  details.appendChild(grupo("Pasos", componente.pasos, filaTexto));
  const explicacion = document.createElement("p");
  explicacion.className = "explicacion";
  explicacion.textContent = componente.explicacion || "";
  details.appendChild(explicacion);
  for (const hijo of componente.hijos || []) {
    details.appendChild(nodoComponente(hijo));
  }
  return details;
}

function tituloComponente(componente) {
  const partes = [componente.clase, componente.tipo];
  if (componente.nombre) {
    partes.push(componente.nombre);
  }
  return partes.filter(Boolean).join(" · ");
}

function grupo(titulo, elementos, pintarFila) {
  const seccion = document.createElement("section");
  const encabezado = document.createElement("h3");
  encabezado.textContent = titulo;
  seccion.appendChild(encabezado);
  const lista = document.createElement("ul");
  for (const elemento of elementos || []) {
    lista.appendChild(pintarFila(elemento));
  }
  seccion.appendChild(lista);
  return seccion;
}

function listaTextos(textos) {
  const lista = document.createElement("ol");
  for (const texto of textos || []) {
    lista.appendChild(filaTexto(texto));
  }
  return lista;
}

function filaTexto(texto) {
  const item = document.createElement("li");
  item.textContent = texto;
  return item;
}

function filaTabla(tabla) {
  return filaConExplicacion([tabla.nombre, tabla.alias, tabla.papel], tabla.explicacion);
}

function filaColumna(columna) {
  return filaConExplicacion(
    [columna.expresion, columna.nombre, columna.papel, columna.certeza],
    columna.explicacion
  );
}

function filaClausula(clausula) {
  return filaConExplicacion([clausula.nombre, clausula.texto], clausula.explicacion);
}

function filaRelacion(relacion) {
  return filaConExplicacion(
    [relacion.tipo, relacion.izquierda, relacion.derecha, relacion.condicion],
    relacion.explicacion
  );
}

function filaConExplicacion(partes, explicacion) {
  const item = document.createElement("li");
  item.textContent = partes.filter(Boolean).join(" · ");
  if (explicacion) {
    const detalle = document.createElement("p");
    detalle.textContent = explicacion;
    item.appendChild(detalle);
  }
  return item;
}

function copiar(texto) {
  const portapapeles = navigator.clipboard;
  if (portapapeles && portapapeles.writeText) {
    portapapeles.writeText(texto);
    return;
  }
  const area = document.createElement("textarea");
  area.value = texto;
  document.body.appendChild(area);
  area.select();
  document.execCommand("copy");
  area.remove();
}
