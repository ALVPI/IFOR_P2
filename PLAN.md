# Plan: Servidor de correo para el Escenario 1 (fuga por correo)

Práctica de Informática Forense — Grupo H. Documento para compartir entre
compañeros: aquí está todo el diseño acordado antes de implementar.

## Objetivo

Un sistema de correo propio para el **Escenario 1** del enunciado: sacar
`Confidencial.pdf` del Windows Server 2008 y **enviarlo por correo entre dos
miembros del grupo**, dejando evidencia analizable después.

Restricción acordada con el cliente:

- Compatible con Windows 10 / 11 (las VMs del laboratorio).
- Descargable del repositorio y ejecutable sin internet en las VMs.
- Código modular, documentado, con pruebas reproducibles.

## Decisiones técnicas (por qué)

| Decisión | Motivo |
|---|---|
| **Python 3, solo stdlib** (sin `pip`) | En las VMs no hay internet garantizado; `socket`, `email`, `http.server` bastan. `py -3 servidor.py` arranca en Windows. |
| **SMTP desde cero** (RFC 5321) | Es lo didáctico y lo que se evalúa: HELO/EHLO, MAIL, RCPT, DATA, códigos 2xx/4xx/5xx. Una librería (`aiosmtpd`) ocultaría el protocolo. |
| **Webmail con `http.server`** | Cubre lo esencial de "gmail" (bandeja, leer, descargar adjuntos, redactar) sin Flask ni dependencias. |
| **Sin autenticación** | Red de laboratorio cerrada; la seguridad pedida es anti-open-relay + validación de destinatarios + límites de conexión. |
| **Servidor en una VM Win10/11 dedicada** | Puertos 25 (SMTP) y 8080 (webmail) abiertos en la red NAT de VirtualBox ya configurada. |
| **Almacenamiento en ficheros** | `buzones/<usuario>/mensajes/*.eml` + `adjuntos/` extraídos: fácil de inspeccionar como evidencia. |

## Requisitos de seguridad (imprescindibles)

- **No open relay**: dominio de destino distinto del local → rechazo `554 5.7.1`.
- **Validar destinatarios**: buzón inexistente → `550 5.1.1`.
- **Limitar conexiones**: máximo simultáneo → `421 4.7.0` al excederlo.
- **Límite de tamaño** en `DATA` → `552 5.3.4`.
- Nombres de adjunto saneados (sin `..`, sin rutas) — evita path traversal.
- Webmail con HTML escapado (evita XSS básico en el laboratorio).

## Estructura prevista

```
servidor/                     # directorio nuevo; el LaTeX no se toca
├── servidor.py        # CLI: arrancar SMTP y/o webmail, alta/baja/listado de usuarios
├── config.py          # lectura de config.ini (puertos, dominio, límites)
├── srv_tcp.py         # bucle TCP, hilo por conexión, timeouts, límite de conexiones
├── smtp_sesion.py     # máquina de estados SMTP (el protocolo, desde cero)
├── correo_api.py      # construir/parsear MIME, extraer adjuntos, direcciones
├── buzon.py           # buzones .eml + adjuntos + usuarios.json (validación RCPT)
├── webmail.py         # http.server: bandeja, leer, descargar adjunto, redactar/enviar
├── plantillas/        # HTML simple (index, mensaje, redactar)
├── config.ini         # puerto 25, puerto 8080, dominio empresa.local, límites
├── arrancar.bat       # doble clic en la VM Windows
├── crear_usuario.bat  # alta de buzones en la VM
├── README.md          # guía completa: VMs, firewall, pruebas, escenario 1
└── tests/             # unittest (stdlib; funcionan igual en las VMs)
    ├── test_protocolo.py    # secuencia SMTP, errores de estado, RSET/NOOP/VRFY
    ├── test_seguridad.py    # open relay, RCPT desconocido, límites, adjuntos
    ├── test_correo.py       # MIME ida y vuelta, extracción de adjuntos
    └── test_webmail.py      # HTTP local: listar, leer, enviar con adjunto
```

## Iteraciones (cada una termina con pruebas en verde)

1. **Base TCP** — `srv_tcp.py` + `smtp_sesion.py` v1: saludo, HELO/EHLO,
   QUIT/NOOP/RSET, `500` a lo desconocido, `503` fuera de orden, timeouts.
2. **Máquina de estados SMTP** — MAIL/RCPT/DATA, anti open relay (`554`),
   RCPT desconocido (`550`), RSET limpia la transacción.
3. **Correo y buzones** — MIME, guardado `.eml`, extracción de adjuntos,
   CLI de usuarios.
4. **Límites y robustez** — `421` por conexiones, `552` por tamaño,
   desconexión a mitad de `DATA`, respuesta multilínea `250-`.
5. **Webmail** — bandeja, lectura con descarga de adjuntos, redactar con
   adjunto, entregado por la misma ruta que el SMTP.
6. **Documentación y VMs** — README con comandos exactos de Windows,
   reglas de firewall, `.bat`, y punto en AGENTS.md.

## Comandos clave

```sh
# Arrancar en la VM (Windows) — SMTP + webmail en foreground
py -3 servidor.py todo

# Gestión de usuarios
py -3 servidor.py usuario alta pepe
py -3 servidor.py usuario listar

# Pruebas (en cualquier SO, sin instalar nada)
cd servidor
python3 -m unittest discover -v
```

## Flujo real del Escenario 1

1. Arrancar `todo` en la VM Win10/11 del servidor de correo.
2. Crear dos buzones: `pepe@empresa.local` y `ana@empresa.local`.
3. En el Windows Server 2008: enviar `Confidencial.pdf` adjunto con cualquier
   cliente SMTP (o `telnet`/PowerShell) a `ana@empresa.local`.
4. Abrir el webmail en el navegador, descargar el adjunto y archivarlo como
   evidencia (junto con los `.eml` del servidor).
