# ============================================================
# Cliente SMTP real para el Escenario 1 de IFOR
# Envia un correo con adjunto MIME por SMTP puro (sin librerias)
#
# Como usarlo:
#   1. Ajusta la IP del servidor y la ruta del adjunto abajo.
#   2. Abre PowerShell y ejecuta (si reclama firma):
#        Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#        .\enviar_correo.ps1
#
# Nota: en una sola VM (pruebas) usa $ServidorSMTP = "127.0.0.1".
#       Para la practica real, pon la IP de la VM servidor.
# ============================================================

# --- CONFIGURACION (ajusta esto) ---
$ServidorSMTP = "127.0.0.1"                              # IP de la VM servidor
$PuertoSMTP   = 25
$De           = "pepe@empresa.local"
$Para         = "ana@empresa.local"
$Asunto       = "Envio Confidencial"
$Cuerpo       = "Adjunto el documento Confidencial."
$RutaAdjunto  = Join-Path $env:USERPROFILE "Desktop\Confidencial.pdf"
# -----------------------------------

if (-not (Test-Path $RutaAdjunto)) {
    Write-Error "No se encuentra el adjunto: $RutaAdjunto"
    exit 1
}

$NombreAdjunto = [System.IO.Path]::GetFileName($RutaAdjunto)
$BytesAdjunto  = [System.IO.File]::ReadAllBytes($RutaAdjunto)
$Base64        = [System.Convert]::ToBase64String($BytesAdjunto)

# Construir el mensaje MIME (multipart/mixed)
$Boundary = "----=_Part_" + [guid]::NewGuid().ToString("N")
$Mensaje  = @()
$Mensaje += "From: $De"
$Mensaje += "To: $Para"
$Mensaje += "Subject: $Asunto"
$Mensaje += "MIME-Version: 1.0"
$Mensaje += "Content-Type: multipart/mixed; boundary=`"$Boundary`""
$Mensaje += ""
$Mensaje += "--$Boundary"
$Mensaje += "Content-Type: text/plain; charset=utf-8"
$Mensaje += "Content-Transfer-Encoding: 7bit"
$Mensaje += ""
$Mensaje += $Cuerpo
$Mensaje += ""
$Mensaje += "--$Boundary"
$Mensaje += "Content-Type: application/pdf; name=`"$NombreAdjunto`""
$Mensaje += "Content-Transfer-Encoding: base64"
$Mensaje += "Content-Disposition: attachment; filename=`"$NombreAdjunto`""
$Mensaje += ""

# Base64 en lineas de 76 caracteres (RFC 2045)
for ($i = 0; $i -lt $Base64.Length; $i += 76) {
    $chunk = $Base64.Substring($i, [Math]::Min(76, $Base64.Length - $i))
    $Mensaje += $chunk
}
$Mensaje += ""
$Mensaje += "--$Boundary--"
$Mensaje += ""

# Conectar por TCP raw y dialogar SMTP
$c = New-Object System.Net.Sockets.TcpClient($ServidorSMTP, $PuertoSMTP)
$s = $c.GetStream()
$r = New-Object System.IO.StreamReader($s)
$w = New-Object System.IO.StreamWriter($s)
$w.AutoFlush = $true

function Recv { $r.ReadLine() }
function Send($line) { $w.WriteLine($line) }

$resp = Recv; Write-Host "S: $resp"
Send "HELO cliente-forense"; $resp = Recv; Write-Host "S: $resp"
Send "MAIL FROM:<$De>";        $resp = Recv; Write-Host "S: $resp"
Send "RCPT TO:<$Para>";        $resp = Recv; Write-Host "S: $resp"
Send "DATA";                   $resp = Recv; Write-Host "S: $resp"

# Enviar el mensaje linea a linea (dot-stuffing si una linea empieza por .)
foreach ($line in $Mensaje) {
    if ($line.StartsWith(".")) { Send ".$line" } else { Send $line }
}
Send "."; $resp = Recv; Write-Host "S: $resp"

Send "QUIT"; $resp = Recv; Write-Host "S: $resp"

$c.Close()
Write-Host ""
Write-Host "Correo enviado correctamente." -ForegroundColor Green
