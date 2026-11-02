"""buzon.py -- buzones locales, gestion de usuarios y entrega de mensajes.

Este modulo es el corazon de la seguridad anti-open-relay: la sesion SMTP
solo llega a entregar un mensaje si :meth:`Buzones.existe` confirma que el
destinatario es un usuario local.

Almacenamiento (facil de inspeccionar como evidencia):

    buzones/
      pepe/
        mensajes/20261102-153012-ab12cd34.eml   # mensaje completo (headers + cuerpo)
        adjuntos/20261102-.../Confidencial.pdf   # adjuntos extraidos (iteracion 3)

El listado de usuarios vive en ``usuarios.json``: {"usuarios": [...]}.
"""

import json
import logging
import re
import threading
import uuid
from datetime import datetime
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Dict, List, Optional

from config import Config
from correo_api import extraer_adjuntos

log = logging.getLogger("correo.buzon")

# Un nombre de usuario seguro SOLO admite letras, numeros, punto, guion y
# guion bajo: asi nadie puede colar "../../etc/passwd" en la ruta del buzon.
RE_USUARIO = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

# Identificadores de mensaje generados por entregar(): letras, numeros,
# guiones y guion bajo (sin puntos ni barras: imposible salirse de la
# carpeta mensajes/).
RE_MSG_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class Buzones:
    """Gestiona usuarios y mensajes en disco, con un lock de escritura."""

    def __init__(self, config: Config):
        self.config = config
        self.ruta_base = Path(config.ruta_base)
        self.ruta_usuarios = Path(config.ruta_usuarios)
        self._lock = threading.Lock()
        self._usuarios: List[str] = []
        self._mtime_usuarios = None
        self._sincronizar()

    # ------------------------------------------------------------------ #
    # Usuarios
    # ------------------------------------------------------------------ #

    def _cargar(self) -> List[str]:
        if self.ruta_usuarios.exists():
            try:
                datos = json.loads(self.ruta_usuarios.read_text("utf-8"))
                return list(datos.get("usuarios", []))
            except (OSError, ValueError) as exc:
                log.error("no pude leer %s: %s", self.ruta_usuarios, exc)
        return []

    def _sincronizar(self) -> None:
        """Recarga usuarios.json si otro proceso lo ha cambiado.

        Importante en la practica: el CLI ``usuario alta`` corre en un
        proceso distinto al del servidor; sin esto, un buzón creado con
        el servidor ya arrancado seguiria dando 550 hasta reiniciarlo.
        (Se llama siempre con el lock adquirido.)
        """
        try:
            mtime = self.ruta_usuarios.stat().st_mtime_ns
        except OSError:
            mtime = None
        if mtime != self._mtime_usuarios:
            self._usuarios = self._cargar()
            self._mtime_usuarios = mtime

    def _guardar(self) -> None:
        self.ruta_usuarios.parent.mkdir(parents=True, exist_ok=True)
        self.ruta_usuarios.write_text(
            json.dumps({"usuarios": sorted(self._usuarios)},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            self._mtime_usuarios = self.ruta_usuarios.stat().st_mtime_ns
        except OSError:
            self._mtime_usuarios = None

    def listar(self) -> List[str]:
        with self._lock:
            self._sincronizar()
            return sorted(self._usuarios)

    def existe(self, usuario: str) -> bool:
        with self._lock:
            self._sincronizar()
            return usuario in self._usuarios

    def alta(self, usuario: str) -> None:
        """Crea un buzón.  ValueError si el nombre es inseguro o repetido."""
        if not RE_USUARIO.match(usuario):
            raise ValueError(
                f"usuario no valido: {usuario!r} (solo letras, numeros, "
                ". guion y guion bajo)"
            )
        with self._lock:
            self._sincronizar()
            if usuario in self._usuarios:
                raise ValueError(f"el usuario {usuario!r} ya existe")
            self._usuarios.append(usuario)
            self._guardar()
        (self.ruta_base / usuario / "mensajes").mkdir(
            parents=True, exist_ok=True
        )
        log.info("alta de buzón: %s@%s", usuario, self.config.dominio)

    def baja(self, usuario: str) -> None:
        """Elimina un buzón de la lista (los ficheros no se borran)."""
        with self._lock:
            self._sincronizar()
            if usuario not in self._usuarios:
                raise ValueError(f"el usuario {usuario!r} no existe")
            self._usuarios.remove(usuario)
            self._guardar()
        log.info("baja de buzón: %s@%s", usuario, self.config.dominio)

    # ------------------------------------------------------------------ #
    # Entrega
    # ------------------------------------------------------------------ #

    def entregar(self, destinos: List[str], data: bytes) -> str:
        """Guarda ``data`` en el buzón de cada destino local.

        Devuelve el identificador de cola ( tambien usado como nombre de
        fichero).  ValueError si un destino no es local/valido.
        """
        cola_id = (
            datetime.now().strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:8]
        )
        for destino in destinos:
            if not RE_USUARIO.match(destino):
                raise ValueError(f"destino inseguro: {destino!r}")
            with self._lock:
                self._sincronizar()
                if destino not in self._usuarios:
                    raise ValueError(f"destino desconocido: {destino!r}")
            carpeta = self.ruta_base / destino / "mensajes"
            carpeta.mkdir(parents=True, exist_ok=True)
            (carpeta / f"{cola_id}.eml").write_bytes(data)

            # Adjuntos extraidos aparte: mas faciles de inspeccionar como
            # evidencia (un .pdf se abre sin parsear el .eml).
            try:
                adjuntos = extraer_adjuntos(
                    data, self.ruta_base / destino / "adjuntos" / cola_id
                )
                if adjuntos:
                    log.info("adjuntos de %s: %s", cola_id, ", ".join(adjuntos))
            except Exception:  # noqa: BLE001 -- un fallo aqui no pierde el correo
                log.exception("no pude extraer adjuntos de %s", cola_id)
        log.info("entregado %s a %s", cola_id, ", ".join(destinos))
        return cola_id

    # ------------------------------------------------------------------ #
    # Lectura (la usa el webmail)
    # ------------------------------------------------------------------ #

    def bandeja(self, usuario: str) -> List[Dict[str, str]]:
        """Resumen de los mensajes del buzón, del mas reciente al mas antiguo."""
        carpeta = self.ruta_base / usuario / "mensajes"
        if not carpeta.is_dir():
            return []
        resumen = []
        for fichero in sorted(carpeta.glob("*.eml"), reverse=True):
            data = fichero.read_bytes()
            try:
                msg = BytesParser(policy=policy.default).parsebytes(data)
                resumen.append({
                    "id": fichero.stem,
                    "de": str(msg.get("From", "")),
                    "para": str(msg.get("To", "")),
                    "asunto": str(msg.get("Subject", "(sin asunto)")),
                    "fecha": str(msg.get("Date", "")),
                    "tamaño": str(len(data)),
                })
            except Exception:  # noqa: BLE001 -- un .eml corrupto no rompe la bandeja
                resumen.append({
                    "id": fichero.stem, "de": "?", "para": "?",
                    "asunto": "(mensaje ilegible)", "fecha": "", "tamaño": "?",
                })
        return resumen

    def leer_mensaje(self, usuario: str, msg_id: str) -> Optional[bytes]:
        """Devuelve el .eml completo, o None si no existe (o id inseguro)."""
        if not RE_USUARIO.match(usuario) or not RE_MSG_ID.match(msg_id):
            return None
        fichero = self.ruta_base / usuario / "mensajes" / f"{msg_id}.eml"
        if not fichero.is_file():
            return None
        return fichero.read_bytes()
