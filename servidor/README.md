# Servidor de correo — Práctica IFOR (Escenario 1)

> ¿Solo quieres usarlo? Ve a la **[Guía de uso en lenguaje sencillo](../GUIA_USO.md)**.
> Este README es la referencia técnica.

Servidor SMTP **escrito desde cero** (RFC 5321, solo Python, sin dependencias)
más un **webmail** mínimo para leer los mensajes y descargar adjuntos.
Pensado para el Escenario 1 de la práctica: enviar `Confidencial.pdf` por
correo entre dos buzones del grupo y conservar las evidencias.

## Requisitos

- **Python 3.9 o superior** en la VM Windows 10/11 (o GNU/Linux/macOS).
- Nada más: ni `pip install`, ni internet. Todo es estándar de la biblioteca.
- `py -3` (el launcher de Windows) o `python` en el PATH.

## Puesta en marcha en Windows 10/11

1. Copia la carpeta `servidor/` a la VM (o clona el repositorio).
2. Crea los buzones:

   ```bat
   py -3 servidor.py usuario alta pepe
   py -3 servidor.py usuario alta ana
   py -3 servidor.py usuario listar
   ```

3. Arranca (doble clic en `arrancar.bat`, o en una consola **como
   Administrador**):

   ```bat
   py -3 servidor.py todo
   ```

   Verás:

   ```text
   SMTP    escuchando en 0.0.0.0:25 (dominio empresa.local)
   Webmail en  http://0.0.0.0:8080/
   ```

4. Abre el firewall para las VMs (misma red NAT de VirtualBox que ya usáis
   para SMB), **como Administrador**:

   ```bat
   netsh advfirewall firewall add rule name="Correo IFOR SMTP" dir=in action=allow protocol=TCP localport=25
   netsh advfirewall firewall add rule name="Correo IFOR web" dir=in action=allow protocol=TCP localport=8080
   ```

> El **puerto 25 requiere privilegios de administrador** en Windows. Para
> probar sin administrador usa `py -3 servidor.py todo --puerto 2525` y
> apunta a ese puerto en las pruebas.

## Probar el SMTP a mano (telnet o PowerShell)

Desde la otra VM (sustituye la IP por la del servidor de correo):

```text
C:\> telnet 192.168.255.X 25
220 empresa.local ESMTP Practica IFOR
HELO cliente
250 empresa.local
MAIL FROM:<pepe@empresa.local>
250 2.1.0 Ok
RCPT TO:<ana@empresa.local>
250 2.1.5 Ok
DATA
354 Introduzca el mensaje; termine con <CRLF>.<CRLF>
Subject: Prueba
Hola, esto es una prueba.

.
250 2.0.0 Ok: queue ... para ana@empresa.local
QUIT
221 2.0.0 empresa.local cerrando
```

Si `telnet` no está instalado, actívalo en «Características de Windows» →
«Cliente Telnet», o usa PowerShell:

```powershell
$c = New-Object Net.Sockets.TcpClient("192.168.255.X", 25)
$s = $c.GetStream(); $r = New-Object IO.StreamReader($s)
$w = New-Object IO.StreamWriter($s); $w.AutoFlush = $true
$r.ReadLine()          # 220
$w.WriteLine("HELO prueba"); $r.ReadLine()
$w.WriteLine("MAIL FROM:<pepe@empresa.local>"); $r.ReadLine()
$w.WriteLine("RCPT TO:<ana@empresa.local>"); $r.ReadLine()
```

## Webmail

Navegador en cualquier VM → `http://IP-del-servidor:8080/`:

- eliges tu buzón, ves la bandeja, abres el mensaje y **descargas el adjunto**;
- «Redactar mensaje» envía con adjunto por la misma ruta interna que el SMTP.

> **Aviso de laboratorio:** no hay autenticación (decisión de la práctica):
> cualquiera en la red puede leer las bandejas. No expongas el 8080 fuera
> de la red NAT de VirtualBox.

## Escenario 1: enviar `Confidencial.pdf`

1. Arranca `todo` en la VM del servidor de correo; buzones `pepe` y `ana`.
2. En el **Windows Server 2008** (o en cualquier VM), envía el PDF por
   correo a `ana@empresa.local` (un cliente SMTP de la VM, o el diálogo
   telnet de arriba, o el propio webmail).
3. Evidencias que quedan en el servidor:
   - `servidor/buzones/ana/mensajes/<id>.eml` — mensaje completo con la
     cabecera `Received` (origen, HELO, fecha);
   - `servidor/buzones/ana/adjuntos/<id>/Confidencial.pdf` — el adjunto
     extraído, listo para imagen y cadena de custodia.
4. En el webmail, bandeja de `ana` → abrir → descargar adjunto.

## Log de envíos (auditoría)

