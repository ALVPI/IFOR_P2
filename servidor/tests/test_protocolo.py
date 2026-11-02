"""test_protocolo.py -- pruebas del protocolo SMTP (RFC 5321 resumido).

Cada clase de prueba arranca un servidor SMTP real en 127.0.0.1 con un
puerto efimero (sin privilegios, sin tocar el config.ini) y dialoga por
socket crudo.  Asi las pruebas son reproducibles en cualquier SO y en las
VMs Windows sin instalar nada mas que Python.
"""

import unittest

from tests.utilidades import arrancar_entorno, codigo, mensaje


class BaseSMTP(unittest.TestCase):
    """Servidor SMTP de apoyo para todas las pruebas de la clase."""

    @classmethod
    def setUpClass(cls):
        cls.entorno = arrancar_entorno()
        cls.config = cls.entorno.config

    @classmethod
    def tearDownClass(cls):
        cls.entorno.parar()

    def conectar(self):
        return self.entorno.conectar()

    def saludar(self, cli):
        """Recibe el 220 y manda HELO; devuelve la respuesta a HELO."""
        self.assertEqual(codigo(cli.leer_respuesta()), "220")
        return cli.enviar("HELO cliente")


class TestSesion(BaseSMTP):
    """Saludo, HELO/EHLO y comandos de sesion."""

    def test_saludo_220_al_conectar(self):
        with self.conectar() as cli:
            respuesta = cli.leer_respuesta()
            self.assertEqual(codigo(respuesta), "220")
            self.assertIn(self.config.dominio, respuesta[0])

    def test_helo_y_quit(self):
        with self.conectar() as cli:
            self.assertEqual(codigo(self.saludar(cli)), "250")
            r = cli.enviar("QUIT")
            self.assertEqual(codigo(r), "221")

    def test_ehlo_responde_multilinea_con_size(self):
        with self.conectar() as cli:
            cli.leer_respuesta()
            r = cli.enviar("EHLO cliente")
            self.assertEqual(codigo(r), "250")
            self.assertTrue(r[0].startswith("250-"), "la primera linea debe ser 250-")
            self.assertTrue(r[-1].startswith("250 "), "la ultima linea debe ser 250 ")
            self.assertIn("SIZE", r[-1])

    def test_ehlo_sin_argumento_da_501(self):
        with self.conectar() as cli:
            cli.leer_respuesta()
            self.assertEqual(codigo(cli.enviar("EHLO")), "501")

    def test_helo_sin_argumento_da_501(self):
        with self.conectar() as cli:
            cli.leer_respuesta()
            self.assertEqual(codigo(cli.enviar("HELO")), "501")

    def test_comando_desconocido_da_500(self):
        with self.conectar() as cli:
            cli.leer_respuesta()
            self.assertEqual(codigo(cli.enviar("FLY colonia")), "500")

    def test_noop_y_rset_validos_antes_del_helo(self):
        # Como en los servidores reales: NOOP/RSET/QUIT no exigen HELO.
        with self.conectar() as cli:
            cli.leer_respuesta()
            self.assertEqual(codigo(cli.enviar("NOOP")), "250")
            self.assertEqual(codigo(cli.enviar("RSET")), "250")

    def test_quit_corta_la_conexion(self):
        with self.conectar() as cli:
            self.saludar(cli)
            cli.enviar("QUIT")
            # Tras el 221 el servidor debe cerrar: la siguiente lectura da EOF.
            self.assertEqual(cli.leer_respuesta(), [])

    def test_desconexion_sin_quit_no_tumba_el_siguiente_cliente(self):
        cli = self.conectar()
        cli.leer_respuesta()
        cli.cerrar()                                  # se va sin QUIT
        with self.conectar() as cli2:                 # nueva conexion debe ir bien
            self.assertEqual(codigo(cli2.leer_respuesta()), "220")

    def test_timeout_sin_actividad_envia_421(self):
        entorno = arrancar_entorno(timeout_seg=1)
        self.addCleanup(entorno.parar)
        with entorno.conectar() as cli:
            self.assertEqual(codigo(cli.leer_respuesta()), "220")
            # No se envia nada: en ~1s el servidor debe cortar con 421.
            respuesta = cli.leer_respuesta()
            self.assertEqual(codigo(respuesta), "421")
            self.assertEqual(cli.leer_respuesta(), [])  # y cerrar


