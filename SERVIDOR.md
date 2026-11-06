# Servidor de correo para el Escenario 1 (fuga por correo)

Documento técnico que explica **cómo se ha programado** el servidor de correo del
grupo y **por qué se adapta** a lo exigido por el enunciado de la práctica de
Informática Forense (Escenario 1: fuga de información por correo electrónico).

> Ficheros relacionados: `PLAN.md` (diseño acordado), `GUIA_USO.md` (guía sencilla
> para los compañeros), `servidor/README.md` (referencia técnica completa) y
> `AGENTS.md` (convenciones del repositorio).

---

## 1. Qué pide el enunciado

El enunciado (`Enunciado.pdf`) plantea tres escenarios de fuga de información.
En todos ellos el fichero original es `Confidencial.pdf`, que reside en un
**Windows Server 2008**. El **Escenario 1** consiste en:

- sacar `Confidencial.pdf` del servidor y **enviarlo por correo electrónico**
  entre **dos miembros del grupo**;
- el estudio y la documentación de la evidencia la realiza **solo uno** de ellos;
- recopilar las evidencias realizando las **imágenes correspondientes sin
  modificarlas**;
- elaborar la **cadena de custodia**, suponiendo que el director de la empresa
  (Jaime Diez Zurro) ha entregado los soportes al grupo.

Por tanto, el sistema de correo debe permitir, en una red de laboratorio
cerrada (VMs de VirtualBox), **enviar un adjunto entre dos buzones del grupo**
y **conservar toda la evidencia** (mensaje completo, adjunto extraído, trazas de
origen) para su posterior análisis forense.

---

## 2. Objetivo del servidor

Construir un **sistema de correo propio** (SMTP + webmail) que:

1. permita enviar `Confidencial.pdf` como adjunto entre dos buzones del grupo
   (`pepe@empresa.local` → `ana@empresa.local`);
2. deje **evidencia analizable** en disco (`.eml` completo con cabecera
   `Received`, adjunto extraído, log de auditoría);
3. sea **ejecutable sin internet** en las VMs Windows 10/11 del laboratorio;
4. sea **didáctico**: el protocolo SMTP se implementa desde cero (RFC 5321),
   que es justo lo que se evalúa en la práctica.

---

## 3. Decisiones técnicas y por qué

| Decisión | Motivo |
|---|---|
| **Python 3, solo stdlib** (sin `pip`) | En las VMs no hay internet garantizado; `socket`, `email` y `http.server` bastan. Se arranca con `py -3 servidor.py` en Windows. |
| **SMTP desde cero** (RFC 5321) | Es lo didáctico y lo evaluado: HELO/EHLO, MAIL, RCPT, DATA y los códigos 2xx/4xx/5xx. Una librería (`aiosmtpd`) ocultaría el protocolo. |
| **Webmail con `http.server`** | Cubre lo esencial de un "Gmail" (bandeja, leer, descargar adjuntos, redactar) sin Flask ni dependencias. |
| **Sin autenticación** | Red de laboratorio cerrada; la seguridad pedida es anti-open-relay + validación de destinatarios + límites de conexión. |
| **Servidor en una VM Win10/11 dedicada** | Puertos 25 (SMTP) y 8080 (webmail) en la red NAT de VirtualBox ya configurada. |
| **Almacenamiento en ficheros** | `buzones/<usuario>/mensajes/*.eml` + `adjuntos/` extraídos: fácil de inspeccionar como evidencia. |
| **Pruebas con `unittest` (stdlib)** | Sin `pytest` ni red externa; funcionan igual en las VMs. |

---

## 4. Arquitectura y módulos

El código vive en `servidor/` y es **modular**, con responsabilidades bien
separadas (cada módulo hace una sola cosa):

```
servidor/
├── servidor.py     CLI: smtp | todo | usuario alta|baja|listar
├── config.py       lectura de config.ini (puertos, dominio, límites)
├── srv_tcp.py      aceptación TCP, hilo por conexión, límites, timeouts
├── smtp_sesion.py  la máquina de estados SMTP (el protocolo, desde cero)
├── correo_api.py   direcciones, construcción MIME, extracción de adjuntos
├── buzon.py        buzones .eml + adjuntos + usuarios.json (+ lock)
├── log_envios.py   auditoría: una línea por envío en logs/envios.log
├── webmail.py      interfaz web con http.server (solo stdlib)
├── plantillas/     HTML del webmail (string.Template)
├── config.ini      configuración editable
├── arrancar.bat    doble clic en la VM Windows
├── crear_usuario.bat
└── tests/          unittest (84 pruebas)
```

### Flujo de una entrega

1. El cliente (telnet, cliente SMTP o webmail) se conecta al puerto 25.
2. `srv_tcp.ServidorTCP` acepta la conexión en un **hilo por cliente**, aplica
   el límite de conexiones simultáneas y el timeout de inactividad.
