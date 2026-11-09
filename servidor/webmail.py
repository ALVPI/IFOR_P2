"""webmail.py -- interfaz web minimalista sobre los buzones (solo stdlib).

Funciones (lo justo para el Escenario 1; sin IMAP, sin TLS, sin base de
datos):

* ``/``               elige buzón; con ``?u=pepe`` muestra la bandeja
* ``/mensaje?u&id``   ver un mensaje + enlaces a sus adjuntos
* ``/adjunto?u&id&n`` descargar el enesimo adjunto extraido del mensaje
* ``/redactar?u``     formulario de envio con campo de adjunto
* ``/enviar`` (POST)  entrega el mensaje por la MISMA ruta interna que
                      el SMTP (buzon.entregar), validando destinos igual

Decisiones de seguridad (acordes a lo pedido para la practica):

* TODO lo que viene del usuario se escapa con ``html.escape`` antes de
  meterlo en una plantilla (contra XSS en el laboratorio);
* el emisor debe ser un buzón existente y el destinatario solo puede ser
  de ``config.dominio`` (mismo anti-relay que el SMTP: un formulario
  tampoco puede usar el servidor para enviar fuera);
* el POST esta limitado en tamanio (``413``) igual que el DATA;
* los adjuntos se sirven SOLO desde la carpeta extraida (indice numerado:
  jamas se compone una ruta con datos del cliente);
* los asuntos pasan por ``_sin_saltos`` (evita inyectar cabeceras
  ``Subject`` con CR/LF desde el formulario).

ADVERTENCIA de laboratorio: NO hay autenticacion (decision acordada para
la practica).  Cualquiera en la red del laboratorio podra leer las
bandejas: no exponer el puerto web fuera de la red NAT de VirtualBox.
"""

import html
import logging
import threading
from email import policy
from email.parser import BytesParser
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from string import Template
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote, urlparse

from buzon import RE_MSG_ID, Buzones
from config import Config
from correo_api import construir_mensaje, parsear_direccion

log = logging.getLogger("correo.webmail")

DIR_PLANTILLAS = Path(__file__).resolve().parent / "plantillas"

# Margen sobre max_tamano_bytes para las cabeceras/contorno del multipart.
LIMITE_POST_EXTRA = 64 * 1024


def _esc(texto) -> str:
    """Escapa cualquier valor de usuario antes de meterlo en HTML."""
    return html.escape(str(texto), quote=True)


def _sin_saltos(texto: str) -> str:
    """Sin CR/LF: evita inyeccion de cabeceras al construir el mensaje."""
    return texto.replace("\r", " ").replace("\n", " ").strip()


