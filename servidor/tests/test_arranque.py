"""test_arranque.py -- arranque combinado ``servidor.py todo``.

El camino documentado (``arrancar.bat`` -> ``servidor.py todo``) es el unico
que monta SMTP y webmail en el MISMO proceso y con LOS MISMOS buzones, y a
la vez el que menos se prueba: si su firma se rompe (p. ej. pasando los
buzones donde la funcion no los espera) el servidor ni arranca, y el fallo
solo sale al probarlo en la VM.  Aqui se arranca de verdad, con puertos
efimeros y un config temporal, y se comprueba que:

* ``cmd_todo`` no estalla (regresion del TypeError de la firma);
* el SMTP responde 220 y entrega un mensaje de punta a punta;
* el webmail responde por HTTP y VE el mensaje que acaba de entregar el
  SMTP: mismos ``Buzones``, no dos instancias distintas;
* esa entrega queda escrita en el log de auditoria.

Todo con ``daemon=True`` y topes de espera: un arranque roto debe fallar el
test, no dejar la suite colgada.
"""

import contextlib
import http.client
import io
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from buzon import Buzones
from config import cargar_config
from srv_tcp import ServidorTCP
from tests.utilidades import ClienteSMTP, codigo, mensaje

ESPERA_ARRANQUE = 5.0   # segundos maximos a que cmd_todo empiece a escuchar


