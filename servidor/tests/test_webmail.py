"""test_webmail.py -- la interfaz web: bandeja, lectura, adjuntos y envio.

Se habla HTTP con ``http.client`` contra un servidor real montado en un
puerto efimero.  Ademas de la felicidad, se comprueban las medidas de
seguridad acordadas: XSS escapado, anti-relay en el formulario, limite
de tamanio del POST e ids de adjunto que no pueden salirse de su carpeta.
"""

import http.client
import unittest

from tests.utilidades import arrancar_entorno
from webmail import Webmail

BORDE = "----bordeDePrueba42"


def multipart(campos, archivo=None) -> bytes:
    """Compone el cuerpo de un formulario multipart/form-data."""
    pedazos = []
    for nombre, valor in campos.items():
        pedazos.append(
            f'--{BORDE}\r\nContent-Disposition: form-data; '
            f'name="{nombre}"\r\n\r\n{valor}\r\n'.encode("utf-8")
        )
    if archivo:
        nombre_fich, datos = archivo
        pedazos.append(
            f'--{BORDE}\r\nContent-Disposition: form-data; '
            f'name="adjunto"; filename="{nombre_fich}"\r\n'
            f'Content-Type: application/pdf\r\n\r\n'.encode("utf-8")
            + datos + b"\r\n"
        )
    pedazos.append(f"--{BORDE}--\r\n".encode("utf-8"))
    return b"".join(pedazos)


class PeticionesMixin:
    """Helpers HTTP para los tests (compartidos por las dos bases)."""

    def peticion(self, metodo, ruta, cuerpo=None, ct=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.web.server_port,
                                          timeout=10)
        try:
            encabezados = {"Content-Type": ct} if ct else {}
            conn.request(metodo, ruta, body=cuerpo, headers=encabezados)
            r = conn.getresponse()
            return r.status, r.read(), dict(r.getheaders())
        finally:
            conn.close()

    def get(self, ruta):
        estado, cuerpo, cab = self.peticion("GET", ruta)
        return estado, cuerpo.decode("utf-8", "replace"), cab

    def enviar_formulario(self, campos, archivo=None):
        estado, cuerpo, cab = self.peticion(
            "POST", "/enviar", cuerpo=multipart(campos, archivo),
            ct=f"multipart/form-data; boundary={BORDE}")
        return estado, cuerpo.decode("utf-8", "replace"), cab


class BaseWeb(PeticionesMixin, unittest.TestCase):
    """Webmail + buzones de prueba levantados por clase.

    Vale para pruebas que NO entregan correo (la bandeja no cambia).
    """

    max_tamano_mb = 25   # las clases hijas pueden bajarlo

    @classmethod
    def setUpClass(cls):
        cls.entorno = arrancar_entorno(max_tamano_mb=cls.max_tamano_mb)
        cls.web = Webmail(cls.entorno.config, cls.entorno.buzones,
                          host="127.0.0.1", puerto=0)
        cls.web.arrancar()

    @classmethod
    def tearDownClass(cls):
        cls.web.shutdown()
        cls.web.server_close()
        cls.entorno.parar()


class BaseWebUnit(PeticionesMixin, unittest.TestCase):
    """Webmail + buzones NUEVOS para cada test.

    Las pruebas que entregan mensajes necesitan bandejas limpias: si no,
    el orden de ejecucion decide los resultados (error ya visto dos veces).
    """

    max_tamano_mb = 25

    def setUp(self):
        self.entorno = arrancar_entorno(max_tamano_mb=self.max_tamano_mb)
        self.addCleanup(self.entorno.parar)
        self.web = Webmail(self.entorno.config, self.entorno.buzones,
                           host="127.0.0.1", puerto=0)
        self.web.arrancar()
        self.addCleanup(self.web.server_close)
        self.addCleanup(self.web.shutdown)   # LIFO: shutdown -> close -> parar


