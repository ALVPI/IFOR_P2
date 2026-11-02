"""test_correo.py -- direcciones, mensajes con adjuntos y CLI de usuarios.

``extraer_direccion`` y ``parsear_direccion`` son la primera linea de
defensa: de ellos depende que el 554 (relay) y el 550 (buzon inexistente)
se apliquen sobre lo que el cliente realmente escribio, no sobre lo que
el servidor adivino.  Aqui se prueban tambien la construccion MIME, la
extraccion de adjuntos con nombres saneados y el CLI de buzones.
"""

import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path

from correo_api import (construir_mensaje, extraer_direccion,
                        extraer_adjuntos, nombre_seguro, parsear_direccion)
from tests.utilidades import arrancar_entorno, codigo


class TestExtraerDireccion(unittest.TestCase):

    def test_direccion_basica(self):
        self.assertEqual(extraer_direccion("FROM:<pepe@empresa.local>", "FROM:"),
                         "pepe@empresa.local")

    def test_prefijo_en_mayusculas_o_minusculas(self):
        self.assertEqual(extraer_direccion("to:<ana@empresa.local>", "TO:"),
                         "ana@empresa.local")

    def test_parametros_esmtp_se_ignoran(self):
        # Clientes reales anaden SIZE=..., BODY=8BITMIME...: no deben
        # provocar un 501.
        self.assertEqual(
            extraer_direccion("FROM:<pepe@empresa.local> SIZE=1024", "FROM:"),
            "pepe@empresa.local",
        )
        self.assertEqual(
            extraer_direccion("TO:<ana@empresa.local> NOTIFY=SUCCESS", "TO:"),
            "ana@empresa.local",
        )

    def test_remitente_nulo(self):
        # <> es legal (devoluciones); el SMTP lo distingue de "" vacio.
        self.assertEqual(extraer_direccion("FROM:<>", "FROM:"), "")

    def test_sintaxis_mala_devuelve_none(self):
        malos = [
            "pepe@empresa.local",      # sin <>
            "<pepe@empresa.local>",    # falta el prefijo FROM:/TO:
            "FROM:pepe@empresa.local", # sin angulos
            "FROM:<sin arroba>",       # direccion no valida
            "TO:",                     # sin direccion
        ]
        for texto in malos:
            with self.subTest(texto=texto):
                prefijo = "FROM:" if texto.upper().startswith("FROM") else "TO:"
                self.assertIsNone(extraer_direccion(texto, prefijo))

    def test_angulo_sin_cerrar_devuelve_none(self):
        self.assertIsNone(extraer_direccion("FROM:<a@empresa.local", "FROM:"))


class TestParsearDireccion(unittest.TestCase):

    def test_direccion_valida(self):
        self.assertEqual(parsear_direccion("pepe@empresa.local"),
                         ("pepe", "empresa.local"))

    def test_dominio_en_mayusculas_se_conserva(self):
        self.assertEqual(parsear_direccion("ana@EMPRESA.LOCAL"),
                         ("ana", "EMPRESA.LOCAL"))

    def test_invalidas_devuelven_none(self):
        for direccion in [
            "sin_arroba",          # falta @
            "a@@b.local",          # @ dobles
            "@b.local",            # usuario vacio
            "a@b@c.local",         # @ de mas
            "pe pe@b.local",       # espacio
            "../../x@b.local",     # path traversal
            "a@ b.local",          # espacio en el dominio
            "a@-malo.local",       # dominio que empieza por guion
        ]:
            with self.subTest(direccion=direccion):
                self.assertIsNone(parsear_direccion(direccion))


class TestNombreSeguro(unittest.TestCase):
    """Los nombres de adjunto nunca deben salirse de su carpeta."""

    def test_casos(self):
        casos = {
            "../../etc/passwd": "passwd",      # traversal clasico
            "..\\..\\evil.pdf": "evil.pdf",    # igual en Windows
            "co:n?ira*.txt": "co_n_ira_.txt",  # caracteres invalidos en Windows
            "..": "adjunto",                   # solo puntos -> nada guardable
            "": "adjunto",                     # sin nombre
            "  .documento  ": "documento",     # puntos/espacios sobrantes
            "Confidencial.pdf": "Confidencial.pdf",  # lo normal se queda igual
        }
        for entrada, esperado in casos.items():
            with self.subTest(entrada=entrada):
                self.assertEqual(nombre_seguro(entrada), esperado)

    def test_long_limitada(self):
        self.assertLessEqual(len(nombre_seguro("a" * 500 + ".pdf")), 100)


