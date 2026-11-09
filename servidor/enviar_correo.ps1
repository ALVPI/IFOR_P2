# ============================================================
# Cliente SMTP real para el Escenario 1 de IFOR
# Envía un correo con adjunto MIME por SMTP puro (sin librerías)
# ============================================================

# --- CONFIGURACIÓN (ajusta esto) ---
$ServidorSMTP = "192.168.1.50"        # IP de la VM servidor
$PuertoSMTP   = 25
$De           = "pepe@empresa.local"
$Para         = "ana@empresa.local"
$Asunto       = "Envio Confidencial"
$Cuerpo       = "Adjunto el documento Confidencial."
$RutaAdjunto  = "C:\Confidencial.pdf"  # ruta del PDF en la VM cliente
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

# Base64 en líneas de 76 caracteres (RFC 2045)
for ($i = 0; $i -lt $Base64.Length; $i += 76) {
    $chunk = $Base64.Substring($i, [Math]::Min(76, $Base64.Length - $i))
    $Mensaje += $chunk
}
$Mensaje += ""
$Mensaje += "--$Boundary--"
$Mensaje += ""

# Conectar por TCP raw y dialogar SMTP
$c  = New-Object System.Net.Sockets.TcpClient($ServidorSMTP, $PuertoSMTP)
$s  = $c.GetStream()
$r  = New-Object System.IO.StreamReader($s)
$w  = New-Object System.IO.StreamWriter($s)
$w.AutoFlush = $true

function Recv { $r.ReadLine() }
function Send($line) { $w.WriteLine($line) }

$resp = Recv; Write-Host "S: $resp"
Send "HELO cliente-forense"; $resp = Recv; Write-Host "S: $resp"
Send "MAIL FROM:<$De>";        $resp = Recv; Write-Host "S: $resp"
Send "RCPT TO:<$Para>";        $resp = Recv; Write-Host "S: $resp"
Send "DATA";                   $resp = Recv; Write-Host "S: $resp"

# Enviar el mensaje línea a línea (dot-stuffing si una línea empieza por .)
foreach ($line in $Mensaje) {
    if ($line.StartsWith(".")) { Send ".$line" } else { Send $line }
}
Send "."; $resp = Recv; Write-Host "S: $resp"

Send "QUIT"; $resp = Recv; Write-Host "S: $resp"

$c.Close()
Write-Host "`nCorreo enviado correctamente." -ForegroundColor Green