class Webmail(ThreadingHTTPServer):
    """Servidor HTTP multihilo con acceso a config y buzones."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, config: Config, buzones: Buzones,
                 host: Optional[str] = None, puerto: Optional[int] = None):
        super().__init__(
            (config.webmail_host if host is None else host,
             config.webmail_puerto if puerto is None else puerto),
            ManejadorWeb,
        )
        self.config = config
        self.buzones = buzones
        self.plantillas: Dict[str, Template] = {
            fich.name: Template(fich.read_text(encoding="utf-8"))
            for fich in sorted(DIR_PLANTILLAS.glob("*.html"))
        }

    def arrancar(self) -> threading.Thread:
        """Arranca el bucle HTTP en un hilo daemon y lo devuelve."""
        hilo = threading.Thread(target=self.serve_forever,
                                name="webmail", daemon=True)
        hilo.start()
        return hilo


class ManejadorWeb(BaseHTTPRequestHandler):
    """Enrutado GET/POST del webmail.  ``self.server`` es un :class:`Webmail`."""

    # ------------------------------------------------------------------ #
    # Respuestas
    # ------------------------------------------------------------------ #

    def log_message(self, formato, *args):
        log.debug("%s - %s", self.address_string(), formato % args)

    def _responder(self, estado: int, cuerpo: bytes,
                   tipo: str = "text/html; charset=utf-8",
                   cabeceras: Optional[Dict[str, str]] = None) -> None:
        try:
            self.send_response(estado)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(cuerpo)))
            for nombre, valor in (cabeceras or {}).items():
                self.send_header(nombre, valor)
            self.end_headers()
            self.wfile.write(cuerpo)
        except (BrokenPipeError, ConnectionResetError):
            pass  # el navegador se ha ido: nada que hacer

    def _pagina(self, titulo: str, cuerpo_html: str, estado: int = 200) -> None:
        """Responde una pagina minima (para inicio, errores y avisos)."""
        documento = (
            "<!DOCTYPE html><html lang='es'><head><meta charset='utf-8'>"
            f"<title>{_esc(titulo)}</title>"
            "<style>body{font-family:system-ui,sans-serif;max-width:52rem;"
            "margin:2rem auto;padding:0 1rem}a{color:#0645ad}</style>"
            f"</head><body><h1>{_esc(titulo)}</h1>{cuerpo_html}</body></html>"
        )
        self._responder(estado, documento.encode("utf-8"))

    def _usuario(self, consulta: Dict[str, str]) -> Optional[str]:
        """Devuelve el usuario ``?u=...`` si es un buzón real, si no None."""
        usuario = consulta.get("u", "")
        return usuario if self.server.buzones.existe(usuario) else None

    # ------------------------------------------------------------------ #
    # GET
    # ------------------------------------------------------------------ #

    def do_GET(self):
        try:
            self._get()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:  # noqa: BLE001 -- un fallo no debe tumbar el hilo HTTP
            log.exception("error en GET %s", self.path)
            self._pagina("Error interno", "<p>Vuelve a intentarlo.</p>", 500)

    def _get(self):
        url = urlparse(self.path)
        consulta = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == "/":
            self._vista_bandeja(consulta)
        elif url.path == "/mensaje":
            self._vista_mensaje(consulta)
        elif url.path == "/adjunto":
            self._vista_adjunto(consulta)
        elif url.path == "/redactar":
            self._vista_redactar(consulta)
        elif url.path == "/fuente":
            self._vista_fuente(consulta)
        else:
            self._pagina("No encontrado", "<p>Esa ruta no existe.</p>", 404)

    def _vista_inicio(self) -> None:
        """Pantalla de eleccion de buzón (no hay login: solo elegir)."""
        buzones = self.server.buzones.listar()
        if buzones:
            items = "".join(
                f"<li><a href='/?u={_esc(u)}'>{_esc(u)}@"
                f"{_esc(self.server.config.dominio)}</a></li>"
                for u in buzones
            )
            cuerpo = f"<p>Elige tu buzón:</p><ul>{items}</ul>"
        else:
            cuerpo = ("<p>No hay buzones creados. Crea uno primero con "
                      "<code>py -3 servidor.py usuario alta &lt;nombre&gt;</code>"
                      "</p>")
        self._pagina("Correo IFOR", cuerpo)

    def _vista_bandeja(self, consulta: Dict[str, str]) -> None:
        if "u" not in consulta:
            self._vista_inicio()
            return
        usuario = self._usuario(consulta)
        if usuario is None:
            self._pagina("No autorizado",
                         "<p>Buzón no valido.</p>", 403)
            return

        mensajes = self.server.buzones.bandeja(usuario)
        if mensajes:
            filas = "".join(
                "<tr><td>{asunto}</td><td>{de}</td><td>{fecha}</td>"
                "<td><a href='/mensaje?u={usuario}&id={id}'>abrir</a>"
                "</td></tr>".format(
                    asunto=_esc(m["asunto"]), de=_esc(m["de"]),
                    fecha=_esc(m["fecha"]),
                    usuario=_esc(usuario), id=_esc(m["id"]),
                )
                for m in mensajes
            )
            tabla = ("<table><tr><th>Asunto</th><th>De</th><th>Fecha</th>"
                     f"<th></th></tr>{filas}</table>")
        else:
            tabla = "<p>(bandeja vacía)</p>"

        plantilla = self.server.plantillas["index.html"]
        self._responder(200, plantilla.substitute(
            usuario=_esc(usuario),
            dominio=_esc(self.server.config.dominio),
            tabla=tabla,
        ).encode("utf-8"))

    def _vista_mensaje(self, consulta: Dict[str, str]) -> None:
        usuario = self._usuario(consulta)
        if usuario is None:
            self._pagina("No autorizado", "<p>Buzón no valido.</p>", 403)
            return
        msg_id = consulta.get("id", "")
        data = self.server.buzones.leer_mensaje(usuario, msg_id)
        if data is None:
            self._pagina("Mensaje no encontrado",
                         "<p>Ese mensaje no existe en tu buzón.</p>", 404)
            return

        msg = BytesParser(policy=policy.default).parsebytes(data)
        asunto = str(msg.get("Subject", "(sin asunto)"))
        cuerpo = ""
        try:
            principal = msg.get_body(preferencelist=("plain", "html"))
            if principal is not None:
                texto = principal.get_content()
                cuerpo = texto if isinstance(texto, str) else str(texto)
        except Exception:  # noqa: BLE001 -- mensajes raros: cuerpo vacio
            cuerpo = ""

        # Adjuntos extraidos a disco (una carpeta por mensaje).
        carpeta_adj = (self.server.config.ruta_base / usuario
                       / "adjuntos" / msg_id)
        archivos = (sorted(p for p in carpeta_adj.iterdir() if p.is_file())
                    if carpeta_adj.is_dir() else [])
        if archivos:
            enlaces = "".join(
                f"<li><a href='/adjunto?u={_esc(usuario)}&id={_esc(msg_id)}"
                f"&n={i}'>{_esc(f.name)}</a></li>"
                for i, f in enumerate(archivos)
            )
            html_adj = f"<ul>{enlaces}</ul>"
        else:
            html_adj = "<p>(sin adjuntos)</p>"

        plantilla = self.server.plantillas["mensaje.html"]
        self._responder(200, plantilla.substitute(
            usuario=_esc(usuario),
            msg_id=_esc(msg_id),
            asunto=_esc(asunto),
            de=_esc(str(msg.get("From", ""))),
            para=_esc(str(msg.get("To", ""))),
            fecha=_esc(str(msg.get("Date", ""))),
            adjuntos=html_adj,
            cuerpo=_esc(cuerpo),
        ).encode("utf-8"))

    def _vista_fuente(self, consulta: Dict[str, str]) -> None:
        """Muestra el .eml completo (cabeceras + cuerpo) como texto plano.

        Util para la auditoria forense: permite inspeccionar las cabeceras
        Received, Message-ID, MIME, etc. sin parsear el mensaje.
        """
        usuario = self._usuario(consulta)
        if usuario is None:
            self._pagina("No autorizado", "<p>Buzón no valido.</p>", 403)
            return
        msg_id = consulta.get("id", "")
        data = self.server.buzones.leer_mensaje(usuario, msg_id)
        if data is None:
            self._pagina("Mensaje no encontrado",
                         "<p>Ese mensaje no existe en tu buzón.</p>", 404)
            return
        self._responder(
            200, data,
            tipo="text/plain; charset=utf-8",
            cabeceras={
                "Content-Disposition":
                    f'inline; filename="{msg_id}.eml"',
            },
        )

    def _vista_adjunto(self, consulta: Dict[str, str]) -> None:
        usuario = self._usuario(consulta)
        if usuario is None:
            self._pagina("No autorizado", "<p>Buzón no valido.</p>", 403)
            return
        msg_id = consulta.get("id", "")
        try:
            indice = int(consulta.get("n", ""))
        except ValueError:
            indice = -1

        # Antes de tocar el disco: el id debe ser de los que genera el
        # servidor (letra/numero/guion).  Tras validarlo, la ruta solo
        # puede caer dentro de adjuntos/<id>/.
        if not RE_MSG_ID.match(msg_id):
            indice = -1
        carpeta_adj = (self.server.config.ruta_base / usuario
                       / "adjuntos" / msg_id)
        archivos = (sorted(p for p in carpeta_adj.iterdir() if p.is_file())
                    if carpeta_adj.is_dir() else [])
        if not 0 <= indice < len(archivos):
            self._pagina("Adjunto no encontrado",
                         "<p>No existe ese adjunto.</p>", 404)
            return

        fichero = archivos[indice]
        self._responder(
            200, fichero.read_bytes(),
            tipo="application/octet-stream",
            cabeceras={
                "Content-Disposition":
                    f"attachment; filename*=UTF-8''{quote(fichero.name)}"
            },
        )

    def _vista_redactar(self, consulta: Dict[str, str]) -> None:
        usuario = self._usuario(consulta)
        if usuario is None:
            self._pagina("No autorizado", "<p>Buzón no valido.</p>", 403)
            return
        plantilla = self.server.plantillas["redactar.html"]
        self._responder(200, plantilla.substitute(
            usuario=_esc(usuario),
            dominio=_esc(self.server.config.dominio),
        ).encode("utf-8"))

    # ------------------------------------------------------------------ #
    # POST /enviar
    # ------------------------------------------------------------------ #

    def do_POST(self):
        try:
            self._post()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:  # noqa: BLE001
            log.exception("error en POST %s", self.path)
            self._pagina("Error interno", "<p>Vuelve a intentarlo.</p>", 500)

    def _post(self):
        url = urlparse(self.path)
        if url.path == "/enviar":
            self._enviar()
        else:
            self._pagina("No encontrado", "<p>Esa ruta no existe.</p>", 404)

    def _drenar(self, nbytes: int) -> None:
        """Lee y descarta hasta ``nbytes`` del cuerpo de la peticion."""
        restante = nbytes
        while restante > 0:
            trozo = self.rfile.read(min(restante, 64 * 1024))
            if not trozo:
                break
            restante -= len(trozo)

    def _leer_formulario(self) -> Tuple[Dict[str, str], List[Tuple[str, bytes]]]:
        """Lee el multipart del POST -> (campos de texto, adjuntos).

        Sin usar el modulo ``cgi`` (eliminado en Python 3.13): el parser
        MIME de la propia stdlib interpretara el cuerpo con la cabecera
        Content-Type que trae la peticion.
        """
        config = self.server.config
        try:
            longitud = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            longitud = 0
        if longitud <= 0:
            raise ValueError("formulario vacio")
        if longitud > config.max_tamano_bytes + LIMITE_POST_EXTRA:
            # Drenar (con tope) antes de responder 413: si cerramos sin
            # leer, el navegador que aun esta enviando recibe un reset y
            # no llega a ver la pagina de error.
            self._drenar(min(longitud, 16 * 1024 * 1024))
            raise OverflowError("formulario demasiado grande")

        cuerpo = self.rfile.read(longitud)
        ct = self.headers.get("Content-Type", "")
        mensaje = BytesParser(policy=policy.default).parsebytes(
            b"Content-Type: " + ct.encode("latin-1", "replace")
            + b"\r\nMIME-Version: 1.0\r\n\r\n" + cuerpo
        )
        if not mensaje.is_multipart():
            raise ValueError("peticion multipart invalida")

        campos: Dict[str, str] = {}
        adjuntos: List[Tuple[str, bytes]] = []
        for parte in mensaje.iter_parts():
            nombre = parte.get_param("name", header="content-disposition")
            if not nombre:
                continue
            nombre = str(nombre)
            binario = parte.get_payload(decode=True) or b""
            archivo = parte.get_filename()
            if nombre == "adjunto" and archivo and binario:
                adjuntos.append((archivo, binario))
            else:
                campos[nombre] = binario.decode("utf-8", "replace")
        return campos, adjuntos

    def _enviar(self) -> None:
        config = self.server.config
        buzones = self.server.buzones
        try:
            campos, adjuntos = self._leer_formulario()
        except OverflowError:
            self._pagina("Mensaje demasiado grande",
                         f"<p>El limite es de {config.max_tamano_mb} MB.</p>",
                         413)
            return
        except ValueError as exc:
            self._pagina("Formulario invalido", f"<p>{_esc(exc)}</p>", 400)
            return

        # Emisor: tiene que ser un buzón real (el hidden del formulario
        # no es una identidad fiable, pero si uno no existe, se corta).
        emisor = campos.get("de", "").strip()
        if not buzones.existe(emisor):
            self._pagina("No autorizado",
                         "<p>Emisor no valido.</p>", 403)
            return

        # Destinos: mismo anti-relay que el SMTP.
        crudos = [d.strip() for d in campos.get("para", "").split(",")
                  if d.strip()]
        if not crudos:
            self._pagina("Faltan destinatarios",
                         "<p>Indica al menos un destinatario.</p>", 400)
            return
        locales: List[str] = []
        for destino in crudos:
            partes = parsear_direccion(destino)
            if (partes is None
                    or partes[1].lower() != config.dominio.lower()
                    or not buzones.existe(partes[0])):
                self._pagina(
                    "Destinatario no valido",
                    f"<p><b>{_esc(destino)}</b> no es un buzón de "
                    f"{_esc(config.dominio)} (el servidor no envía fuera "
                    "del dominio local).</p>",
                    400,
                )
                return
            locales.append(partes[0])

        asunto = _sin_saltos(campos.get("asunto", "")) or "(sin asunto)"
        cuerpo_txt = campos.get("cuerpo", "")
        dir_de = f"{emisor}@{config.dominio}"
        dir_para = ", ".join(f"{u}@{config.dominio}" for u in locales)

        try:
            data = construir_mensaje(dir_de, dir_para, asunto, cuerpo_txt,
                                     adjuntos)
            ip_cliente = self.client_address[0] if self.client_address else "desconocido"
            cabecera = (
                "Received: from webmail (" + ip_cliente + ")\r\n"
                "\tby " + config.dominio + " (servidor IFOR) with HTTP;\r\n"
                "\t" + formatdate(localtime=True) + "\r\n"
            ).encode("utf-8")
            cola_id = buzones.entregar(locales, cabecera + data,
                                       origen=ip_cliente)
        except Exception:  # noqa: BLE001 -- disco u otro fallo interno
            log.exception("error entregando mensaje del webmail")
            self._pagina("Error interno",
                         "<p>No se ha podido entregar el mensaje.</p>", 500)
            return

        enlaces = " · ".join(
            f"<a href='/?u={_esc(u)}'>bandeja de {_esc(u)}</a>"
            for u in locales
        )
        self._pagina(
            "Mensaje entregado",
            f"<p>Entregado a <b>{_esc(dir_para)}</b> "
            f"(cola <code>{_esc(cola_id)}</code>).</p>"
            f"<p><a href='/redactar?u={_esc(emisor)}'>Redactar otro</a> · "
            f"{enlaces}</p>",
        )