3. `smtp_sesion.SesionSMTP` ejecuta la **máquina de estados** SMTP:
   `inicio → saludado → mail → rcpt → dato → saludado`.
4. Al recibir `DATA`, se valida el tamaño; si es válido se prepende una
   cabecera `Received` (origen, HELO, fecha) y se entrega vía
   `buzon.Buzones.entregar`.
5. `entregar` guarda el `.eml` en cada buzón destino, extrae los adjuntos a
   disco y registra una línea en `logs/envios.log`.
6. El webmail (`webmail.py`) usa **la misma ruta de entrega** (`entregar`),
   de modo que SMTP y webmail convergen en un único punto de entrega.

---

## 5. Protocolo SMTP implementado desde cero

El módulo `smtp_sesion.py` implementa RFC 5321 sin librerías externas:

- **Saludo** `220 empresa.local ESMTP Practica IFOR`.
- **HELO/EHLO**: EHLO responde multilínea (`250-` continúa, `250 ` termina)
  anunciando `8BITMIME` y `SIZE <límite>` (anuncio del límite de tamaño).
- **Comandos de sesión**: `NOOP`, `RSET`, `QUIT`, `VRFY` (aceptados en
  cualquier momento, incluso antes del HELO, como en servidores reales).
- **Transacción**: `MAIL FROM:<dir>`, `RCPT TO:<dir>` (varios destinatarios),
  `DATA` con terminador `<CRLF>.<CRLF>`.
- **Códigos de error**: `500` (desconocido/línea larga), `501` (sintaxis),
  `503` (fuera de orden), `550` (destinatario desconocido), `554` (relay
  denegado), `552` (mensaje demasiado grande), `421` (sin huecos/timeout).
- **Robustez**: dot-unstuffing (RFC 4.5.2), drenado hasta el `.` final tras
  exceder el límite (evita desincronizar la sesión), protección frente a
  líneas gigantes sin CRLF (límite de memoria), recuperación ante
  desconexión a mitad de `DATA`.

---

## 6. Seguridad (requisitos imprescindibles del plan)

El plan (`PLAN.md`) fijó estos requisitos y todos están implementados y
cubiertos por pruebas:

1. **No open relay**: dominio de destino distinto del local → rechazo
   `554 5.7.1`. (`smtp_sesion._cmd_rcpt`, `webmail._enviar`)
2. **Validar destinatarios**: buzón inexistente → `550 5.1.1`.
   (`Buzones.existe`)
3. **Limitar conexiones**: máximo simultáneo → `421 4.7.0` al excederlo.
   (`ServidorTCP._bucle_aceptar`)
4. **Límite de tamaño en DATA** → `552 5.3.4`. (`_recibir_data`)
5. **Nombres de adjunto saneados** (sin `..`, sin rutas) — evita path
   traversal. (`correo_api.nombre_seguro`)
6. **Webmail con HTML escapado** (evita XSS básico). (`webmail._esc`)
7. **Ids de mensaje seguros** (regex `^[A-Za-z0-9_-]{1,64}$`): imposible
   salirse de la carpeta `mensajes/`. (`buzon.RE_MSG_ID`)
8. **Usuarios seguros** (regex `^[A-Za-z0-9._-]{1,64}$`): evita
   `../../etc/passwd` en la ruta del buzón. (`buzon.RE_USUARIO`)
9. **Sin inyección de cabeceras** en el webmail: `_sin_saltos` elimina CR/LF
   del asunto. (`webmail._sin_saltos`)
10. **Adjuntos servidos solo por índice numerado** (nunca se compone una ruta
    con datos del cliente). (`webmail._vista_adjunto`)
11. **Límite de tamaño en el POST** del webmail → `413`. (`_leer_formulario`)
12. **El emisor del webmail debe ser un buzón real** (el campo oculto no es
    identidad fiable). (`webmail._enviar`)

---

## 7. Almacenamiento y evidencias (cadena de custodia)

El almacenamiento es **en ficheros**, fácil de inspeccionar y de archivar como
evidencia:

```
buzones/
  ana/
    mensajes/20261102-153012-ab12cd34.eml   # mensaje completo (headers + cuerpo)
    adjuntos/20261102-.../Confidencial.pdf    # adjunto extraído
```

- Cada mensaje se guarda como **`.eml`** (mensaje MIME completo con todas las
  cabeceras, incluida `Received` con la IP de origen, el HELO y la fecha).
- Los **adjuntos se extraen** a una carpeta por mensaje, con nombres saneados,
  de modo que un `.pdf` se abre sin parsear el `.eml`.
- El identificador de cola (`cola_id`) tiene resolución de segundo + UUID
  corto: `20261102153012-ab12cd34`.
