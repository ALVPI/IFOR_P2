"""config.py -- carga de la configuracion del sistema de correo.

Lee ``config.ini`` (si existe) y completa lo que falte con los valores por
defecto de la dataclass :class:`Config`.  Todas las rutas relativas se
resuelven contra este directorio (``servidor/``), de modo que el programa
funcione igual sea cual sea el directorio de trabajo (importante en las
VMs Windows, donde se arranca con doble clic en un .bat).
"""

import configparser
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Directorio donde viven el codigo y la configuracion.
DIR_BASE = Path(__file__).resolve().parent


@dataclass
class Config:
    """Parametros operativos del servidor de correo."""

    smtp_host: str = "0.0.0.0"
    smtp_puerto: int = 25          # 25 requiere administrador en Windows
    webmail_host: str = "0.0.0.0"
    webmail_puerto: int = 8080
    dominio: str = "empresa.local"  # dominio LOCAL: lo unico que se acepta entregar
    ruta_base: Path = DIR_BASE / "buzones"
    ruta_usuarios: Path = DIR_BASE / "usuarios.json"
    ruta_logs: Path = DIR_BASE / "logs"    # log de envios (auditoria)
    copia_adjuntos: Optional[Path] = (
        DIR_BASE / "adjuntos_enviados"     # copia FISICA de los adjuntos
    )                                      # enviados (None = desactivado)
    max_conexiones: int = 20       # conexiones SMTP simultaneas permitidas
    max_tamano_mb: int = 25        # limite de tamano del mensaje en DATA
    timeout_seg: int = 120         # inactividad maxima por conexion

    @property
    def max_tamano_bytes(self) -> int:
        return self.max_tamano_mb * 1024 * 1024


def cargar_config(ruta: Optional[Path] = None) -> Config:
    """Devuelve la :class:`Config` leida de ``ruta`` (por defecto config.ini)."""
    ruta = Path(ruta) if ruta else DIR_BASE / "config.ini"
    lector = configparser.ConfigParser()
    cfg = Config()

    if ruta.exists():
        lector.read(ruta, encoding="utf-8")

    if lector.has_section("smtp"):
        cfg.smtp_host = lector.get("smtp", "host", fallback=cfg.smtp_host)
        cfg.smtp_puerto = lector.getint("smtp", "puerto", fallback=cfg.smtp_puerto)
    if lector.has_section("webmail"):
        cfg.webmail_host = lector.get("webmail", "host", fallback=cfg.webmail_host)
        cfg.webmail_puerto = lector.getint(
            "webmail", "puerto", fallback=cfg.webmail_puerto
        )
    if lector.has_section("correo"):
        cfg.dominio = lector.get("correo", "dominio", fallback=cfg.dominio)
    if lector.has_section("rutas"):
        base = Path(lector.get("rutas", "base", fallback=""))
        if str(base):
            cfg.ruta_base = base if base.is_absolute() else DIR_BASE / base
        usu = Path(lector.get("rutas", "usuarios", fallback=""))
        if str(usu):
            cfg.ruta_usuarios = usu if usu.is_absolute() else DIR_BASE / usu
    if lector.has_section("log"):
        dirlog = Path(lector.get("log", "directorio", fallback=""))
        if str(dirlog):
            cfg.ruta_logs = dirlog if dirlog.is_absolute() else DIR_BASE / dirlog
        # Copia de adjuntos: valor vacio -> desactivado (None).
        if lector.has_option("log", "copia_adjuntos"):
            crudo = lector.get("log", "copia_adjuntos").strip()
            if not crudo:
                cfg.copia_adjuntos = None
            else:
                ruta_copia = Path(crudo)
                cfg.copia_adjuntos = (ruta_copia if ruta_copia.is_absolute()
                                      else DIR_BASE / ruta_copia)
    if lector.has_section("limites"):
        cfg.max_conexiones = lector.getint(
            "limites", "max_conexiones", fallback=cfg.max_conexiones
        )
        cfg.max_tamano_mb = lector.getint(
            "limites", "max_tamano_mb", fallback=cfg.max_tamano_mb
        )
        cfg.timeout_seg = lector.getint(
            "limites", "timeout_seg", fallback=cfg.timeout_seg
        )

    return cfg
