"""test_copia_adjuntos.py -- copia FISICA de los adjuntos enviados.

El log de auditoria (``logs/envios.log``) deja constancia en texto; esta
prueba comprueba la otra mitad: que cada adjunto enviado con el servidor
se guarda tal cual en ``adjuntos_enviados/``, en una carpeta por mensaje
con su ficha ``envio.txt``, y que un fallo al escribir esa copia NUNCA
tumba el envio ni el propio log.

Todo con directorios temporales: no ensucia el repo.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from correo_api import construir_mensaje
from tests.utilidades import arrancar_entorno, codigo, mensaje


class BaseCopia(unittest.TestCase):
    """Entorno temporal por prueba con su carpeta de copias aparte."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="correo_copia_"))
        self.copia = self.tmp / "adjuntos_enviados"
        self.entorno = arrancar_entorno(copia_adjuntos=self.copia)
        self.config = self.entorno.config
        self.buzones = self.entorno.buzones

    def tearDown(self):
        self.entorno.parar()

    # ------------------------------------------------------------------ #

    def entregar_con_adjuntos(self, adjuntos=None, asunto="Con ficheros"):
        """Entrega un mensaje con adjuntos y devuelve sus bytes."""
        data = construir_mensaje(
            "pepe@empresa.local", "ana@empresa.local", asunto, "cuerpo",
            adjuntos if adjuntos is not None
            else [("Confidencial.pdf", b"%PDF-1.4 contenido confidencial")],
        )
        self.buzones.entregar(["ana"], data)
        return data

    def carpetas(self):
        """Carpetas creadas en el directorio de copias (las de mensajes)."""
        if not self.copia.is_dir():
            return []
        return sorted(p for p in self.copia.iterdir() if p.is_dir())