class TestFirmaCrearServidor(unittest.TestCase):
    """``cmd_todo`` pasa los buzones en 3a posicion: la firma debe admitirlo.

    Antes de este arreglo la firma era ``(config, puerto, host)`` y la
    llamada de ``cmd_todo`` estallaba siempre con ``TypeError``: el
    arranque documentado no funcionaba en absoluto.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="correo_firma_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_acepta_buzones_como_tercer_argumento(self):
        import servidor

        config = cargar_config()
        config.smtp_host = "127.0.0.1"
        config.ruta_base = self.tmp / "buzones"
        config.ruta_usuarios = self.tmp / "usuarios.json"
        config.ruta_logs = self.tmp / "logs"
        buzones = Buzones(config)
        buzones.alta("pepe")

        # Sin este cambio: TypeError: got multiple values for argument...
        inst = servidor._crear_servidor_smtp(config, buzones,
                                             puerto=2525, host="127.0.0.1")
        self.assertIsInstance(inst, ServidorTCP)
        # el override de puerto/host se aplica igualmente
        self.assertEqual(config.smtp_puerto, 2525)
        self.assertEqual(config.smtp_host, "127.0.0.1")


class TestArranqueTodo(unittest.TestCase):
    """``servidor.py todo`` real: SMTP + webmail en un proceso, puerto efimero."""

    def setUp(self):
        import servidor
        import webmail

        self.servidor = servidor
        self.tmp = Path(tempfile.mkdtemp(prefix="correo_todo_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

        # Config temporal: puertos 0 (efimeros) y todo dentro del tmp, para
        # no tocar el config.ini ni los buzones del repo.
        self.cfg = self.tmp / "config.ini"
        self.cfg.write_text(
            "[smtp]\nhost = 127.0.0.1\npuerto = 0\n\n"
            "[webmail]\nhost = 127.0.0.1\npuerto = 0\n\n"
            "[correo]\ndominio = prueba.local\n\n"
            "[rutas]\n"
            f"base = {self.tmp / 'buzones'}\n"
            f"usuarios = {self.tmp / 'usuarios.json'}\n\n"
            "[log]\n"
            f"directorio = {self.tmp / 'logs'}\n",
            encoding="utf-8",
        )
        config = cargar_config(self.cfg)
        buzones = Buzones(config)
        buzones.alta("pepe")
        buzones.alta("ana")

        # cmd_todo monta el SMTP y el webmail el solo: para poder pararlos
        # despues (solo se detienen con Ctrl+C) hay que capturarlos.
        self.smtp = None
        self.web = None
        crear_orig = servidor._crear_servidor_smtp
        webmail_orig = webmail.Webmail

        def crear_capturado(*args, **kwargs):
            self.smtp = crear_orig(*args, **kwargs)
            return self.smtp

        def webmail_capturado(*args, **kwargs):
            self.web = webmail_orig(*args, **kwargs)
            return self.web

        servidor._crear_servidor_smtp = crear_capturado
        webmail.Webmail = webmail_capturado
        self.addCleanup(self._restaurar, servidor, crear_orig,
                        webmail, webmail_orig)

        # La salida de cmd_todo se captura para poder diagnosticar un fallo.
        self.salida = io.StringIO()
        self._stdout = contextlib.redirect_stdout(self.salida)
        self._stdout.__enter__()
        self.addCleanup(self._stdout.__exit__, None, None, None)

        args = SimpleNamespace(config=str(self.cfg), puerto=None, host=None)
        self.hilo = threading.Thread(target=servidor.cmd_todo, args=(args,),
                                     name="cmd-todo", daemon=True)
        self.hilo.start()
        # Se registra el ultimo: al ejecutarse el primero (LIFO) todo esta
        # parado antes de restaurar parches, la salida o borrar el tmp.
        self.addCleanup(self._detener)
        self._esperar_arranque()

    # ------------------------------------------------------------------ #
    # Limpieza
    # ------------------------------------------------------------------ #

    @staticmethod
    def _restaurar(servidor, crear_orig, webmail, webmail_orig):
        servidor._crear_servidor_smtp = crear_orig
        webmail.Webmail = webmail_orig

    @staticmethod
    def _cerrar_webmail(web):
        # shutdown() bloquearia si serve_forever nunca llego a arrancar:
        # por eso vive en un hilo daemon con tope (ver _detener).
        try:
            web.shutdown()
        except Exception:  # noqa: BLE001 -- el cierre nunca falla el test
            pass
        try:
            web.server_close()
        except OSError:
            pass

    def _detener(self):
        """Para el SMTP (con lo que cmd_todo devuelve) y luego el webmail."""
        if self.smtp is not None:
            try:
                self.smtp.parar()
            except OSError:
                pass
        if self.hilo is not None:
            self.hilo.join(timeout=ESPERA_ARRANQUE)
        if self.web is not None:
            cierre = threading.Thread(target=self._cerrar_webmail,
                                      args=(self.web,), daemon=True)
            cierre.start()
            cierre.join(timeout=ESPERA_ARRANQUE)

    def _esperar_arranque(self):
        """Espera a que el SMTP de cmd_todo acepte conexiones (o falla)."""
        fin = time.monotonic() + ESPERA_ARRANQUE
        while time.monotonic() < fin:
            if not self.hilo.is_alive():
                self.fail("cmd_todo termino sin arrancar:\n"
                          + self.salida.getvalue())
            if self.smtp is not None and self.smtp.puerto:
                try:
                    with ClienteSMTP(self.smtp.puerto):
                        return                    # ya acepta conexiones
                except OSError:
                    pass                          # aun no ha hecho el bind
            time.sleep(0.05)
        self.fail(f"el SMTP no ha llegado a escuchar en "
                  f"{ESPERA_ARRANQUE}s:\n" + self.salida.getvalue())

    # ------------------------------------------------------------------ #
    # Utilidades
    # ------------------------------------------------------------------ #

    def _entregar(self, asunto="Todo arrancado"):
        """Dialogo SMTP completo hasta el 250 final (cliente a mano)."""
        with ClienteSMTP(self.smtp.puerto) as cli:
            self.assertEqual(codigo(cli.leer_respuesta()), "220")
            self.assertEqual(codigo(cli.enviar("EHLO cliente")), "250")
            self.assertEqual(
                codigo(cli.enviar("MAIL FROM:<pepe@prueba.local>")), "250")
            self.assertEqual(
                codigo(cli.enviar("RCPT TO:<ana@prueba.local>")), "250")
            self.assertEqual(codigo(cli.enviar("DATA")), "354")
            respuesta = cli.enviar_data(
                mensaje("pepe@prueba.local", "ana@prueba.local",
                        "hola desde el arranque combinado", asunto))
            self.assertEqual(codigo(respuesta), "250")

    # ------------------------------------------------------------------ #
    # Pruebas
    # ------------------------------------------------------------------ #

    def test_todo_levanta_smtp_y_webmail(self):
        """Los dos servicios responden y el arranque informa de ambos."""
        with ClienteSMTP(self.smtp.puerto) as cli:
            self.assertEqual(codigo(cli.leer_respuesta()), "220")

        conn = http.client.HTTPConnection("127.0.0.1", self.web.server_port,
                                          timeout=ESPERA_ARRANQUE)
        try:
            conn.request("GET", "/")
            respuesta = conn.getresponse()
            cuerpo = respuesta.read().decode("utf-8", "replace")
        finally:
            conn.close()
        self.assertEqual(respuesta.status, 200)
        # la pagina de inicio lista los buzones creados
        self.assertIn("pepe@prueba.local", cuerpo)
        self.assertIn("ana@prueba.local", cuerpo)

        salida = self.salida.getvalue()
        self.assertIn("SMTP    escuchando", salida)
        self.assertIn("Webmail en", salida)

    def test_entrega_compartida_entre_smtp_y_webmail(self):
        """Lo que entrega el SMTP lo ve el webmail: un solo Buzones."""
        self._entregar(asunto="Repartido a medias")

        bandeja = self.web.buzones.bandeja("ana")
        self.assertEqual(len(bandeja), 1)
        self.assertEqual(bandeja[0]["asunto"], "Repartido a medias")

    def test_entrega_queda_en_el_log(self):
        """El envio del arranque combinado se audita en el log de la maquina."""
        self._entregar(asunto="Evidencia del escenario")

        fichero = self.tmp / "logs" / "envios.log"
        self.assertTrue(fichero.exists(),
                        "cmd_todo no ha creado el log de envios")
        contenido = fichero.read_text(encoding="utf-8")
        self.assertIn("de: pepe@prueba.local", contenido)
        self.assertIn("para: ana@prueba.local", contenido)
        self.assertIn("asunto: Evidencia del escenario", contenido)
        self.assertIn("adjuntos: ninguno", contenido)


if __name__ == "__main__":
    unittest.main()
