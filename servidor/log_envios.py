"""log_envios.py -- auditoria de envios en texto plano (linea por mensaje).

Cada entrega (tanto por SMTP como por el webmail: las dos convergen en
``buzon.entregar``) anade UNA linea legible a ``logs/envios.log``::

    2026-11-05T10:00:00 | de: pepe@empresa.local | para: ana@empresa.local,
    luis@empresa.local | asunto: Examen final | adjuntos: Confidencial.pdf
    (123 KB), notas.txt (4 KB)

Reglas de formato (documentadas a proposito para poder auditarlas):

* El timestamp es ISO 8601 en hora local, segundos de precision.
* ``para`` son los destinos locales en el ORDEN en que se acceptaron
  (RCPT TO / lista del webmail), unidos con ``, `` (que no entra en
  conflicto con el separador de campos `` | ``).
* El separador de campos es `` | ``.  Para que una linea nunca se rompa,
  TODO ``|`` que aparezca dentro del asunto o de un nombre de adjunto se
  sustituye por ``¦`` (barra partida, U+00A6): muy parecido al original
  pero imposible de confundir con el campo.
* Si no hay adjuntos se escribe ``adjuntos: ninguno``.  El tamanio de
  cada adjunto se redondea a KB (minimo 1 KB).
* El fichero crece por ANEXION (modo ``"a"``): jamas se reescribe, un log
  de auditoria solo se apila.
* La escritura esta protegida con lock (entregar se llama desde un hilo
  por conexion) y con try/except: un fallo del log (disco lleno, permisos,
  lo que sea) NUNCA tumbar el envio ni la sesion; solo deja constancia en
  el logger ``correo.log_envios``.
"""

import logging
import threading
from datetime import datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path
from typing import List, Tuple

from config import Config
from correo_api import nombre_seguro

log = logging.getLogger("correo.log_envios")

SEPARADOR = " | "
SUSTITUTO = "\u00a6"        # barra partida: sustituye al | del propio mensaje

# Un solo fichero de anexo dentro del directorio configurado.
NOMBRE_FICHERO = "envios.log"

# entregar() se llama desde un hilo por conexion (SMTP y webmail): el
# anexo multipartido al fichero debe ser atomico entre la apertura y el
# close para no entrelazar lineas.
_lock = threading.Lock()


def _sin_separador(texto: str) -> str:
    """Quita ``|`` del texto libre (asunto, nombres) sustituyendolo al ``¦``.

    Sustituye primero el separador completo (`` | ``) y despues cualquier
    `|` suelto: el resultado ya no puede romper la linea del log.
    """
    return str(texto).replace(SEPARADOR, " " + SUSTITUTO + " ").replace(
        "|", SUSTITUTO
    )


def _kb(nbytes: int) -> int:
    """Redondea un tamanio a KB, con 1 KB como minimo legible."""
    return max(1, (nbytes + 1023) // 1024)


def _partes_mensaje(data: bytes) -> Tuple[str, str, List[str]]:
    """De los bytes del mensaje saca (remitente, asunto, textos de adjuntos).

    Los nombres son los SANEADOS con los que se guardan en disco
    (``nombre_seguro``), que es lo que un auditor vera en ``buzones/``.
    Un mensaje corrupto no es error: devuelve defaults.
    """
    try:
        msg = BytesParser(policy=policy.default).parsebytes(data)
    except Exception:  # noqa: BLE001 -- el correo ya esta entregado; log aparte
        return "(desconocido)", "(mensaje ilegible)", []

    remitente = str(msg.get("From", "")).strip() or "(desconocido)"
    asunto = str(msg.get("Subject", "")).strip() or "(sin asunto)"

    adjuntos: List[str] = []
    if isinstance(msg, EmailMessage):
        for parte in msg.iter_attachments():
            payload = parte.get_payload(decode=True)
            if payload is None:
                contenido = parte.get_payload()
                nbytes = (len(contenido.encode("utf-8", "replace"))
                          if isinstance(contenido, str) else 0)
            else:
                nbytes = len(payload)
            nombre = _sin_separador(nombre_seguro(str(parte.get_filename() or "")))
            adjuntos.append(f"{nombre} ({_kb(nbytes)} KB)")
    return remitente, asunto, adjuntos


def registrar_envio(config: Config, destinos: List[str], data: bytes) -> None:
    """Anade UNA linea por mensaje al log de envios.  NUNCA lanza excepciones.

    Llamada desde :meth:`buzon.Buzones.entregar`, punto de entrega comun
    del SMTP y del webmail.  ``destinos`` son nombres de usuario locales
    en el orden aceptado: SE completan con ``config.dominio`` para el log.
    """
    try:
        remitente, asunto, adjuntos = _partes_mensaje(data)
        para = ", ".join(
            _sin_separador(f"{d}@{config.dominio}") for d in destinos
        )
        texto_adjuntos = ", ".join(adjuntos) if adjuntos else "ninguno"
        timestamp = datetime.now().isoformat(timespec="seconds")
        linea = (
            f"{timestamp}{SEPARADOR}de: {_sin_separador(remitente)}"
            f"{SEPARADOR}para: {para}{SEPARADOR}asunto: "
            f"{_sin_separador(asunto)}{SEPARADOR}adjuntos: "
            f"{_sin_separador(texto_adjuntos)}\n"
        )

        directorio = Path(config.ruta_logs)
        directorio.mkdir(parents=True, exist_ok=True)   # tambien al escribir
        with _lock:
            with open(directorio / NOMBRE_FICHERO, "a", encoding="utf-8") as fich:
                fich.write(linea)
    except Exception:  # noqa: BLE001 -- el envio nunca depende del log
        log.exception("no pude escribir el log de envios en %s",
                      getattr(config, "ruta_logs", "?"))


def preparar_directorio(config: Config) -> None:
    """Crea el directorio de logs al arrancar (silencioso si ya existia)."""
    try:
        Path(config.ruta_logs).mkdir(parents=True, exist_ok=True)
    except Exception:  # noqa: BLE001 -- no bloquear el arranque por el log
        log.exception("no pude crear el directorio de logs %s",
                      getattr(config, "ruta_logs", "?"))
