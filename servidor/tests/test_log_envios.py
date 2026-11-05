"""test_log_envios.py -- auditoria de envios (logs/envios.log).

El punto de enganche unico es ``buzon.entregar``: las pruebas comprueban
que SMTP y entrega directa dejan UNA linea por mensaje en el fichero de
log, con remitente, destinos en orden, asunto y nombres de adjuntos.
Cada prueba usa un directorio temporal, asi que no ensucia el repo.
"""

import unittest
from pathlib import Path

from correo_api import construir_mensaje
from tests.utilidades import arrancar_entorno, codigo, mensaje


class BaseLog(unittest.TestCase):
    """Entorno SMTP temporal por PRUEBA: cada test tiene su log aislado."""

    def setUp(self):
        self.entorno = arrancar_entorno()
        self.config = self.entorno.config
        self.buzones = self.entorno.buzones

    def tearDown(self):
        self.entorno.parar()

    # ------------------------------------------------------------------ #

    def leer_log(self):
        """Devuelve la ruta del log y sus lineas (lista de str sin \\n)."""
        fichero = Path(self.config.ruta_logs) / "envios.log"
        lineas = fichero.read_text("utf-8").splitlines() if fichero.exists() else []
        return fichero, lineas


class TestLogEntregas(BaseLog):

    def test_directorio_se_crea_si_no_existia(self):
        self.buzones.entregar(["ana"], mensaje("pepe@empresa.local",
                                              "ana@empresa.local"))
        self.assertTrue(Path(self.config.ruta_logs).is_dir())

    def test_linea_con_remitente_destinos_y_asunto(self):
        self.buzones.entregar(
            ["ana", "pepe"],
            mensaje("pepe@empresa.local", "ana@empresa.local, "
                    "pepe@empresa.local", asunto="Examen final"),
        )
        _, lineas = self.leer_log()
        self.assertTrue(lineas, "debe existir al menos una linea de log")
        ultima = lineas[-1]
        self.assertIn("de: pepe@empresa.local", ultima)
        # Orden de aceptacion: ana ANTES de pepe.
        self.assertIn("para: ana@empresa.local, pepe@empresa.local", ultima)
        self.assertIn("asunto: Examen final", ultima)
        self.assertIn("adjuntos: ninguno", ultima)

    def test_mensaje_con_adjuntos_registra_nombres_y_tamanios(self):
        adjuntos = [("Confidencial.pdf", b"x" * (123 * 1024)),
                    ("notas.txt", b"y" * 4096)]
        data = construir_mensaje("pepe@empresa.local", "ana@empresa.local",
                                 "Con ficheros", "cuerpo", adjuntos)
        self.buzones.entregar(["ana"], data)
        _, lineas = self.leer_log()
        ultima = lineas[-1]
        self.assertIn("Confidencial.pdf (123 KB)", ultima)
        self.assertIn("notas.txt (4 KB)", ultima)
        self.assertNotIn("ninguno", ultima)

    def test_nombres_de_adjunto_son_los_saneados(self):
        # Lo que va al log es lo que queda en buzones/adjuntos/ (auditable).
        data = construir_mensaje("pepe@empresa.local", "ana@empresa.local",
                                 "ruta rara", "cuerpo",
                                 [("../../etc/passwd", b"contenido")])
        self.buzones.entregar(["ana"], data)
        _, lineas = self.leer_log()
        self.assertIn("passwd", lineas[-1])
        self.assertNotIn("..", lineas[-1])

    def test_separador_no_rompe_la_linea(self):
        # Un asunto que contiene el separador ' | ' debe quedar escapado
        # con la barra partida (U+00A6): UNA sola linea en el log.
        self.buzones.entregar(
            ["ana"],
            mensaje("pepe@empresa.local", "ana@empresa.local",
                    asunto="resumen | avance | 2026"),
        )
        _, lineas = self.leer_log()
        self.assertEqual(len(lineas), 1)
        self.assertIn("asunto: resumen \u00a6 avance \u00a6 2026", lineas[-1])

    def test_anexo_da_varias_lineas_sin_reescribir(self):
        data = mensaje("pepe@empresa.local", "ana@empresa.local",
                       asunto="log repetido")
        self.buzones.entregar(["ana"], data)
        self.buzones.entregar(["ana", "pepe"], data)
        _, lineas = self.leer_log()
        self.assertEqual(len(lineas), 2)
        self.assertIn("para: ana@empresa.local, pepe@empresa.local", lineas[-1])

    def test_log_via_smtp_real(self):
        # Camino completo: dialogo SMTP real -> entregar -> fichero de log.
        with self.entorno.conectar() as cli:
            self.assertEqual(codigo(cli.leer_respuesta()), "220")
            self.assertEqual(codigo(cli.enviar("HELO cliente")), "250")
            self.assertEqual(
                codigo(cli.enviar("MAIL FROM:<pepe@empresa.local>")), "250")
            self.assertEqual(
                codigo(cli.enviar("RCPT TO:<ana@empresa.local>")), "250")
            self.assertEqual(codigo(cli.enviar("DATA")), "354")
            data = (b"Message-ID: <log1@cliente>\r\n"
                    b"From: pepe@empresa.local\r\n"
                    b"To: ana@empresa.local\r\n"
                    b"Subject: Auditoria SMTP\r\n\r\n"
                    b"cuerpo de prueba\r\n.\r\n")
            self.assertEqual(codigo(cli.enviar_data(data)), "250")
            cli.enviar("QUIT")

        _, lineas = self.leer_log()
        self.assertTrue(lineas, "el envio por SMTP debe quedar registrado")
        self.assertIn("de: pepe@empresa.local", lineas[-1])
        self.assertIn("asunto: Auditoria SMTP", lineas[-1])

    def test_fallo_del_log_no_tumba_la_entrega(self):
        # ruta_logs apunta a un FICHERO (mkdir imposible): la entrega
        # debe seguir siendo 250 / devolver id y escribir el .eml.
        self.buzones.entregar(["ana"], mensaje("pepe@empresa.local",
                                              "ana@empresa.local"))
        ruta_ficha = Path(self.config.ruta_base) / "no-es-un-directorio"
        ruta_ficha.write_text("no soy un directorio", "utf-8")
        ruta_logs_previa = self.config.ruta_logs
        self.config.ruta_logs = ruta_ficha
        try:
            cola_id = self.buzones.entregar(
                ["ana"], mensaje("pepe@empresa.local", "ana@empresa.local",
                                 asunto="log roto"))
            self.assertTrue(cola_id)
            self.assertTrue(
                (Path(self.config.ruta_base) / "ana" / "mensajes"
                 / f"{cola_id}.eml").is_file())
        finally:
            self.config.ruta_logs = ruta_logs_previa
            ruta_ficha.unlink()
