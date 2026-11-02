"""correo_api.py -- parseo de direcciones SMTP y manipulacion de mensajes.

Dos bloques:

* direcciones: interpretar ``FROM:<a@b>`` / ``TO:<a@b>`` sin romper con
  las variantes reales de los clientes (son la base de los 554/550);
* mensajes: construir mensajes con adjuntos (webmail y pruebas) y
  extraer los adjuntos de un mensaje entrante a disco, con los nombres
  saneados para que nadie pueda escaparse de la carpeta destino.
"""

import mimetypes
import re
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formatdate, make_msgid
from pathlib import Path
from typing import List, Optional, Tuple

# La parte local y el dominio se validan de forma estricta: sin espacios,
# sin barras, sin caracteres de ruta.  Es la primera linea de defensa
# contra inyecciones de rutas y comandos raros.
RE_USUARIO = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
RE_DOMINIO = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")

# Caracteres prohibidos en nombres de fichero de Windows (y raros en Unix).
RE_INVALIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


# ---------------------------------------------------------------------- #
# Direcciones
# ---------------------------------------------------------------------- #

def extraer_direccion(resto: str, prefijo: str) -> Optional[str]:
    """Extrae la direccion de ``FROM:<a@b> SIZE=...`` o ``TO:<a@b>``.

    * ``resto`` es lo que va despues del verbo (``MAIL``/``RCPT``).
    * Devuelve la direccion (``""`` para el remitente nulo ``<>``).
    * Devuelve ``None`` si la sintaxis es incorrecta (→ 501 en el protocolo).
    * Los parametros ESMTP que puedan venir detras (``SIZE=...``,
      ``NOTIFY=...``) se ignoran a proposito: son opcionales en la RFC.
    """
    if not resto.upper().startswith(prefijo):
        return None
    resto = resto[len(prefijo):].lstrip()

    inicio, fin = resto.find("<"), resto.find(">")
    if inicio != 0 or fin < 0:
        return None
    direccion = resto[1:fin]
    if direccion == "":            # <> = remitente nulo (devoluciones)
        return ""

    if not parsear_direccion(direccion):
        return None
    return direccion


def parsear_direccion(direccion: str) -> Optional[Tuple[str, str]]:
    """``"pepe@empresa.local"`` -> ``("pepe", "empresa.local")`` o ``None``."""
    if direccion.count("@") != 1:
        return None
    usuario, dominio = direccion.split("@", 1)
    if not RE_USUARIO.match(usuario) or not RE_DOMINIO.match(dominio):
        return None
    return usuario, dominio


# ---------------------------------------------------------------------- #
# Construccion de mensajes (webmail y pruebas)
# ---------------------------------------------------------------------- #

def construir_mensaje(de: str, para: str, asunto: str, cuerpo: str,
                      adjuntos: Optional[List[Tuple[str, bytes]]] = None) -> bytes:
    """Compone un mensaje MIME completo listo para entregar en un buzón.

    ``adjuntos`` es una lista de ``(nombre_original, bytes_del_fichero)``.
    Devuelve los bytes con lineas CRLF (formato SMTP).
    """
    msg = EmailMessage()
    msg["From"] = de
    msg["To"] = para
    msg["Subject"] = asunto
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    msg.set_content(cuerpo)

    for nombre, datos in adjuntos or []:
        # mimetypes adivina "application/pdf" etc.; si no lo conoce, octet-stream
        tipo = mimetypes.guess_type(nombre)[0] or "application/octet-stream"
        maintype, subtype = tipo.split("/", 1)
        msg.add_attachment(datos, maintype=maintype, subtype=subtype,
                           filename=nombre)

    # as_bytes() usa \n; en SMTP toca \r\n (los mensajes solo deben
    # contener CRLF, si no el parser del destinatario se queja).
    return msg.as_bytes().replace(b"\n", b"\r\n")


# ---------------------------------------------------------------------- #
# Extraccion de adjuntos
# ---------------------------------------------------------------------- #

def nombre_seguro(nombre: str) -> str:
    """Reduce un nombre de adjunto a algo guardable dentro de UNA carpeta.

    Casos que tira abajo (pruebas en ``test_correo``):

    * ``../../etc/passwd``            -> ``passwd``
    * ``..\\..\\evil.pdf``            -> ``evil.pdf``
    * ``co:n?ira*.txt``               -> ``co_n_ira_.txt``
    * ``..`` o vacio                  -> ``adjunto``
    """
    nombre = nombre.replace("\\", "/").split("/")[-1]      # sin rutas
    nombre = RE_INVALIDOS.sub("_", nombre)                 # sin caracteres raros
    nombre = nombre.strip(". ")                            # sin '..' ni puntos finales
    nombre = nombre[:100]                                  # longitud razonable
    return nombre or "adjunto"


def extraer_adjuntos(data: bytes, destino: Path) -> List[str]:
    """Guarda en ``destino`` cada adjunto del mensaje ``data``.

    Devuelve los nombres con los que se guardaron (puede ser ``[]``).
    Un mensaje corrupto o sin adjuntos no es un error: devuelve [].
    """
    try:
        msg = BytesParser(policy=policy.default).parsebytes(data)
    except Exception:  # noqa: BLE001 -- un .eml corrupto no debe tumbar la entrega
        return []
    if not isinstance(msg, EmailMessage) or not msg.is_multipart():
        return []

    guardados: List[str] = []
    for parte in msg.iter_attachments():
        payload = parte.get_payload(decode=True)
        if payload is None:
            contenido = parte.get_payload()
            payload = (contenido.encode("utf-8", "replace")
                       if isinstance(contenido, str) else b"")
        nombre = nombre_seguro(str(parte.get_filename() or ""))

        destino.mkdir(parents=True, exist_ok=True)
        ruta = destino / nombre
        contador = 1
        while ruta.exists():          # colisiones: informe.pdf, informe_1.pdf...
            ruta = destino / f"{ruta.stem}_{contador}{ruta.suffix}"
            contador += 1
        ruta.write_bytes(payload)
        guardados.append(ruta.name)
    return guardados