class TestLectura(BaseWeb):

    def test_inicio_lista_los_buzones(self):
        estado, cuerpo, _ = self.get("/")
        self.assertEqual(estado, 200)
        self.assertIn("pepe@empresa.local", cuerpo)
        self.assertIn("ana@empresa.local", cuerpo)

    def test_bandeja_vacia(self):
        estado, cuerpo, _ = self.get("/?u=ana")
        self.assertEqual(estado, 200)
        self.assertIn("Bandeja de", cuerpo)
        self.assertIn("bandeja vacía", cuerpo)

    def test_bandeja_usuario_invalido_da_403(self):
        estado, _, _ = self.get("/?u=hacker")
        self.assertEqual(estado, 403)

    def test_ruta_inexistente_da_404(self):
        estado, _, _ = self.get("/no-existe")
        self.assertEqual(estado, 404)

    def test_mensaje_inexistente_da_404(self):
        estado, _, _ = self.get("/mensaje?u=ana&id=noexiste")
        self.assertEqual(estado, 404)

    def test_redactar_requiere_usuario_valido(self):
        self.assertEqual(self.get("/redactar?u=ana")[0], 200)
        self.assertEqual(self.get("/redactar?u=otro")[0], 403)


class TestEnvioWeb(BaseWebUnit):

    def test_envio_con_adjunto_endtoend(self):
        pdf = b"%PDF-1.4 contenido del confidencial " + bytes(range(256))
        asunto = "Te paso el confidencial — versión 2026"
        estado, cuerpo, _ = self.enviar_formulario(
            {"de": "pepe", "para": "ana@empresa.local",
             "asunto": asunto, "cuerpo": "Mira el adjunto, tíldes áéíóú ñ."},
            archivo=("Confidencial.pdf", pdf),
        )
        self.assertEqual(estado, 200, cuerpo)
        self.assertIn("Mensaje entregado", cuerpo)

        # Llego al buzón (UTF-8 intacto) y el adjunto se extrajo identico.
        bandeja = self.entorno.buzones.bandeja("ana")
        self.assertEqual(len(bandeja), 1)
        self.assertEqual(bandeja[0]["asunto"], asunto)
        msg_id = bandeja[0]["id"]
        carpeta = (self.entorno.config.ruta_base / "ana"
                   / "adjuntos" / msg_id)
        self.assertEqual((carpeta / "Confidencial.pdf").read_bytes(), pdf)

        # El mensaje se ve en el webmail...
        estado, vista, _ = self.get(f"/mensaje?u=ana&id={msg_id}")
        self.assertEqual(estado, 200)
        self.assertIn(asunto, vista)
        self.assertIn("Confidencial.pdf", vista)

        # ... y el adjunto se descarga (BYTES crudos, sin decodificar).
        estado, descarga, cab = self.peticion(
            "GET", f"/adjunto?u=ana&id={msg_id}&n=0")
        self.assertEqual(estado, 200)
        self.assertEqual(descarga, pdf)
        self.assertIn("attachment", cab.get("Content-Disposition", ""))

    def test_destino_fuera_del_dominio_rechazado(self):
        estado, cuerpo, _ = self.enviar_formulario(
            {"de": "pepe", "para": "victima@ejemplo.com",
             "asunto": "spam", "cuerpo": "hola"},
        )
        self.assertEqual(estado, 400, cuerpo)
        self.assertIn("no es un buzón", cuerpo)
        self.assertEqual(self.entorno.buzones.bandeja("ana"), [])

    def test_destino_local_inexistente_rechazado(self):
        estado, _, _ = self.enviar_formulario(
            {"de": "pepe", "para": "nadie@empresa.local",
             "asunto": "x", "cuerpo": "y"},
        )
        self.assertEqual(estado, 400)

    def test_emisor_falso_rechazado(self):
        estado, _, _ = self.enviar_formulario(
            {"de": "hacker", "para": "ana@empresa.local",
             "asunto": "x", "cuerpo": "y"},
        )
        self.assertEqual(estado, 403)

    def test_post_vacio_da_400(self):
        estado, _, _ = self.peticion("POST", "/enviar", cuerpo=b"",
                                     ct=f"multipart/form-data; boundary={BORDE}")
        self.assertEqual(estado, 400)

    def test_asunto_con_salto_de_linea_no_inyecta_cabeceras(self):
        estado, _, _ = self.enviar_formulario(
            {"de": "pepe", "para": "ana@empresa.local",
             "asunto": "hola\r\nBcc: victima@ejemplo.com",
             "cuerpo": "intentito"},
        )
        self.assertEqual(estado, 200)
        bandeja = self.entorno.buzones.bandeja("ana")
        data = self.entorno.buzones.leer_mensaje("ana", bandeja[0]["id"])
        self.assertNotIn(b"\r\nBcc:", data,
                         "el asunto no debe partir el mensaje en dos cabeceras")