Cada mensaje entregado — por **SMTP o por el webmail** (los dos convergen en
el punto de entrega común, `buzon.entregar`) — añade **una única línea de
texto plano** a `logs/envios.log`, dentro del directorio `servidor/`:

```text
2026-11-05T10:00:00 | de: pepe@empresa.local | para: ana@empresa.local, luis@empresa.local | asunto: Examen final | adjuntos: Confidencial.pdf (123 KB), notas.txt (4 KB)
```

- **Timestamp** ISO 8601 en hora local (segundos de precisión).
- **`para`**: los destinatarios locales **en el orden en que se aceptaron**
  (RCPT TO / la lista del formulario), unidos con `, `.
- **`adjuntos`**: nombres ya saneados (los mismos que quedan en
  `buzones/…/adjuntos/`) con su tamaño redondeado a KB (mínimo 1 KB); si no
  hay, `adjuntos: ninguno`.
- **Escaping**: si el asunto o un nombre de adjunto contiene el separador
  ` | ` — o cualquier `|` — se sustituye por `¦` (barra partida, U+00A6),
  así que cada envío es exactamente una línea jamás rota.
- El fichero **crece por anexión** (nunca se reescribe) y la escritura va
  protegida con lock y `try/except`: un fallo del log (disco lleno,
  permisos…) queda en el logger `correo.log_envios` pero **nunca tumba** el
  envío ni la sesión.

**Dónde y cómo cambiar el directorio** — sección nueva de `config.ini`
(valor por defecto en `config.py`: `logs`, relativo a `servidor/`; rutas
absolutas también admitidas; el directorio se crea solo, al arrancar y al
escribir):

```ini
[log]
directorio = logs
```

`logs/` son datos runtime y están en `.gitignore` (no se versionan).

## Respuestas del servidor (lo que verás en las pruebas)

| Código | Significado |
|--------|-------------|
| `220/250/354/221` | saludo, OK, listo para DATA, despedida |
| `500` | comando desconocido o línea demasiado larga |
| `501` | sintaxis (falta `<direccion>`, malformada…) |
| `503` | fuera de orden (MAIL sin HELO, DATA sin RCPT…) |
| `550` | destinatario no existe en este servidor |
| `554` | **relay denegado**: dominio distinto de `empresa.local` |
| `552` | mensaje que supera `max_tamano_mb` |
| `421` | sin huecos de conexión o timeout de inactividad |

## Pruebas reproducibles

```sh
cd servidor
python3 -m unittest discover -v        # o: py -3 -m unittest discover -v
```

84 pruebas: protocolo, seguridad (anti-open-relay, límites), MIME/adjuntos,
webmail (XSS, 413, ids seguros), log de envíos y arranque combinado `todo`.
Sin red externa ni
privilegios: todo se monta en 127.0.0.1 con puertos efímeros y buzones
temporales.

## Estructura

```text
servidor/
├── servidor.py     CLI: smtp | webmail-via-todo | usuario alta|baja|listar
├── config.py       lectura de config.ini (puertos, dominio, límites)
├── srv_tcp.py      aceptación TCP, hilo por conexión, límites, timeouts
├── smtp_sesion.py  la máquina de estados SMTP (el protocolo, desde cero)
├── correo_api.py   direcciones, construcción MIME, extracción de adjuntos
├── buzon.py        buzones .eml + adjuntos + usuarios.json (+ lock)
├── log_envios.py   auditoría: una línea por envío en logs/envios.log
├── webmail.py      interfaz web con http.server (solo stdlib)
├── plantillas/     HTML del webmail (string.Template)
├── config.ini      configuración editable
├── logs/           log de envíos (runtime, no versionado)
├── arrancar.bat    doble clic en la VM Windows
├── crear_usuario.bat
└── tests/          unittest (84 pruebas)
```

## Ajustes (`config.ini`)

```ini
[smtp]     puerto = 25
[webmail]  puerto = 8080
[correo]   dominio = empresa.local      # solo se entrega a este dominio
[limites]  max_conexiones = 20
           max_tamano_mb = 25
           timeout_seg = 120
[log]      directorio = logs            # logs/envios.log (auditoría)
```

Los buzones (`buzones/`), `usuarios.json` y `logs/` son **datos runtime**:
están en `.gitignore` y no se versionan.

## Solución de problemas

- **`550 Destinatario desconocido`** → no existe el buzón: `usuario alta`.
- **`554 Relay denegado`** → el destino no es de `empresa.local`.
- **`conexión rechazada` / nada responde** → firewall (netsh de arriba) o
  la IP de la VM no es la esperada (`ipconfig`).
- **`Acceso denegado` al arrancar** → puerto 25 sin administrador:
  usa `--puerto 2525`.
- **No veo un buzón recién creado con el servidor ya arrancado** → no
  debería pasar (el servidor recarga `usuarios.json` solo); reinicia el
  servidor si el fichero se editó a mano mientras corría.