- `usuarios.json` guarda la lista de buzones (`{"usuarios": [...]}`).
- `buzones/`, `usuarios.json` y `logs/` son **datos runtime** (`.gitignore`):
  no se versionan, son propios de cada VM.

Esto encaja con el enunciado: la evidencia se recopila **sin modificarla** y
queda lista para la cadena de custodia.

---

## 8. Webmail

`webmail.py` implementa un webmail mínimo sobre `http.server` (solo stdlib):

- `/` — elige buzón / muestra la bandeja.
- `/mensaje?u&id` — ver un mensaje + enlaces a sus adjuntos.
- `/adjunto?u&id&n` — descargar el enésimo adjunto extraído.
- `/redactar?u` — formulario de envío con campo de adjunto.
- `/enviar` (POST) — entrega por la **misma ruta interna** que el SMTP
  (`buzon.entregar`), validando destinos igual (anti-relay).

Decisiones de laboratorio: **no hay autenticación** (decisión acordada); no
exponer el puerto 8080 fuera de la red NAT de VirtualBox.

---

## 9. Log de envíos (auditoría)

Cada mensaje entregado — por **SMTP o por el webmail** — añade **una única
línea** a `logs/envios.log`:

```
2026-11-05T10:00:00 | de: pepe@empresa.local | para: ana@empresa.local, luis@empresa.local | asunto: Examen final | adjuntos: Confidencial.pdf (123 KB), notas.txt (4 KB)
```

- Timestamp ISO 8601 en hora local (segundos).
- `para`: destinatarios en el orden aceptado (RCPT TO / lista del formulario).
- `adjuntos`: nombres saneados con tamaño redondeado a KB (mínimo 1 KB); si no
  hay, `adjuntos: ninguno`.
- **Escaping**: si el asunto o un nombre contiene ` | ` (o cualquier `|`),
  se sustituye por `¦` (U+00A6), de modo que cada envío es **exactamente una
  línea** jamás rota.
- El fichero **crece por anexión** (nunca se reescribe); la escritura va
  protegida con lock y `try/except`: un fallo del log (disco lleno,
  permisos…) queda en el logger `correo.log_envios` pero **nunca tumba** el
  envío ni la sesión.

El directorio del log es configurable en `config.ini` (`[log] directorio`),
por defecto `logs/` relativo a `servidor/`.

---

## 10. Pruebas reproducibles

```sh
cd servidor
python3 -m unittest discover -v        # o: py -3 -m unittest discover -v
```

**84 pruebas** en verde: protocolo (secuencia SMTP, errores de estado,
RSET/NOOP/VRFY), seguridad (anti-open-relay, RCPT desconocido, límites,
adjuntos), MIME/adjuntos, webmail (XSS, 413, ids seguros), log de envíos y
arranque combinado `todo`. Sin red externa ni privilegios: todo se monta en
`127.0.0.1` con puertos efímeros y buzones temporales.

---

## 11. Cómo se adapta al Escenario 1 (paso a paso)

1. Arrancar `todo` en la VM Win10/11 del servidor de correo.
2. Crear dos buzones: `pepe@empresa.local` y `ana@empresa.local`.
3. En el Windows Server 2008: enviar `Confidencial.pdf` adjunto con cualquier
   cliente SMTP (o telnet/PowerShell) a `ana@empresa.local`.
4. Evidencias que quedan en el servidor:
   - `servidor/buzones/ana/mensajes/<id>.eml` — mensaje completo con la
     cabecera `Received` (origen, HELO, fecha);
   - `servidor/buzones/ana/adjuntos/<id>/Confidencial.pdf` — el adjunto
     extraído, listo para imagen y cadena de custodia;
   - `servidor/logs/envios.log` — línea de auditoría del envío.
5. En el webmail, bandeja de `ana` → abrir → descargar adjunto.
6. Archivar todo (imágenes de disco) **sin modificar** y elaborar la cadena
   de custodia.

Esto cubre exactamente lo que pide el enunciado: sacar `Confidencial.pdf` del
Windows Server 2008, enviarlo por correo entre dos miembros del grupo y
conservar la evidencia analizable.

---

## 12. Limitaciones y aviso de laboratorio

- **No hay autenticación** (decisión de la práctica): cualquiera en la red del
  laboratorio puede leer las bandejas. No exponer el puerto 8080 fuera de la
  red NAT de VirtualBox.
- No se soporta IMAP/POP3 ni TLS: el sistema es SMTP (enviar) + webmail
  (leer). Si el grupo lo necesita, se puede añadir después.
- El puerto 25 requiere **privilegios de administrador** en Windows; para
  probar sin ellos, usar `--puerto 2525`.
- `buzones/`, `usuarios.json` y `logs/` son datos runtime y no se versionan.

---

## 13. Comandos clave

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

Más detalles técnicos: `servidor/README.md`. Diseño e iteraciones:
`PLAN.md`. Guía sencilla: `GUIA_USO.md`.