class TestXSS(BaseWeb):
    """Todo contenido de usuario debe salir escapado en las vistas."""

    def test_script_en_asunto_y_cuerpo_escapados(self):
        marcador = "<script>alert('xss')</script>"
        estado, _, _ = self.enviar_formulario(
            {"de": "pepe", "para": "ana@empresa.local",
             "asunto": marcador, "cuerpo": marcador},
        )
        self.assertEqual(estado, 200)

        bandeja = self.entorno.buzones.bandeja("ana")
        msg_id = bandeja[0]["id"]
        _, bandeja_html, _ = self.get("/?u=ana")
        _, vista_html, _ = self.get(f"/mensaje?u=ana&id={msg_id}")

        for pagina in (bandeja_html, vista_html):
            self.assertNotIn(marcador, pagina,
                             "el script no debe aparecer sin escapar")
            self.assertIn("&lt;script&gt;", pagina)


class TestAdjuntosSeguros(BaseWeb):

    def _mensaje_con_adjunto(self, nombre_hostil, datos=b"contenido"):
        self.enviar_formulario(
            {"de": "pepe", "para": "ana@empresa.local",
             "asunto": "adj", "cuerpo": "va"},
            archivo=(nombre_hostil, datos),
        )
        bandeja = self.entorno.buzones.bandeja("ana")
        return bandeja[0]["id"]

    def test_id_de_adjunto_con_traversal_da_404(self):
        msg_id = self._mensaje_con_adjunto("ok.pdf")
        for id_malo in ["..", "../..", "noexiste", ""]:
            with self.subTest(id=id_malo):
                estado, _, _ = self.get(
                    f"/adjunto?u=ana&id={id_malo}&n=0")
                self.assertEqual(estado, 404)
        # El id legitimo sigue funcionando (los anteriores no lo rompieron).
        self.assertEqual(
            self.get(f"/adjunto?u=ana&id={msg_id}&n=0")[0], 200)

    def test_indice_fuera_de_rango_da_404(self):
        msg_id = self._mensaje_con_adjunto("ok.pdf")
        # El indice valido (0, unico adjunto) si funciona...
        self.assertEqual(
            self.get(f"/adjunto?u=ana&id={msg_id}&n=0")[0], 200)
        # ...pero cualquier otra cosa no.
        for n in ["-1", "99", "abc"]:
            with self.subTest(n=n):
                self.assertEqual(
                    self.get(f"/adjunto?u=ana&id={msg_id}&n={n}")[0], 404)


class TestLimitePost(BaseWebUnit):
    """POST por encima del limite -> 413 (igual que el DATA del SMTP)."""

    max_tamano_mb = 1

    def test_formulario_grande_recibe_413(self):
        campos = {"de": "pepe", "para": "ana@empresa.local",
                  "asunto": "gordo", "cuerpo": "A" * (1100 * 1024)}
        estado, cuerpo, _ = self.enviar_formulario(campos)
        self.assertEqual(estado, 413, cuerpo[:200])
        self.assertEqual(self.entorno.buzones.bandeja("ana"), [])


if __name__ == "__main__":
    unittest.main()
