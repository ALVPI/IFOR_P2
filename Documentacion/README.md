# Plantilla Modular en LaTeX — Informe Técnico Pericial

## Estructura de directorios

```text
plantilla_informe_pericial_latex/
├── main.tex                              # Documento maestro, variables del caso y ensamblaje
├── estilo_pericial.sty                   # Paquete de estilos (colores, márgenes, fuentes, encabezados y portada)
├── README.md                             # Guía rápida de compilación y uso
├── resources/                            # Logotipos, sellos, esquemas y capturas de evidencias
│   ├── logo_perito.png
│   └── logo_colegio.png
├── capitulos/                            # Secciones principales del dictamen pericial
│   ├── 00_resumen_ejecutivo.tex
│   ├── 01_introduccion.tex
│   ├── 02_consideraciones_generales.tex
│   ├── 03_consideraciones_especificas.tex
│   ├── 04_conclusiones.tex
│   ├── 05_metodologia.tex
│   └── 06_bibliografia.tex
└── anexos/                               # Evidencias digitales, cadenas de custodia y anexos técnicos
    ├── anexo_01_evidencias.tex
    └── anexo_02_capturas_y_logs.tex
```

## Cómo utilizar la plantilla

1. **Overleaf:** Sube directamente este archivo `.zip` mediante *New Project -> Upload Project*.
2. **Compilación local:** Ejecuta dos pasadas de `pdflatex` (o usa `latexmk -pdf main.tex`) para resolver el índice y el contador total de páginas (`LastPage`).
3. **Personalización visual:** Edita `estilo_pericial.sty` para modificar colores (`AzulPericial`, `GrisOscuro`), márgenes, tipografía, encabezados/pies de página o el diseño de la portada (`\GenerarPortadaPericial`).
4. **Datos del informe:** Modifica las variables `\renewcommand{\Cliente}{...}`, `\renewcommand{\Referencia}{...}`, etc. en `main.tex`.
