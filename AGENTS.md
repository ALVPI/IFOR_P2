# AGENTS.md

Práctica 2 de Informática Forense (Grupo H): documentación LaTeX sobre 3 escenarios de vulnerabilidad. **No hay código, tests, lint ni CI**; la única verificación posible es compilar el PDF sin errores.

## Estructura

- `Documentacion/main.tex` — único punto de entrada. Todo se compila desde ahí con rutas relativas (`bib/`, `styles/`, `frontmatter/`, `capitulos/`): **compilar desde `Documentacion/`, nunca desde la raíz**.
- `Documentacion/capitulos/NN_tema.tex` — capítulos (solo contenido); `frontmatter/` — resumen/abstract/agradecimientos; `apendices/` — vacío; `bib/refs.bib` — referencias; `Recursos/` — figuras (fuentes SVG + exportes PDF/PNG).
- `Documentacion/styles/mistilo.sty` — **todo el diseño** (portada, cabeceras, márgenes, entornos como `aviso`). Regla del repo: si no es contenido, va en el `.sty`; los `.tex` de capítulos llevan solo texto. El `.sty` documenta sus propias opciones.
- `Enunciado.pdf` — enunciado de la práctica. `resumen_configuracion_ws2008_entorno_forense_md.md` — notas de lab del escenario WS2008 (red NAT, SMB, permisos).

## Compilar

```sh
cd Documentacion
pdflatex -interaction=nonstopmode main
biber main
pdflatex -interaction=nonstopmode main
pdflatex -interaction=nonstopmode main
```

- Hacen falta las 4 pasadas (biber + referencias cruzadas + índice): sin ellas salen `[?]` en las citas y el índice desactualizado. No hay Makefile ni latexmk configurado.
- Éxito = código de salida 0 **y** `grep '^!' main.log` vacío. Salida: `Documentacion/main.pdf`.
- Si aparece `! LaTeX Error: Missing \begin{document}` apuntando al preámbulo de `main.tex`, es casi seguro que `\titulodoc[corto]{largo}` perdió su argumento obligatorio `{...}` (ambos son obligatorios: el corto es opcional, el largo no).

## Convenciones que no son obvias

- **Añadir un capítulo**: crear `capitulos/NN_xxx.tex` que empiece por `\chapter{...}` **y** añadir `\include{capitulos/NN_xxx}` en `main.tex` antes de `\appendix`. Hoy **no hay ningún `\include` de capítulos** en `main.tex` (solo `\input` de frontmatter): sin ese paso, el capítulo existe en el repo pero no sale en el PDF. Los nombres de directorio no llevan tilde (`capitulos`, `apendices`).
- **Compilar un solo capítulo**: descomentar `\includeonly{capitulos/NN_xxx}` en `main.tex` y volver a comentarlo al terminar (el ejemplo del comentario apunta a un capítulo de plantilla que no existe).
- **babel**: `main.tex` carga `[english,spanish]`; el **último idioma de la lista es el principal**. El abstract usa `\begin{otherlanguage}{english}` — no quitar `english` ni reordenar sin motivo.
- **Citas**: clave inexistente en `bib/refs.bib` → `[?]`. Las reglas de formato de entradas (separador `and` entre autores, tildes `{\'a}`, convención de clave `primerAutor+año+palabra`) están documentadas en los comentarios del propio `refs.bib`.
- **PDFs nuevos**: `Documentacion/.gitignore` ignora `*.pdf` y solo excede `figuras/`, `images/` y `assets/` (rutas que no existen). Un PDF nuevo en `Recursos/` **no se añade con `git add` normal**: usar `git add -f Documentacion/Recursos/xxx.pdf`. Los SVG/PNG no están ignorados.

## Sistema de correo (`servidor/`)

- **Python 3 SOLO stdlib, sin `pip`** (decisión de diseño: las VMs no tienen
  internet). No añadir dependencias externas; `pytest` tampoco: las pruebas
  son `unittest`.
- Verificación obligatoria tras cualquier cambio:

  ```sh
  cd servidor && python3 -m unittest discover -v   # 72 pruebas
  ```

- CLI: `python3 servidor.py todo` (SMTP + webmail) · `usuario alta|baja|listar` ·
  `smtp --puerto 2525` para probar sin administrador. Detalles, firewall y
  diálogo SMTP de prueba: `servidor/README.md`.
- Diseño e iteraciones acordadas: `PLAN.md` (raíz). Código y comentarios en
  español, igual que el resto del repo.
- Runtime no versionado (`servidor/.gitignore`): `buzones/`, `usuarios.json`,
  `__pycache__/` — los buzones son evidencia generada en cada VM.

## Git

- Los artefactos de compilación (`main.pdf`, `main.aux`, `main.log`, `main.toc`, `main.synctex.gz`...) están fuera del índice y cubiertos por `.gitignore`: **no hacer `git add` de `main.*`** salvo `main.tex`. Tras compilar, `git status` debe seguir limpio.
- Historial en español con prefijo convencional tipo `docs:`; los mensajes y comentarios del repo también están en español.
