# =============================================================================
#  enviar_correo.ps1
#  ---------------------------------------------------------------------------
#  Cliente SMTP real para el Escenario 1 de la practica de Informatica Forense
#  (grupo H): envio de `Confidencial.pdf` entre dos buzones del grupo.
#
#  Que hace este script:
#     Compone un mensaje MIME completo (texto + adjunto en base64), se conecta
#     al servidor de correo por TCP y dialoga el protocolo SMTP definido en la
#     RFC 5321 SIN usar librerias de envio, de modo que todo el trafico quede
#     visible y sea auditable.
#
#  Por que SMTP "a pelo" y no un cliente de correo:
#     La practica exige un escenario realista. Al hablar SMTP directamente se
#     genera la cabecera `Received` en el servidor con la IP real de origen y
#     el HELO declarado, que son las trazas que despues se analizan en la
#     cadena de custodia.
#
#  Requisitos:
#     * Python no hace falta: solo PowerShell 5.1+ (viene con Windows).
#     * El servidor de correo debe estar arrancado (servidor.py todo).
#     * El adjunto debe existir en la ruta indicada abajo.
#
#  Como ejecutarlo:
#     1. Ajusta las variables de la seccion CONFIGURACION.
#     2. Abre PowerShell en la carpeta del script y ejecuta:
#
#          Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#          .\enviar_correo.ps1
#
#     El `-Scope Process` solo afecta a esta ventana: no cambia la politica
#     global del equipo (importante en las VMs del laboratorio).
#
#  Notas de red:
#     * Misma VM (pruebas):      $ServidorSMTP = "127.0.0.1"
#     * Practica con dos VMs:    $ServidorSMTP = "192.168.1.50"  (IP del servidor)
#     * Si la conexion es rechazada, revisa el firewall del PC anfitrion
#       (puerto 25) y que ambas VMs esten en la misma red (adaptador puente).
# =============================================================================

# -----------------------------------------------------------------------------
#  CONFIGURACION -- unico bloque que hay que tocar
# -----------------------------------------------------------------------------
# IP (o nombre) del servidor de correo. Usar "127.0.0.1" cuando el servidor
# corre en la misma maquina que este script.
$ServidorSMTP = "127.0.0.1"

# Puerto SMTP estandar. El 25 requiere privilegios de administrador en el
# SERVIDOR; si se arranca con `--puerto 2525`, cambiarlo aqui tambien.
$PuertoSMTP   = 25

# Remitente y destinatario. Ambos deben existir como buzones en el servidor
# (creados con `py -3 servidor.py usuario alta <nombre>`), o el servidor
# respondera 550 "Destinatario desconocido".
$De           = "pepe@empresa.local"
$Para         = "ana@empresa.local"

# Asunto y cuerpo del mensaje. El asunto no debe contener saltos de linea:
# romperia las cabeceras del mensaje (injection de cabeceras).
$Asunto       = "Envio Confidencial"
$Cuerpo       = "Adjunto el documento Confidencial."

# Ruta del fichero que se adjunta. Por defecto, el escritorio del usuario
# actual ($env:USERPROFILE resuelve a C:\Users\<usuario>).
$RutaAdjunto  = Join-Path $env:USERPROFILE "Desktop\Confidencial.pdf"
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
#  1. VALIDACION DEL ADJUNTO
# -----------------------------------------------------------------------------
# Se comprueba ANTES de abrir la conexion: si el fichero no existe, no tiene
# sentido entablar la sesion SMTP. `Test-Path` devuelve $false si no hay
# permisos de lectura, no solo si no existe.
if (-not (Test-Path $RutaAdjunto)) {
    Write-Error "No se encuentra el adjunto: $RutaAdjunto"
    exit 1   # codigo de salida != 0: util si alguien lo automatiza
}

# `GetFileName` deja solo el nombre (sin ruta), que es lo que viaja en las
# cabeceras `name=` y `filename=`. Evita filtrar la estructura de carpetas
# del equipo que envia.
$NombreAdjunto = [System.IO.Path]::GetFileName($RutaAdjunto)

# El adjunto viaja SIEMPRE en binario (aunque sea un PDF "de texto"): se leen
# los bytes crudos y se codifican en base64 para poder viajar por un canal
# de texto como SMTP.
$BytesAdjunto  = [System.IO.File]::ReadAllBytes($RutaAdjunto)
$Base64        = [System.Convert]::ToBase64String($BytesAdjunto)

# -----------------------------------------------------------------------------
#  2. CONSTRUCCION DEL MENSAJE MIME (RFC 2045 / RFC 5322)
# -----------------------------------------------------------------------------
# El mensaje es `multipart/mixed`: dos partes separadas por un `boundary`
# (frontera) unica. La parte 1 es el texto plano; la parte 2 es el adjunto.
#
# Estructura resultante:
#
#   From: ...
#   To: ...
#   Subject: ...
#   Content-Type: multipart/mixed; boundary="----=_Part_<aleatorio>"
#
#   ------_Part_<aleatorio>
#   Content-Type: text/plain
#   <cuerpo>
#
#   ------_Part_<aleatorio>
#   Content-Type: application/pdf
#   Content-Transfer-Encoding: base64
#   <base64 del PDF>
#
#   ------_Part_<aleatorio>--

# Frontera aleatoria: un GUID garantiza que no aparezca dentro del propio
# contenido (si apareciera, el destinatario cortaria el mensaje a mitad).
$Boundary = "----=_Part_" + [guid]::NewGuid().ToString("N")

# Se acumula el mensaje en un array de lineas; al final se envia linea a linea.
$Mensaje  = @()

