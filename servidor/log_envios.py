"""log_envios.py -- auditoria de envios en texto plano (linea por mensaje).

Cada entrega (tanto por SMTP como por el webmail: las dos convergen en
``buzon.entregar``) anade UNA linea legible a ``logs/envios.log``::

    2026-11-05T10:00:00 | de: pepe@empresa.local | para: ana@empresa.local,
    luis@empresa.local | asunto: Examen final | adjuntos: Confidencial.pdf
    (123 KB), notas.txt (4 KB)

Y, ademas, guarda una **copia FISICA** de cada adjunto enviado en
``adjuntos_enviados/`` (configurable con ``[log] copia_adjuntos``; vacio
lo desactiva)::

    adjuntos_enviados/
      2026-11-05_10-00-00_a1b2c3d4/
        envio.txt            <- quien, para quien, asunto y fecha
        Confidencial.pdf     <- el fichero tal cual se envio
        notas.txt

Una carpeta por MENSAJE (fecha + hash corto del contenido), asi el
registro de texto y la copia fisica se pueden cruzar.  Si el mensaje no
lleva adjuntos no se crea carpeta.

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
  el logger ``correo.log_envios``.  Lo mismo vale para la copia fisica de
  adjuntos: si falla, se anota y sigue; el correo ya esta entregado.
"""

import hashlib
import logging
import threading
from datetime import datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path
from typing import Dict, List, Tuple

from config import Config
from correo_api import nombre_seguro

log = logging.getLogger("correo.log_envios")

SEPARADOR = " | "
SUSTITUTO = "\u00a6"        # barra partida: sustituye al | del propio mensaje

# Un solo fichero de anexo dentro del directorio configurado.
NOMBRE_FICHERO = "envios.log"

# Carpeta con la copia fisica de los adjuntos de un mensaje.
FICHERO_METADATA = "envio.txt"

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


def _partes_mensaje(data: bytes) -> Tuple[str, str, List[Tuple[str, bytes]]]:
    """De los bytes del mensaje saca (remitente, asunto, adjuntos).

    Los adjuntos vuelven como ``(nombre_saneado, contenido)``: el mismo
    nombre con el que se guardan en ``buzones/.../adjuntos/`` y con el que
    se copian en ``adjuntos_enviados/``.  Un mensaje corrupto no es error:
    devuelve defaults.
    """
    try:
        msg = BytesParser(policy=policy.default).parsebytes(data)
    except Exception:  # noqa: BLE001 -- el correo ya esta entregado; log aparte
        return "(desconocido)", "(mensaje ilegible)", []

    remitente = str(msg.get("From", "")).strip() or "(desconocido)"
    asunto = str(msg.get("Subject", "")).strip() or "(sin asunto)"

    adjuntos: List[Tuple[str, bytes]] = []
    if isinstance(msg, EmailMessage):
        for parte in msg.iter_attachments():
            payload = parte.get_payload(decode=True)
            if payload is None:
                contenido = parte.get_payload()
                payload = (contenido.encode("utf-8", "replace")
                           if isinstance(contenido, str) else b"")
            nombre = nombre_seguro(str(parte.get_filename() or ""))
            adjuntos.append((nombre, payload))
    return remitente, asunto, adjuntos


# ---------------------------------------------------------------------- #
# Copia FISICA de los adjuntos enviados
# ---------------------------------------------------------------------- #

def _nombre_con_sufijo(nombre: str, numero: int) -> str:
    """``informe.pdf`` -> ``informe_1.pdf`` (dos adjuntos con el mismo nombre)."""
    ruta = Path(nombre)
    return f"{ruta.stem}_{numero}{ruta.suffix}"


def _carpeta_del_mensaje(config: Config, data: bytes) -> Path:
    """Carpeta unica por mensaje: fecha + hash corto del contenido.

    La fecha la hace legible a simple vista; el hash (sha1 del mensaje)
    sirve para cruzar la carpeta con el ``.eml`` original: mismo
    contenido, misma huella.  Dos mensajes identicos en el mismo segundo
    no comparten carpeta: se anade un sufijo numerado.
    """
    sello = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    huella = hashlib.sha1(data).hexdigest()[:8]
    base = Path(config.copia_adjuntos)
    carpeta = base / f"{sello}_{huella}"
    contador = 1
    while carpeta.exists():
        carpeta = base / f"{sello}_{huella}_{contador}"
        contador += 1
    return carpeta


