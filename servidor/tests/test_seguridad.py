"""test_seguridad.py -- anti open-relay, validacion de destinos y limites.

Estas son las pruebas que demuestran los requisitos de seguridad pedidos:

* no open relay (destino fuera del dominio local -> 554),
* destinatarios validados contra los buzones (-> 550),
* limite de conexiones simultaneas (-> 421),
* limite de tamano en DATA (-> 552),
* robustez ante timeouts y desconexiones a mitad de mensaje.
"""

import time
import unittest

from tests.utilidades import ClienteSMTP, arrancar_entorno, codigo, mensaje


class TestAntiOpenRelay(unittest.TestCase):
    """Nadie puede usar nuestro servidor para enviar a dominios ajenos."""

    @classmethod
    def setUpClass(cls):
        cls.entorno = arrancar_entorno()

    @classmethod
    def tearDownClass(cls):
        cls.entorno.parar()

    def _hasta_rcpt(self, cli, destino):
        """Saluda, abre transaccion y envia RCPT TO:<destino>."""
        cli.leer_respuesta()
        cli.enviar("HELO cliente")
        cli.enviar("MAIL FROM:<intruso@ejemplo.com>")
        return cli.enviar(f"RCPT TO:<{destino}>")

    def test_dominio_externo_recibe_554(self):
        with self.entorno.conectar() as cli:
            r = self._hasta_rcpt(cli, "victim@otro.dominio.com")
            self.assertEqual(codigo(r), "554")
            self.assertIn("Relay denegado", r[0])

    def test_dominio_local_desconocido_recibe_550(self):
        with self.entorno.conectar() as cli:
            r = self._hasta_rcpt(cli, "nadie@empresa.local")
            self.assertEqual(codigo(r), "550")

    def test_dominio_local_en_mayusculas_si_se_acepta(self):
        # La comparacion de dominios no distingue mayusculas (RFC 5321).
        with self.entorno.conectar() as cli:
            r = self._hasta_rcpt(cli, "ana@EMPRESA.LOCAL")
            self.assertEqual(codigo(r), "250")

    def test_tras_554_se_puede_enviar_a_un_destino_local(self):
        # El relay denegado NO corta la sesion: corrige el destino y sigue.
        with self.entorno.conectar() as cli:
            self.assertEqual(codigo(
                self._hasta_rcpt(cli, "fuera@ejemplo.org")), "554")
            r = cli.enviar("RCPT TO:<ana@empresa.local>")
            self.assertEqual(codigo(r), "250")

    def test_direccion_maliciosa_recibe_501(self):
        casos = [
            "../../etc@empresa.local",   # intento de traversal en el usuario
            "pe pe@empresa.local",       # espacio en la direccion
            "a@@empresa.local",          # arrobas dobles
            "@empresa.local",            # usuario vacio
        ]
        for caso in casos:
            with self.subTest(destino=caso):
                with self.entorno.conectar() as cli:
                    r = self._hasta_rcpt(cli, caso)
                    self.assertEqual(codigo(r), "501")


class TestLimites(unittest.TestCase):
    """Cuantos mensajes/conexiones aguanta y que pasa al pasarselos."""

    def test_limite_de_conexiones_envia_421(self):
        entorno = arrancar_entorno(max_conexiones=2)
        self.addCleanup(entorno.parar)
        ocupadas = [entorno.conectar(), entorno.conectar()]
        self.addCleanup(lambda: [c.cerrar() for c in ocupadas])
        for cli in ocupadas:
            self.assertEqual(codigo(cli.leer_respuesta()), "220")

        tercera = entorno.conectar()
        self.addCleanup(tercera.cerrar)
        r = tercera.leer_respuesta()
        self.assertEqual(codigo(r), "421")
        # Ademas corta: la siguiente lectura da EOF.
        self.assertEqual(tercera.leer_respuesta(), [])

        # Al liberarse una, vuelve a admitir (el hueco se recupera).
        ocupadas[0].cerrar()
        tiempo_limite = time.monotonic() + 3
        while time.monotonic() < tiempo_limite:
            nueva = entorno.conectar()
            r = nueva.leer_respuesta()
            if codigo(r) == "220":
                nueva.cerrar()
                break
            nueva.cerrar()
            time.sleep(0.1)
        else:
            self.fail("el servidor no recupero el hueco tras cerrar una conexion")

    def test_mensaje_grande_recibe_552_y_no_se_guarda(self):
        entorno = arrancar_entorno(max_tamano_mb=1)
        self.addCleanup(entorno.parar)
        relleno = (b"A" * 200 + b"\r\n") * 6000   # ~1,2 MB
        data = (
            b"From: pepe@empresa.local\r\nTo: ana@empresa.local\r\n"
            b"Subject: grande\r\n\r\n" + relleno + b".\r\n"
        )
        with entorno.conectar() as cli:
            cli.leer_respuesta()
            cli.enviar("HELO cliente")
            cli.enviar("MAIL FROM:<pepe@empresa.local>")
            cli.enviar("RCPT TO:<ana@empresa.local>")
            cli.enviar("DATA")
            r = cli.enviar_data(data)
            self.assertEqual(codigo(r), "552")
            # La sesion sigue viva: se puede mandar otro mensaje pequeno.
            self.assertEqual(codigo(cli.enviar("NOOP")), "250")

        self.assertEqual(entorno.buzones.bandeja("ana"), [],
                         "el mensaje grande no debe guardarse")

    def test_timeout_dentro_de_data_envia_421(self):
        entorno = arrancar_entorno(timeout_seg=1)
        self.addCleanup(entorno.parar)
        with entorno.conectar() as cli:
            cli.leer_respuesta()
            cli.enviar("HELO cliente")
            cli.enviar("MAIL FROM:<pepe@empresa.local>")
            cli.enviar("RCPT TO:<ana@empresa.local>")
            self.assertEqual(codigo(cli.enviar("DATA")), "354")
            # Cuerpo a medias y nada mas: el servidor debe cortar por timeout.
            cli.sock.sendall(b"Subject: a medias\r\n\r\nsin terminar")
            r = cli.leer_respuesta()
            self.assertEqual(codigo(r), "421")
            self.assertEqual(cli.leer_respuesta(), [])

    def test_desconexion_a_mitad_de_data_no_tumba_el_servidor(self):
        entorno = arrancar_entorno()
        self.addCleanup(entorno.parar)
        cli = entorno.conectar()
        cli.leer_respuesta()
        cli.enviar("HELO cliente")
        cli.enviar("MAIL FROM:<pepe@empresa.local>")
        cli.enviar("RCPT TO:<ana@empresa.local>")
        cli.enviar("DATA")
        cli.sock.sendall(b"Subject: incompleto\r\n\r\nparcial")
        cli.cerrar()                                  # se desconecta sin el punto

        # El siguiente cliente no debe notar nada raro.
        with entorno.conectar() as cli2:
            self.assertEqual(codigo(cli2.leer_respuesta()), "220")

        self.assertEqual(entorno.buzones.bandeja("ana"), [],
                         "un DATA incompleto no debe producir mensaje")


if __name__ == "__main__":
    unittest.main()
