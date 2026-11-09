"""smtp_sesion.py -- protocolo SMTP implementado desde cero (RFC 5321).

Cada conexion de cliente crea una :class:`SesionSMTP` con su socket.  El
ciclo de vida es:

1. enviar el saludo ``220``;
2. leer lineas de comando, validarlas contra el ESTADO de la sesion y
   responder con el codigo SMTP correspondiente;
3. cerrar en ``QUIT`` (``221``), timeout (``421``) o desconexion del cliente.

Maquina de estados (que comandos son legales en cada momento):

    inicio --HELO/EHLO--> saludado --MAIL FROM--> mail
        --RCPT TO--> rcpt (acepta varios) --DATA--> dato --.--> saludado

Codigos principales:
    500 comando desconocido / linea demasiado larga
    501 sintaxis del comando (falta <direccion>, argumentos...)
    503 comando fuera de orden (MAIL sin HELO, DATA sin RCPT, RCPT sin MAIL)
    550 destinatario desconocido            (validacion de buzones)
    554 relay denegado: dominio no local    (anti-open-relay)
    552 mensaje demasiado grande            (limite de DATA)
    421 sin huecos de conexion / timeout    (limites generales)

Nota de seguridad: ``NOOP``, ``RSET`` y ``QUIT`` se aceptan en cualquier
momento (incluido antes del HELO), como en los servidores reales.
"""

import logging
import socket
from email.utils import formatdate
from typing import TYPE_CHECKING, List, Optional, Tuple

from buzon import Buzones
from correo_api import extraer_direccion, parsear_direccion

if TYPE_CHECKING:  # solo para el tipado; evita import circular
    from config import Config

log = logging.getLogger("correo.smtp")

# Longitud maxima de linea segun RFC 5321 (998 + CRLF).
MAX_LINEA = 1000

# Marcador interno que devuelve _leer_linea cuando la linea real era tan
# larga que hubo que drenarla por fragmentos (no puede confundirse con un
# comando util: la respuesta en cualquier caso es un 500).
_MARCA_LARGA = b"<LINEA-LARGA>\n"


