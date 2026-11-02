"""utilidades.py -- mini cliente SMTP y entorno de pruebas.

``smtplib`` ocultaria el protocolo que queremos comprobar, asi que las
pruebas hablan el SMTP a mano: leen respuestas multilinnea ("250-..." hasta
"250 ") y envian comandos tal y como haria un cliente real.

:class:`Entorno` levanta un servidor SMTP real en 127.0.0.1 con puerto
efimero y buzones en un directorio temporal: sin privilegios, sin tocar el
config.ini y reproducible en cualquier SO (incluidas las VMs Windows).
"""

import shutil
import socket
import tempfile
from pathlib import Path
from typing import List, Optional

from buzon import Buzones
from config import Config
from smtp_sesion import SesionSMTP
from srv_tcp import ServidorTCP


class ClienteSMTP:
    """Cliente SMTP minimo para dialogar contra el servidor en pruebas."""

    def __init__(self, puerto: int, host: str = "127.0.0.1", timeout: float = 5):
        self.sock = socket.create_connection((host, puerto), timeout=timeout)
        self.fp = self.sock.makefile("rb")

    # ------------------------------------------------------------------ #

    def leer_respuesta(self) -> List[str]:
        """Lee una respuesta completa: lineas 'NNN-' hasta la 'NNN ' final.

        Devuelve [] si la conexion se cerro (EOF).
        """
        lineas: List[str] = []
        while True:
            linea = self.fp.readline()
            if not linea:
                break  # el servidor cerro
            texto = linea.decode("utf-8", "replace").rstrip("\r\n")
            lineas.append(texto)
            if len(texto) >= 4 and texto[3] == " ":
                break
        return lineas

    def enviar(self, comando: str) -> List[str]:
        """Envia un comando con CRLF y devuelve la respuesta."""
        self.sock.sendall(comando.encode("utf-8") + b"\r\n")
        return self.leer_respuesta()

    def enviar_data(self, datos: bytes) -> List[str]:
        """Envia el bloque DATA (debe terminar en CRLF.CRLF) y responde."""
        self.sock.sendall(datos)
        return self.leer_respuesta()

    def cerrar(self) -> None:
        try:
            self.fp.close()
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.cerrar()


def codigo(respuesta: List[str]) -> str:
    """Devuelve el codigo SMTP ('250', '550', ...) de la respuesta."""
    return respuesta[0][:3] if respuesta else "EOF"


def mensaje(de: str, para: str, cuerpo: str = "hola",
            asunto: str = "prueba") -> bytes:
    """Compone un mensaje SMTP sencillo terminado en CRLF.CRLF."""
    data = (
        f"From: {de}\r\nTo: {para}\r\nSubject: {asunto}\r\n"
        f"Date: Tue, 02 Nov 2026 12:00:00 +0100\r\n\r\n{cuerpo}\r\n"
    )
    return data.encode("utf-8") + b".\r\n"


# ---------------------------------------------------------------------- #
# Entorno de pruebas
# ---------------------------------------------------------------------- #

class Entorno:
    """Servidor SMTP de prueba + buzones temporales."""

    def __init__(self, servidor: ServidorTCP, config: Config,
                 buzones: Buzones, ruta_tmp: str):
        self.servidor = servidor
        self.config = config
        self.buzones = buzones
        self.ruta_tmp = ruta_tmp

    @property
    def puerto(self) -> int:
        return self.servidor.puerto

    def conectar(self) -> ClienteSMTP:
        return ClienteSMTP(self.puerto)

    def parar(self) -> None:
        self.servidor.parar()
        shutil.rmtree(self.ruta_tmp, ignore_errors=True)


def arrancar_entorno(usuarios=("pepe", "ana"), **kwargs) -> Entorno:
    """Levanta un servidor SMTP de prueba.

    ``usuarios`` crea buzones de ejemplo; ``kwargs`` son campos de
    :class:`Config` (``max_conexiones``, ``timeout_seg``,
    ``max_tamano_mb``...).
    """
    ruta_tmp = tempfile.mkdtemp(prefix="correo_test_")
    config = Config(
        smtp_host="127.0.0.1",
        smtp_puerto=0,
        ruta_base=Path(ruta_tmp) / "buzones",
        ruta_usuarios=Path(ruta_tmp) / "usuarios.json",
        **kwargs,
    )
    buzones = Buzones(config)
    for usuario in usuarios:
        buzones.alta(usuario)

    servidor = ServidorTCP(
        host="127.0.0.1",
        puerto=0,
        max_conexiones=config.max_conexiones,
        timeout_seg=config.timeout_seg,
        manejar=lambda sock, addr: SesionSMTP(
            sock, addr, config, buzones=buzones
        ).ejecutar(),
        mensaje_rechazo=b"421 4.7.0 Demasiadas conexiones\r\n",
    )
    servidor.arrancar()
    return Entorno(servidor, config, buzones, ruta_tmp)