# --- Cabeceras del mensaje (RFC 5322) ---
$Mensaje += "From: $De"                        # quien envia
$Mensaje += "To: $Para"                        # quien recibe
$Mensaje += "Subject: $Asunto"                 # asunto visible
$Mensaje += "MIME-Version: 1.0"                # habilita el soporte MIME
$Mensaje += "Content-Type: multipart/mixed; boundary=`"$Boundary`""
$Mensaje += ""                                 # linea en blanco: fin de cabeceras

# --- Parte 1: cuerpo en texto plano ---
$Mensaje += "--$Boundary"                      # apertura de la parte 1
$Mensaje += "Content-Type: text/plain; charset=utf-8"
$Mensaje += "Content-Transfer-Encoding: 7bit"  # texto sin codificar
$Mensaje += ""                                 # fin de cabeceras de la parte
$Mensaje += $Cuerpo                            # el texto en si
$Mensaje += ""                                 # separador antes del siguiente --

# --- Parte 2: adjunto ---
$Mensaje += "--$Boundary"                      # apertura de la parte 2
$Mensaje += "Content-Type: application/pdf; name=`"$NombreAdjunto`""
$Mensaje += "Content-Transfer-Encoding: base64"
$Mensaje += "Content-Disposition: attachment; filename=`"$NombreAdjunto`""
$Mensaje += ""                                 # fin de cabeceras: empieza el base64

# El base64 se parte en lineas de 76 caracteres, como exige la RFC 2045.
# SMTP admite lineas de hasta 998 caracteres, pero 76 es la practica habitual
# y garantiza compatibilidad con cualquier servidor o cliente de destino.
for ($i = 0; $i -lt $Base64.Length; $i += 76) {
    $chunk = $Base64.Substring($i, [Math]::Min(76, $Base64.Length - $i))
    $Mensaje += $chunk
}

$Mensaje += ""                                 # linea en blanco tras el contenido
$Mensaje += "--$Boundary--"                    # frontera CERRADA (con -- final)
$Mensaje += ""                                 # fin del mensaje

# -----------------------------------------------------------------------------
#  3. CONEXION TCP Y DIALOGO SMTP (RFC 5321)
# -----------------------------------------------------------------------------
# Se abre un socket TCP crudo hacia el servidor y se habla el protocolo a mano.
# No hay autenticacion: la red del laboratorio es cerrada (decision de la
# practica). Si algo falla aqui, el script lanza excepcion y no llega a enviar.
$c = New-Object System.Net.Sockets.TcpClient($ServidorSMTP, $PuertoSMTP)
$s = $c.GetStream()

# StreamReader/StreamWriter trabajan sobre el flujo de bytes del socket.
# `AutoFlush = $true` equivale a enviar cada WriteLine inmediatamente: sin
# esto, los comandos quedarian en el buffer y el servidor no los veria.
$r = New-Object System.IO.StreamReader($s)
$w = New-Object System.IO.StreamWriter($s)
$w.AutoFlush = $true

# --- Helpers de la sesion ---
# `Recv` lee la respuesta del servidor (una linea por comando).
function Recv { $r.ReadLine() }

# `Send` escribe un comando y lo termina con CRLF, que es como debe cerrarse
# cada linea en SMTP (no basta con el salto de linea propio de Windows).
function Send($line) { $w.WriteLine($line) }

# --- Secuencia SMTP ---
# Cada paso muestra la respuesta `S:` (server) para poder auditar la sesion.
#
# 220 = saludo del servidor (listo para hablar)
# 250 = comando aceptado
# 354 = servidor listo para recibir el bloque DATA
# 221 = despedida
# 4xx = error temporal (reintentable)   5xx = error permanente

$resp = Recv; Write-Host "S: $resp"                        # 220 saludo
Send "HELO cliente-forense"; $resp = Recv; Write-Host "S: $resp"   # 250
Send "MAIL FROM:<$De>";        $resp = Recv; Write-Host "S: $resp"  # 250 remitente
Send "RCPT TO:<$Para>";        $resp = Recv; Write-Host "S: $resp"  # 250 destino
Send "DATA";                   $resp = Recv; Write-Host "S: $resp"  # 354 listo

# --- Envio del cuerpo ---
# Se transmite el mensaje linea a linea. Aplica el DOT-STUFFING de la RFC 5321
# seccion 4.5.2: cualquier linea que empiece por "." se le anteponen dos
# puntos. Sin esto, un cuerpo que contenga una linea con solo un punto
# interpretaria el fin anticipado del mensaje y el servidor cortaria el .eml.
foreach ($line in $Mensaje) {
    if ($line.StartsWith(".")) { Send ".$line" } else { Send $line }
}

# "." en una linea propia = fin del bloque DATA. El servidor responde 250 si
# ha guardado el mensaje, o 5xx si lo ha rechazado (demasiado grande, etc.).
Send "."; $resp = Recv; Write-Host "S: $resp"              # 250 entregado

# Cierre ordenado de la sesion: el servidor responde 221 y libera la conexion.
Send "QUIT"; $resp = Recv; Write-Host "S: $resp"           # 221

# -----------------------------------------------------------------------------
#  4. CIERRE Y RESULTADO
# -----------------------------------------------------------------------------
# Se cierra el socket explicitamente para no dejar conexiones abiertas en la
# VM. En caso de exito se muestra el mensaje final en verde.
$c.Close()

Write-Host ""
Write-Host "Correo enviado correctamente." -ForegroundColor Green
Write-Host "  De:     $De"
Write-Host "  Para:   $Para"
Write-Host "  Asunto: $Asunto"
Write-Host "  Adjunto: $NombreAdjunto ($([Math]::Round($BytesAdjunto.Length/1KB)) KB)"