def _copiar_adjuntos(config: Config, destinos: List[str], remitente: str,
                     asunto: str, adjuntos: List[Tuple[str, bytes]],
                     data: bytes) -> Path:
    """Guarda los adjuntos tal cual se enviaron, mas su ficha ``envio.txt``.

    Devuelve la carpeta creada.  Lanza si no se puede escribir: quien
    decide como actuar ante un fallo es :func:`registrar_envio`.
    """
    carpeta = _carpeta_del_mensaje(config, data)
    carpeta.mkdir(parents=True, exist_ok=True)

    # Un nombre repetido dentro del mismo mensaje no se pisa.
    vistos: Dict[str, int] = {}
    for nombre, contenido in adjuntos:
        repetido = vistos.get(nombre, 0)
        vistos[nombre] = repetido + 1
        final = nombre if repetido == 0 else _nombre_con_sufijo(nombre, repetido)
        (carpeta / final).write_bytes(contenido)

    # Ficha: lo mismo que la linea del log, para poder auditar la carpeta
    # por si sola (un adjunto suelto ya no pierde su contexto).
    asunto_ficha = asunto.replace("\r", " ").replace("\n", " ")
    (carpeta / FICHERO_METADATA).write_text(
        f"fecha: {datetime.now().isoformat(timespec='seconds')}\n"
        f"de: {remitente}\n"
        f"para: {', '.join(f'{d}@{config.dominio}' for d in destinos)}\n"
        f"asunto: {asunto_ficha}\n"
        f"adjuntos: {', '.join(nombre for nombre, _ in adjuntos)}\n",
        encoding="utf-8",
    )
    return carpeta


def registrar_envio(config: Config, destinos: List[str], data: bytes) -> None:
    """Anade UNA linea por mensaje al log de envios.  NUNCA lanza excepciones.

    Llamada desde :meth:`buzon.Buzones.entregar`, punto de entrega comun
    del SMTP y del webmail.  ``destinos`` son nombres de usuario locales
    en el orden aceptado: SE completan con ``config.dominio`` para el log.

    Si el mensaje lleva adjuntos, ademas guarda su copia FISICA en
    ``config.copia_adjuntos`` (una carpeta por mensaje; ``None`` la
    desactiva).  Un fallo al escribir el log o la copia solo se anota en
    el logger: el correo ya esta entregado y no se toca.
    """
    try:
        remitente, asunto, adjuntos = _partes_mensaje(data)
        para = ", ".join(
            _sin_separador(f"{d}@{config.dominio}") for d in destinos
        )
        texto_adjuntos = (
            ", ".join(
                f"{_sin_separador(nombre)} ({_kb(len(contenido))} KB)"
                for nombre, contenido in adjuntos
            )
            if adjuntos else "ninguno"
        )
        timestamp = datetime.now().isoformat(timespec="seconds")
        linea = (
            f"{timestamp}{SEPARADOR}de: {_sin_separador(remitente)}"
            f"{SEPARADOR}para: {para}{SEPARADOR}asunto: "
            f"{_sin_separador(asunto)}{SEPARADOR}adjuntos: "
            f"{_sin_separador(texto_adjuntos)}\n"
        )

        with _lock:
            directorio = Path(config.ruta_logs)
            directorio.mkdir(parents=True, exist_ok=True)   # tambien al escribir
            with open(directorio / NOMBRE_FICHERO, "a", encoding="utf-8") as fich:
                fich.write(linea)

            # Copia fisica de los adjuntos (si los hay y esta activada).
            if adjuntos and getattr(config, "copia_adjuntos", None) is not None:
                try:
                    _copiar_adjuntos(config, destinos, remitente, asunto,
                                     adjuntos, data)
                except Exception:  # noqa: BLE001
                    log.exception("no pude guardar la copia de adjuntos en %s",
                                  getattr(config, "copia_adjuntos", "?"))
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