class TestTransaccion(unittest.TestCase):
    """MAIL FROM / RCPT TO / DATA y el orden de la secuencia.

    Cada prueba arranca su propio entorno: asi el numero de mensajes de
    una bandeja no depende del orden en que se ejecuten los tests.
    """

    def setUp(self):
        self.entorno = arrancar_entorno()
        self.addCleanup(self.entorno.parar)
        self.config = self.entorno.config

    def conectar(self):
        return self.entorno.conectar()

    def saludar(self, cli):
        """Recibe el 220 y manda HELO; devuelve la respuesta a HELO."""
        self.assertEqual(codigo(cli.leer_respuesta()), "220")
        return cli.enviar("HELO cliente")

    def test_flujo_completo_entrega_en_el_buzon(self):
        with self.conectar() as cli:
            self.assertEqual(codigo(self.saludar(cli)), "250")
            self.assertEqual(codigo(cli.enviar(
                "MAIL FROM:<pepe@empresa.local>")), "250")
            self.assertEqual(codigo(cli.enviar(
                "RCPT TO:<ana@empresa.local>")), "250")
            self.assertEqual(codigo(cli.enviar("DATA")), "354")
            r = cli.enviar_data(
                mensaje("pepe@empresa.local", "ana@empresa.local",
                        "hola desde la prueba")
            )
            self.assertEqual(codigo(r), "250")

        bandeja = self.entorno.buzones.bandeja("ana")
        self.assertEqual(len(bandeja), 1)
        data = self.entorno.buzones.leer_mensaje("ana", bandeja[0]["id"])
        self.assertIn(b"hola desde la prueba", data)
        # Cabecera Received con trazas del origen (evidencia para la practica)
        self.assertIn(b"Received: from", data)
        self.assertIn(b"pepe@empresa.local", data)

    def test_varios_destinos_reciben_copia(self):
        with self.conectar() as cli:
            self.saludar(cli)
            cli.enviar("MAIL FROM:<pepe@empresa.local>")
            self.assertEqual(codigo(cli.enviar(
                "RCPT TO:<ana@empresa.local>")), "250")
            self.assertEqual(codigo(cli.enviar(
                "RCPT TO:<pepe@empresa.local>")), "250")
            self.assertEqual(codigo(cli.enviar("DATA")), "354")
            self.assertEqual(codigo(cli.enviar_data(
                mensaje("pepe@empresa.local", "ana, pepe", "para los dos")
            )), "250")

        self.assertEqual(len(self.entorno.buzones.bandeja("ana")), 1)
        self.assertEqual(len(self.entorno.buzones.bandeja("pepe")), 1)

    def test_rset_cancela_la_transaccion(self):
        with self.conectar() as cli:
            self.saludar(cli)
            cli.enviar("MAIL FROM:<pepe@empresa.local>")
            cli.enviar("RCPT TO:<ana@empresa.local>")
            self.assertEqual(codigo(cli.enviar("RSET")), "250")
            # Tras RSET olvidamos RCPT: DATA ya no es legal.
            self.assertEqual(codigo(cli.enviar("DATA")), "503")

    def test_un_segundo_mensaje_sin_repetir_helo(self):
        with self.conectar() as cli:
            self.saludar(cli)
            for _ in range(2):
                cli.enviar("MAIL FROM:<pepe@empresa.local>")
                cli.enviar("RCPT TO:<ana@empresa.local>")
                cli.enviar("DATA")
                self.assertEqual(codigo(cli.enviar_data(
                    mensaje("pepe@empresa.local", "ana@empresa.local")
                )), "250")
        self.assertEqual(len(self.entorno.buzones.bandeja("ana")), 2)

    # -- errores de secuencia ------------------------------------------- #

    def test_mail_sin_helo_da_503(self):
        with self.conectar() as cli:
            cli.leer_respuesta()
            self.assertEqual(codigo(cli.enviar(
                "MAIL FROM:<pepe@empresa.local>")), "503")

    def test_mail_repetido_da_503(self):
        with self.conectar() as cli:
            self.saludar(cli)
            cli.enviar("MAIL FROM:<pepe@empresa.local>")
            self.assertEqual(codigo(cli.enviar(
                "MAIL FROM:<pepe@empresa.local>")), "503")

    def test_rcpt_sin_mail_da_503(self):
        with self.conectar() as cli:
            self.saludar(cli)
            self.assertEqual(codigo(cli.enviar(
                "RCPT TO:<ana@empresa.local>")), "503")

    def test_data_sin_rcpt_da_503(self):
        with self.conectar() as cli:
            self.saludar(cli)
            cli.enviar("MAIL FROM:<pepe@empresa.local>")
            self.assertEqual(codigo(cli.enviar("DATA")), "503")

    # -- errores de sintaxis -------------------------------------------- #

    def test_mail_sin_angulos_da_501(self):
        with self.conectar() as cli:
            self.saludar(cli)
            self.assertEqual(codigo(cli.enviar(
                "MAIL FROM:pepe@empresa.local")), "501")

    def test_mail_sin_from_da_501(self):
        with self.conectar() as cli:
            self.saludar(cli)
            self.assertEqual(codigo(cli.enviar(
                "MAIL TO:<pepe@empresa.local>")), "501")

    def test_rcpt_sin_to_da_501(self):
        with self.conectar() as cli:
            self.saludar(cli)
            cli.enviar("MAIL FROM:<pepe@empresa.local>")
            self.assertEqual(codigo(cli.enviar(
                "RCPT FROM:<ana@empresa.local>")), "501")

    def test_data_con_argumentos_da_501(self):
        with self.conectar() as cli:
            self.saludar(cli)
            cli.enviar("MAIL FROM:<pepe@empresa.local>")
            cli.enviar("RCPT TO:<ana@empresa.local>")
            self.assertEqual(codigo(cli.enviar("DATA por favor")), "501")

    # -- VRFY ------------------------------------------------------------- #

    def test_vrfy_usuarios(self):
        with self.conectar() as cli:
            cli.leer_respuesta()
            self.assertEqual(codigo(cli.enviar(
                "VRFY <pepe@empresa.local>")), "250")   # existe
            self.assertEqual(codigo(cli.enviar(
                "VRFY <nadie@empresa.local>")), "550")  # no existe
            self.assertEqual(codigo(cli.enviar("VRFY coso")), "501")  # sintaxis