class SesionSMTP:
    """Maneja una conexion SMTP completa, de principio a fin."""

    # Estados de la maquina
    ESTADO_INICIO = "inicio"        # sin HELO/EHLO todavia
    ESTADO_SALUDADO = "saludado"    # HELO/EHLO hecho; sin transaccion abierta
    ESTADO_MAIL = "mail"            # MAIL FROM aceptado
    ESTADO_RCPT = "rcpt"            # un o mas RCPT TO aceptados
    ESTADO_DATO = "dato"            # dentro del bloque DATA

    def __init__(self, sock: socket.socket, addr: tuple, config: "Config",
                 buzones: Optional[Buzones] = None):
        self.sock = sock
        self.addr = addr
        self.config = config
        self.buzones = buzones
        self.estado = self.ESTADO_INICIO
        self.helo: Optional[str] = None      # dominio que declaro el cliente
        self.mail_de: Optional[str] = None   # remitente del MAIL FROM actual
        self.rcpt_a: List[str] = []          # destinatarios del RCPT actual

        # makefile da un readline() buffered sobre el socket.
        self._fp = sock.makefile("rb")
        self._cerrar = False

    # ------------------------------------------------------------------ #
    # Bucle principal
    # ------------------------------------------------------------------ #

    def ejecutar(self) -> None:
        """Saludo + bucle de comandos.  Termina cuando la sesion se cierra."""
        self._escribir(f"220 {self.config.dominio} ESMTP Practica IFOR")

        while not self._cerrar:
            try:
                linea = self._leer_linea()
            except socket.timeout:
                self._responder_si_puedo("421 4.4.2 Tiempo de espera agotado")
                log.info("timeout con %s", self.addr)
                break
            except OSError:
                break  # cliente desaparecido sin avisar

            if not linea:  # EOF: el cliente cerro sin QUIT
                log.info("desconexion abrupta de %s", self.addr)
                break

            if linea == _MARCA_LARGA or len(linea) > MAX_LINEA:
                self._responder("500 5.5.2 Linea de comando demasiado larga")
                continue

            texto = linea.decode("latin-1").rstrip("\r\n")
            self._procesar(texto)

        try:
            self._fp.close()
        except OSError:
            pass

    def _leer_linea(self) -> bytes:
        """Lee UNA linea de comando acotando la memoria.

        ``readline(MAX_LINEA + 3)`` nunca devuelve mas de ese tope: si la
        linea no trae salto de linea dentro, drenamos el resto de la linea
        por fragmentos (hasta ver ``\\n``) y devolvemos _MARCA_LARGA.  Asi
        un cliente que mande gigabytes sin CRLF no puede agotar la RAM y,
        ademas, la sesion queda alineada para el siguiente comando.

        Puede lanzar ``socket.timeout`` u ``OSError``; ``ejecutar`` los
        trata.  Devuelve ``b""`` en EOF.
        """
        linea = self._fp.readline(MAX_LINEA + 3)
        if not linea or linea.endswith(b"\n"):
            return linea                      # EOF o linea completa (corta o no)
        # Sin salto de linea y lleno el tope: drenamos hasta encontrarla.
        while True:
            trozo = self._fp.readline(MAX_LINEA + 3)
            if not trozo or trozo.endswith(b"\n"):
                break                         # fin de linea (o EOF drenando)
        return _MARCA_LARGA

    # ------------------------------------------------------------------ #
    # Procesamiento de comandos
    # ------------------------------------------------------------------ #

    def _procesar(self, texto: str) -> None:
        verb, _, resto = texto.partition(" ")
        verb = verb.upper()
        log.debug("<- %s", texto)

        if not verb:
            self._responder("500 5.5.2 Linea vacia")
            return

        manejar = {
            "HELO": self._cmd_helo,
            "EHLO": self._cmd_ehlo,
            "MAIL": self._cmd_mail,
            "RCPT": self._cmd_rcpt,
            "DATA": self._cmd_data,
            "RSET": self._cmd_rset,
            "NOOP": self._cmd_noop,
            "QUIT": self._cmd_quit,
            "VRFY": self._cmd_vrfy,
        }.get(verb)

        if manejar is None:
            self._responder("500 5.5.2 Comando no reconocido")
            return
        manejar(resto.strip())

    # -- comandos de sesion --------------------------------------------- #

    def _cmd_helo(self, resto: str) -> None:
        if not resto:
            self._responder("501 5.5.4 Uso: HELO <dominio>")
            return
        self._reiniciar_transaccion()
        self.estado = self.ESTADO_SALUDADO
        self.helo = resto
        self._responder(f"250 {self.config.dominio}")

    def _cmd_ehlo(self, resto: str) -> None:
        if not resto:
            self._responder("501 5.5.4 Uso: EHLO <dominio>")
            return
        self._reiniciar_transaccion()
        self.estado = self.ESTADO_SALUDADO
        self.helo = resto
        # Respuesta multilinnea: "250-" continua, "250 " termina.
        self._escribir(f"250-{self.config.dominio}")
        self._escribir("250-8BITMIME")
        self._escribir(f"250 SIZE {self.config.max_tamano_bytes}")

    def _cmd_rset(self, resto: str) -> None:
        del resto
        # RSET solo descarta la transaccion (MAIL/RCPT), no olvida el HELO.
        self._reiniciar_transaccion()
        if self.estado in (self.ESTADO_MAIL, self.ESTADO_RCPT, self.ESTADO_DATO):
            self.estado = self.ESTADO_SALUDADO
        self._responder("250 2.0.0 Ok")

    def _cmd_noop(self, resto: str) -> None:
        del resto
        self._responder("250 2.0.0 Ok")

    def _cmd_quit(self, resto: str) -> None:
        del resto
        self._responder(f"221 2.0.0 {self.config.dominio} cerrando")
        self._cerrar = True

    def _cmd_vrfy(self, resto: str) -> None:
        # Comprueba si la direccion es un buzón local conocido.
        direccion = resto[1:-1] if resto.startswith("<") else resto
        partes = parsear_direccion(direccion)
        if partes is None:
            self._responder("501 5.5.4 Uso: VRFY <usuario@dominio>")
            return
        usuario, dominio = partes
        if (dominio.lower() == self.config.dominio.lower()
                and self.buzones and self.buzones.existe(usuario)):
            self._responder(f"250 2.1.5 <{direccion}>")
        else:
            self._responder("550 5.1.1 Destinatario desconocido")

    # -- comandos de transaccion ---------------------------------------- #

    def _cmd_mail(self, resto: str) -> None:
        # 1) Orden de la secuencia: primero se saluda y no se puede repetir.
        if self.estado == self.ESTADO_INICIO:
            self._responder("503 5.5.1 Se espera HELO/EHLO primero")
            return
        if self.estado != self.ESTADO_SALUDADO:
            self._responder("503 5.5.1 Transaccion en curso; use RSET para reiniciar")
            return
        # 2) Sintaxis: MAIL FROM:<direccion>
        direccion = extraer_direccion(resto, "FROM:")
        if direccion is None:
            self._responder("501 5.5.4 Uso: MAIL FROM:<direccion>")
            return
        # El remitente NO se valida contra los buzones: cualquiera puede
        # decir quien es (como en Gmail con cuentas ajenas).  Lo que se
        # valida rigorosamente es el DESTINO (anti open-relay).
        self.mail_de = direccion
        self.estado = self.ESTADO_MAIL
        self._responder("250 2.1.0 Ok")

    def _cmd_rcpt(self, resto: str) -> None:
        # 1) Orden: hace falta un MAIL FROM abierto.
        if self.estado not in (self.ESTADO_MAIL, self.ESTADO_RCPT):
            self._responder("503 5.5.1 Se espera MAIL FROM primero")
            return
        # 2) Sintaxis: RCPT TO:<direccion>
        direccion = extraer_direccion(resto, "TO:")
        if direccion is None or direccion == "":
            self._responder("501 5.5.4 Uso: RCPT TO:<direccion>")
            return
        partes = parsear_direccion(direccion)
        if partes is None:
            self._responder("501 5.5.4 Direccion invalida")
            return
        usuario, dominio = partes

        # 3) SEGURIDAD: dominio distinto del local -> relay denegado (554).
        if dominio.lower() != self.config.dominio.lower():
            log.warning("RELAY DENEGADO de %s a <%s> (cliente %s)",
                        self.mail_de, direccion, self.addr[0])
            self._responder("554 5.7.1 Relay denegado: solo dominio local")
            return
        # 4) SEGURIDAD: el buzón tiene que existir (550).
        if not self.buzones or not self.buzones.existe(usuario):
            self._responder("550 5.1.1 Destinatario desconocido")
            return

        self.rcpt_a.append(usuario)
        self.estado = self.ESTADO_RCPT
        self._responder("250 2.1.5 Ok")

    def _cmd_data(self, resto: str) -> None:
        if resto:
            self._responder("501 5.5.4 DATA no admite argumentos")
            return
        if self.estado != self.ESTADO_RCPT:
            self._responder("503 5.5.1 Se espera RCPT TO primero")
            return
        self._responder("354 Introduzca el mensaje; termine con <CRLF>.<CRLF>")

        datos, motivo = self._recibir_data()
        if motivo is not None:
            self._responder_datos_rechazados(motivo)
            return

        # Entrega: se prepende una cabecera Received con trazas del origen
        # (cliente, HELO, fecha) -- util como evidencia para la practica.
        cabecera = (
            f"Received: from {self.helo or 'desconocido'} ({self.addr[0]})\r\n"
            f"\tby {self.config.dominio} (servidor IFOR) with ESMTP;\r\n"
            f"\t{formatdate(localtime=True)}\r\n"
        ).encode("utf-8")

        try:
            cola_id = self.buzones.entregar(
                self.rcpt_a, cabecera + datos, origen=self.addr[0])
        except Exception as exc:  # noqa: BLE001 -- fallo de disco u otro
            log.exception("error entregando mensaje de %s", self.addr)
            self._responder(f"451 4.3.0 Error interno: {exc}")
            self._reiniciar_transaccion()
            self.estado = self.ESTADO_SALUDADO
            return

        self._responder(
            f"250 2.0.0 Ok: queue {cola_id} para "
            f"{', '.join(a + '@' + self.config.dominio for a in self.rcpt_a)}"
        )
        # Tras entregar, la sesion vuelve a "saludado": se admite otro
        # mensaje sin repetir HELO (así lo hacen los servidores reales).
        self._reiniciar_transaccion()
        self.estado = self.ESTADO_SALUDADO

    def _responder_datos_rechazados(self, motivo: str) -> None:
        """El bloque DATA se ha descartado: informa y vuelve a 'saludado'."""
        if motivo == "excedido":
            self._responder(
                f"552 5.3.4 Mensaje demasiado grande "
                f"(maximo {self.config.max_tamano_mb} MB)"
            )
        elif motivo == "linea":
            self._responder("500 5.5.2 Linea demasiado larga en el mensaje")
        # "timeout" y "conexion" ya han cerrado la sesion dentro de _recibir_data
        if motivo in ("timeout", "conexion"):
            return
        self._reiniciar_transaccion()
        self.estado = self.ESTADO_SALUDADO

    # ------------------------------------------------------------------ #
    # Lectura del bloque DATA
    # ------------------------------------------------------------------ #

    def _recibir_data(self) -> Tuple[Optional[bytes], Optional[str]]:
        """Lee el mensaje hasta <CRLF>.<CRLF> aplicando las reglas de la RFC.

        Devuelve ``(datos, None)`` si todo ha ido bien, o ``(None, motivo)``
        con motivo en: ``"excedido"`` (demasiado grande), ``"linea"``
        (linea larguisima), ``"timeout"`` (421 enviado) o ``"conexion"``
        (cliente desaparecido; la sesion se cierra).

        Detalles que suelen fallar en implementaciones caseras:

        * **dot-unstuffing**: en DATA cualquier linea que empieza por ``.``
          pierde ese punto (el cliente lo duplica para evitar que un
          cuerpo con ``.\r\n`` termine el mensaje antes de tiempo);
        * tras exceder el limite se sigue LEYENDO hasta el ``.`` final:
          si no, la sesion se desincroniza y todos los comandos
          posteriores se interpretarian como cuerpo de mensaje;
        * ``readline(MAX_LINEA + 3)`` limita la memoria: una linea sin
          salto de linea que supere ese tope se marca como ``linea`` y se
          descarta por fragmentos hasta ver el fin de linea.
        """
        datos = bytearray()
        excedido = False
        linea_larga = False
        en_linea_larga = False

        while True:
            try:
                linea = self._fp.readline(MAX_LINEA + 3)
            except socket.timeout:
                self._responder_si_puedo("421 4.4.2 Tiempo de espera agotado")
                log.info("timeout dentro de DATA con %s", self.addr)
                self._cerrar = True
                return None, "timeout"
            except OSError:
                self._cerrar = True
                return None, "conexion"

            if not linea:  # EOF a mitad de mensaje
                log.info("desconexion a mitad de DATA de %s", self.addr)
                self._cerrar = True
                return None, "conexion"

            # Fin del mensaje: una linea que contiene solo un punto.
            if not en_linea_larga and linea in (b".\r\n", b".\n"):
                break

            # Fragmento sin salto de linea: o es una linea normal completa
            # o es el trozo inicial de una linea demasiado larga.
            if len(linea) >= MAX_LINEA + 3 and not linea.endswith(b"\n"):
                en_linea_larga = True
                linea_larga = True
                continue
            if en_linea_larga:
                # Ultimo trozo de la linea larga (acaba en \n): lo descartamos.
                en_linea_larga = False
                continue

            # Linea completa: dot-unstuffing (quitamos el punto duplicado).
            if linea.startswith(b"."):
                linea = linea[1:]

            if excedido:
                pass  # ya solo drenamos: el mensaje se descartara entero
            elif len(datos) + len(linea) > self.config.max_tamano_bytes:
                # No guardamos, pero seguimos leyendo hasta el "." final.
                excedido = True
            else:
                datos.extend(linea)

        if excedido:
            return None, "excedido"
        if linea_larga:
            return None, "linea"
        return bytes(datos), None

    # ------------------------------------------------------------------ #
    # Utilidades
    # ------------------------------------------------------------------ #

    def _reiniciar_transaccion(self) -> None:
        """Olvida remitente/destinatarios (se usa en HELO, RSET y tras DATA)."""
        self.mail_de = None
        self.rcpt_a = []

    def _escribir(self, linea: str) -> None:
        """Escribe ``linea`` completa con CRLF (el gestor de errores corta)."""
        try:
            self.sock.sendall(linea.encode("utf-8", "replace") + b"\r\n")
        except OSError:
            self._cerrar = True

    def _responder(self, linea: str) -> None:
        log.debug("-> %s", linea)
        self._escribir(linea)

    def _responder_si_puedo(self, linea: str) -> None:
        """Igual que :meth:`_responder`, tolerando socket ya cerrado."""
        if not self._cerrar:
            self._responder(linea)