class TestConstruirYExtraer(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="correo_adj_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_roundtrip_con_adjunto(self):
        pdf = b"%PDF-1.4 contenido falso del Confidencial"
        data = construir_mensaje(
            "pepe@empresa.local", "ana@empresa.local",
            "Te paso el confidencial", "En_adjunto", [("Confidencial.pdf", pdf)],
        )
        guardados = extraer_adjuntos(data, self.tmp / "adj")
        self.assertEqual(guardados, ["Confidencial.pdf"])
        leido = (self.tmp / "adj" / "Confidencial.pdf").read_bytes()
        self.assertEqual(leido, pdf)

    def test_adjunto_con_nombre_hostil_no_escapa(self):
        data = construir_mensaje(
            "pepe@empresa.local", "ana@empresa.local",
            "hola", "cuerpo", [("../../evil.sh", b"#!/bin/sh")],
        )
        guardados = extraer_adjuntos(data, self.tmp / "adj")
        self.assertEqual(guardados, ["evil.sh"])
        # No debe existir NINGUN fichero fuera de la carpeta adj/.
        extraños = [p for p in self.tmp.rglob("*") if p.is_file()
                    and p.name == "evil.sh" and p.parent != self.tmp / "adj"]
        self.assertEqual(extraños, [])

    def test_mensaje_sin_multipart_no_da_adjuntos(self):
        data = construir_mensaje("a@empresa.local", "b@empresa.local",
                                 "solo texto", "nada aqui")
        self.assertEqual(extraer_adjuntos(data, self.tmp / "adj"), [])
        self.assertFalse((self.tmp / "adj").exists())

    def test_mensaje_corrupto_no_lanza_excepcion(self):
        self.assertEqual(extraer_adjuntos(b"\x00\x01\x02 basura", self.tmp / "adj"),
                         [])


class TestEntregaConAdjunto(unittest.TestCase):
    """De punta a punta: el adjunto viaja por SMTP y aterriza en el buzón."""

    def setUp(self):
        self.entorno = arrancar_entorno()
        self.addCleanup(self.entorno.parar)

    def test_pdf_confidencial_llega_completo(self):
        pdf = b"%PDF-1.4\n" + bytes(range(256)) * 32
        data = construir_mensaje(
            "pepe@empresa.local", "ana@empresa.local",
            "Confidencial.pdf adjunto", "Lo envio por correo",
            [("Confidencial.pdf", pdf)],
        )
        with self.entorno.conectar() as cli:
            cli.leer_respuesta()
            cli.enviar("HELO cliente")
            cli.enviar("MAIL FROM:<pepe@empresa.local>")
            cli.enviar("RCPT TO:<ana@empresa.local>")
            cli.enviar("DATA")
            r = cli.enviar_data(data + b".\r\n")
            self.assertEqual(codigo(r), "250")

        bandeja = self.entorno.buzones.bandeja("ana")
        self.assertEqual(len(bandeja), 1)
        self.assertEqual(bandeja[0]["asunto"], "Confidencial.pdf adjunto")

        carpeta_adj = (self.entorno.config.ruta_base / "ana" / "adjuntos"
                       / bandeja[0]["id"])
        self.assertEqual((carpeta_adj / "Confidencial.pdf").read_bytes(), pdf)


class TestCLIUsuario(unittest.TestCase):
    """`servidor.py usuario alta|baja|listar` contra un config temporal."""

    def setUp(self):
        import servidor  # se importa aqui para no arrastrar logging al module

        self.servidor_cli = servidor
        self.tmp = Path(tempfile.mkdtemp(prefix="correo_cli_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.usuarios = self.tmp / "usuarios.json"
        self.cfg = self.tmp / "config.ini"
        self.cfg.write_text(
            "[correo]\ndominio = prueba.local\n\n"
            "[rutas]\n"
            f"base = {self.tmp / 'buzones'}\n"
            f"usuarios = {self.usuarios}\n",
            encoding="utf-8",
        )

    def ejecutar(self, *args):
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            codigo_salida = self.servidor_cli.main(
                ["--config", str(self.cfg), "usuario", *args]
            )
        return codigo_salida, salida.getvalue()

    def test_alta_listar_baja(self):
        codigo_salida, salida = self.ejecutar("alta", "prueba1")
        self.assertEqual(codigo_salida, 0, salida)
        self.assertIn("prueba1@prueba.local", salida)
        self.assertIn('"prueba1"', self.usuarios.read_text("utf-8"))

        _, salida = self.ejecutar("listar")
        self.assertIn("prueba1@prueba.local", salida)

        codigo_salida, _ = self.ejecutar("baja", "prueba1")
        self.assertEqual(codigo_salida, 0)
        _, salida = self.ejecutar("listar")
        self.assertNotIn("prueba1@prueba.local", salida)

    def test_alta_duplicada_falla(self):
        self.assertEqual(self.ejecutar("alta", "prueba1")[0], 0)
        codigo_salida, salida = self.ejecutar("alta", "prueba1")
        self.assertEqual(codigo_salida, 1)
        self.assertIn("ya existe", salida)

    def test_alta_nombre_inseguro_falla(self):
        for nombre in ["../../etc", "con espacios", "pepe;rm"]:
            with self.subTest(nombre=nombre):
                codigo_salida, salida = self.ejecutar("alta", nombre)
                self.assertEqual(codigo_salida, 1)
                self.assertIn("no valido", salida)

    def test_baja_inexistente_falla(self):
        codigo_salida, salida = self.ejecutar("baja", "nadie")
        self.assertEqual(codigo_salida, 1)
        self.assertIn("no existe", salida)

    def test_alta_sin_nombre_falla(self):
        codigo_salida, salida = self.ejecutar("alta")
        self.assertEqual(codigo_salida, 2)
        self.assertIn("necesita un nombre", salida)


if __name__ == "__main__":
    unittest.main()
