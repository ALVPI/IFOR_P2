"""srv_tcp.py -- servidor TCP generico.

Responsabilidades (y solo estas):

* abrir el socket de escucha y aceptar conexiones;
* atender cada conexion en su propio hilo;
* aplicar el limite de conexiones simultaneas (quien se excede recibe
  ``mensaje_rechazo`` y se corta);
* aplicar el timeout de inactividad a cada conexion;
* registrar eventos y liberar todo al parar (importante en los tests).

Este modulo NO entiende de SMTP: el protocolo vive en ``smtp_sesion.py``.
El unico hueco protocolico es ``mensaje_rechazo`` (el421 que envia el SMTP
cuando no quedan huecos), que se pasa desde ``servidor.py``.
"""

import logging
import socket
import threading
from typing import Callable, Optional

log = logging.getLogger("correo.tcp")


class ServidorTCP:
    """Bucle de aceptacion con un hilo por cliente.

    ``manejar(sock, addr)`` se ejecuta en el hilo de cada conexion; cuando
    termina (o falla) se cierra el socket y se descuenta del contador.
    """

    def __init__(
        self,
        host: str,
        puerto: int,
        max_conexiones: int,
        timeout_seg: float,
        manejar: Callable[[socket.socket, tuple], None],
        mensaje_rechazo: Optional[bytes] = None,
    ):
        self.host = host
        self.puerto = puerto                 # tras arrancar(): puerto real (0 -> efimero)
        self.max_conexiones = max_conexiones
        self.timeout_seg = timeout_seg
        self.manejar = manejar
        self.mensaje_rechazo = mensaje_rechazo

        self._sock_escucha: Optional[socket.socket] = None
        self._hilo_bucle: Optional[threading.Thread] = None
        self._parar = threading.Event()
        self._lock = threading.Lock()
        self._activas: dict[socket.socket, threading.Thread] = {}

    # ------------------------------------------------------------------ #

    def arrancar(self, bloqueante: bool = False) -> None:
        """Abre el socket de escucha y empieza a aceptar conexiones.

        Con ``bloqueante=False`` (uso normal y tests) el bucle corre en un
        hilo daemon y ``arrancar`` devuelve enseguida.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.puerto))
        sock.listen(5)
        self.puerto = sock.getsockname()[1]  # resuelve puerto 0 -> puerto efimero
        self._sock_escucha = sock
        self._parar.clear()
        log.info("escuchando en %s:%s", self.host, self.puerto)

        if bloqueante:
            self._bucle_aceptar()
        else:
            self._hilo_bucle = threading.Thread(
                target=self._bucle_aceptar, name="tcp-aceptar", daemon=True
            )
            self._hilo_bucle.start()

    def parar(self) -> None:
        """Cierra el listener y todas las conexiones activas."""
        self._parar.set()
        if self._sock_escucha:
            try:
                self._sock_escucha.close()
            except OSError:
                pass
        with self._lock:
            activas = list(self._activas)
        for sock in activas:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        log.info("servidor detenido")

    # ------------------------------------------------------------------ #

    def _bucle_aceptar(self) -> None:
        assert self._sock_escucha is not None
        while not self._parar.is_set():
            try:
                sock, addr = self._sock_escucha.accept()
            except OSError:
                # socket cerrado (parar) u otro error de red: salimos
                break

            with self._lock:
                lleno = len(self._activas) >= self.max_conexiones
                if not lleno:
                    hilo = threading.Thread(
                        target=self._atender,
                        args=(sock, addr),
                        name=f"tcp-{addr[0]}:{addr[1]}",
                        daemon=True,
                    )
                    self._activas[sock] = hilo

            if lleno:
                log.warning("conexion rechazada desde %s: limite alcanzado", addr)
                self._rechazar(sock)
                continue

            self._activas[sock].start()

    def _rechazar(self, sock: socket.socket) -> None:
        if self.mensaje_rechazo:
            try:
                sock.sendall(self.mensaje_rechazo)
            except OSError:
                pass
        try:
            sock.close()
        except OSError:
            pass

    def _atender(self, sock: socket.socket, addr: tuple) -> None:
        try:
            sock.settimeout(self.timeout_seg)
            self.manejar(sock, addr)
        except Exception:  # noqa: BLE001 -- un fallo nunca debe tumbar el servidor
            log.exception("error atendiendo a %s", addr)
        finally:
            try:
                sock.close()
            except OSError:
                pass
            with self._lock:
                self._activas.pop(sock, None)