class TestCopiaAdjuntos(BaseCopia):

    def test_adjunto_copiado_identico_byte_a_byte(self):
        pdf = b"%PDF-1.4 contenido confidencial " + bytes(range(256))
        self.entregar_con_adjuntos([("Confidencial.pdf", pdf)])

        carpetas = self.carpetas()
        self.assertEqual(len(carpetas), 1, "una carpeta por mensaje")
        fichero = carpetas[0] / "Confidencial.pdf"
        self.assertTrue(fichero.is_file())
        self.assertEqual(fichero.read_bytes(), pdf)

    def test_varios_adjuntos_se_guardan_todos(self):
        self.entregar_con_adjuntos([
            ("Confidencial.pdf", b"pdf"),
            ("notas.txt", b"notas"),
        ])
        carpetas = self.carpetas()
        self.assertEqual(len(carpetas), 1)
        nombres = sorted(p.name for p in carpetas[0].iterdir())
        self.assertEqual(nombres, ["Confidencial.pdf", "envio.txt",
                                   "notas.txt"])

    def test_ficha_envio_txt_con_remitente_destino_y_asunto(self):
        self.entregar_con_adjuntos(asunto="Informe | confidencial")
        ficha = (self.carpetas()[0] / "envio.txt").read_text("utf-8")
        self.assertIn("de: pepe@empresa.local", ficha)
        self.assertIn("para: ana@empresa.local", ficha)
        self.assertIn("asunto: Informe | confidencial", ficha)
        self.assertIn("fecha: ", ficha)
        self.assertIn("Confidencial.pdf", ficha)

    def test_sin_adjuntos_no_se_crea_carpeta(self):
        self.buzones.entregar(["ana"], mensaje("pepe@empresa.local",
                                              "ana@empresa.local"))
        self.assertEqual(self.carpetas(), [],
                         "sin adjuntos no debe crearse nada")

    def test_adjuntos_duplicados_no_se_pisan(self):
        self.entregar_con_adjuntos([("informe.pdf", b"primero"),
                                    ("informe.pdf", b"segundo")])
        carpeta = self.carpetas()[0]
        self.assertEqual((carpeta / "informe.pdf").read_bytes(), b"primero")
        self.assertEqual((carpeta / "informe_1.pdf").read_bytes(), b"segundo")

    def test_nombre_hostil_no_escapa_de_la_carpeta(self):
        self.entregar_con_adjuntos([("../../etc/evil.sh", b"contenido")])
        carpeta = self.carpetas()[0]
        self.assertEqual((carpeta / "evil.sh").read_bytes(), b"contenido")
        # Nada escrito fuera del directorio de copias.
        fuera = [p for p in self.tmp.rglob("evil.sh")
                 if p.is_file() and carpeta not in p.parents]
        self.assertEqual(fuera, [])

    def test_dos_mensajes_con_mismo_contenido_no_comparten_carpeta(self):
        data = construir_mensaje("pepe@empresa.local", "ana@empresa.local",
                                 "Repetido", "cuerpo",
                                 [("Confidencial.pdf", b"pdf")])
        self.buzones.entregar(["ana"], data)
        self.buzones.entregar(["ana"], data)
        self.assertEqual(len(self.carpetas()), 2,
                         "cada envio tiene su propia carpeta")

    def test_ficha_y_log_cuentan_lo_mismo(self):
        # Las dos evidencias del mismo envio se pueden cruzar: la carpeta
        # (fecha + hash) y la linea del log hablan del mismo mensaje.
        self.entregar_con_adjuntos(asunto="Cruzar evidencias")
        carpeta = self.carpetas()[0]
        log = (Path(self.config.ruta_logs) / "envios.log").read_text("utf-8")
        ficha = (carpeta / "envio.txt").read_text("utf-8")

        self.assertIn("Cruzar evidencias", log)
        self.assertIn("Confidencial.pdf", log)
        self.assertIn("asunto: Cruzar evidencias", ficha)
        self.assertIn("de: pepe@empresa.local", ficha)
        # La carpeta lleva fecha + hash corto del mensaje.
        self.assertRegex(
            carpeta.name,
            r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_[0-9a-f]{8}$")


class TestCopiaPorSmtp(BaseCopia):

    def test_adjunto_enviado_por_smtp_tambien_se_copia(self):
        pdf = b"%PDF-1.4 smtp"
        data = construir_mensaje("pepe@empresa.local", "ana@empresa.local",
                                 "Por el protocolo", "cuerpo",
                                 [("Confidencial.pdf", pdf)])
        with self.entorno.conectar() as cli:
            self.assertEqual(codigo(cli.leer_respuesta()), "220")
            self.assertEqual(codigo(cli.enviar("EHLO cliente")), "250")
            self.assertEqual(
                codigo(cli.enviar("MAIL FROM:<pepe@empresa.local>")), "250")
            self.assertEqual(
                codigo(cli.enviar("RCPT TO:<ana@empresa.local>")), "250")
            self.assertEqual(codigo(cli.enviar("DATA")), "354")
            self.assertEqual(codigo(cli.enviar_data(data + b".\r\n")), "250")

        carpetas = self.carpetas()
        self.assertEqual(len(carpetas), 1)
        self.assertEqual((carpetas[0] / "Confidencial.pdf").read_bytes(), pdf)


class TestCopiaResistente(BaseCopia):

    def test_copia_desactivada_no_escribe_nada(self):
        self.config.copia_adjuntos = None
        self.entregar_con_adjuntos()
        self.assertEqual(self.carpetas(), [])
        # ...pero el log sigue apuntando el envio.
        log = Path(self.config.ruta_logs) / "envios.log"
        self.assertIn("Confidencial.pdf", log.read_text("utf-8"))

    def test_fallo_de_copia_no_tumba_el_envio_ni_el_log(self):
        # La ruta de copia apunta a un FICHERO: mkdir imposible.
        fichero = self.tmp / "no-es-un-directorio"
        fichero.write_text("no soy un directorio", "utf-8")
        self.config.copia_adjuntos = fichero

        cola_id = self.buzones.entregar(
            ["ana"], mensaje("pepe@empresa.local", "ana@empresa.local",
                             asunto="log roto"))
        # El correo se entrega igual...
        self.assertTrue(cola_id)
        self.assertTrue(
            (Path(self.config.ruta_base) / "ana" / "mensajes"
             / f"{cola_id}.eml").is_file())
        # ...y la linea de log tambien se escribe.
        log = Path(self.config.ruta_logs) / "envios.log"
        self.assertIn("asunto: log roto", log.read_text("utf-8"))


class TestConfigCopiaAdjuntos(unittest.TestCase):
    """``[log] copia_adjuntos`` del config.ini: relativa, absoluta o vacia."""

    def escribir_config(self, contenido):
        tmp = Path(tempfile.mkdtemp(prefix="correo_cfg_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        ruta = tmp / "config.ini"
        ruta.write_text(contenido, encoding="utf-8")
        return ruta

    def test_valor_relativo_se_resuelve_contra_el_directorio(self):
        from config import DIR_BASE, cargar_config
        ruta = self.escribir_config("[log]\ncopia_adjuntos = evidencia\n")
        cfg = cargar_config(ruta)
        self.assertEqual(cfg.copia_adjuntos, DIR_BASE / "evidencia")

    def test_valor_vacio_desactiva_la_copia(self):
        from config import cargar_config
        ruta = self.escribir_config("[log]\ncopia_adjuntos = \n")
        cfg = cargar_config(ruta)
        self.assertIsNone(cfg.copia_adjuntos)

    def test_sin_clave_usa_el_valor_por_defecto(self):
        from config import DIR_BASE, cargar_config
        ruta = self.escribir_config("[smtp]\npuerto = 2525\n")
        cfg = cargar_config(ruta)
        self.assertEqual(cfg.copia_adjuntos, DIR_BASE / "adjuntos_enviados")


if __name__ == "__main__":
    unittest.main()