class TestRobustez(unittest.TestCase):
    """Esquinas raras: lineas gigantes y dot-stuffing en DATA."""

    def setUp(self):
        self.entorno = arrancar_entorno()
        self.addCleanup(self.entorno.parar)

    def test_comando_gigante_responde_500_y_la_sesion_sigue_viva(self):
        with self.entorno.conectar() as cli:
            cli.leer_respuesta()
            r = cli.enviar("X" * 5000)          # jamas termina en logica de cliente
            self.assertEqual(codigo(r), "500")
            self.assertIn("demasiado larga", r[0])
            # La sesion quedo alineada: el siguiente comando se entiende.
            self.assertEqual(codigo(cli.enviar("HELO cliente")), "250")

    def test_linea_larga_en_data_devuelve_500_y_no_entrega(self):
        data = (
            b"From: pepe@empresa.local\r\nTo: ana@empresa.local\r\n"
            b"Subject: largo\r\n\r\n"
            + b"X" * 3000 + b"\r\n"
            + b"cuerpo tras la linea larga\r\n"
            + b".\r\n"
        )
        with self.entorno.conectar() as cli:
            cli.leer_respuesta()
            cli.enviar("HELO cliente")
            cli.enviar("MAIL FROM:<pepe@empresa.local>")
            cli.enviar("RCPT TO:<ana@empresa.local>")
            cli.enviar("DATA")
            r = cli.enviar_data(data)
            self.assertEqual(codigo(r), "500")
            self.assertEqual(codigo(cli.enviar("NOOP")), "250")

        self.assertEqual(self.entorno.buzones.bandeja("ana"), [],
                         "un mensaje con linea gigante no debe guardarse")

    def test_dot_stuffing_se_invierte_al_guardar(self):
        # En DATA, un punto inicial de linea SE DUPLICA en el envio; el
        # servidor debe quitar UNO al guardar (RFC 5321, seccion 4.5.2).
        data = (
            b"From: pepe@empresa.local\r\nTo: ana@empresa.local\r\n"
            b"Subject: puntos\r\n\r\n"
            b"antes\r\n"
            b"...\r\n"        # el cliente quiso decir: ".."
            b"..\r\n"         # el cliente quiso decir: "."
            b"..stuff\r\n"    # el cliente quiso decir: ".stuff"
            b"despues\r\n"
            b".\r\n"          # fin real del mensaje
        )
        with self.entorno.conectar() as cli:
            cli.leer_respuesta()
            cli.enviar("HELO cliente")
            cli.enviar("MAIL FROM:<pepe@empresa.local>")
            cli.enviar("RCPT TO:<ana@empresa.local>")
            cli.enviar("DATA")
            self.assertEqual(codigo(cli.enviar_data(data)), "250")

        bandeja = self.entorno.buzones.bandeja("ana")
        self.assertEqual(len(bandeja), 1, "el '.' final no debe cortar antes de tiempo")
        guardado = self.entorno.buzones.leer_mensaje("ana", bandeja[0]["id"])
        self.assertIn(b"..\r\n", guardado)      # lo que habia tras el relleno
        self.assertIn(b".stuff\r\n", guardado)
        self.assertNotIn(b"...\r\n", guardado)  # la forma "empaquetada" ya no existe

        # Y la sesion sigue sirviendo mensajes tras el dot-stuffing.
        with self.entorno.conectar() as cli2:
            cli2.leer_respuesta()
            cli2.enviar("HELO cliente")
            cli2.enviar("MAIL FROM:<pepe@empresa.local>")
            cli2.enviar("RCPT TO:<ana@empresa.local>")
            cli2.enviar("DATA")
            self.assertEqual(codigo(cli2.enviar_data(
                mensaje("pepe@empresa.local", "ana@empresa.local")
            )), "250")
        self.assertEqual(len(self.entorno.buzones.bandeja("ana")), 2)


if __name__ == "__main__":
    unittest.main()
