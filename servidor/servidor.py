"""servidor.py -- punto de entrada (CLI) del sistema de correo.

Uso tipico (en la VM Windows, con el paquete Python instalado):

    py -3 servidor.py smtp               # solo SMTP en el puerto 25 (admin)
    py -3 servidor.py smtp --puerto 2525 # sin privilegios, para pruebas
    py -3 servidor.py usuario alta pepe  # gestion de buzones
    py -3 servidor.py todo               # SMTP + webmail juntos

Tambien funciona con ``python3`` en GNU/Linux/macOS.
"""

import argparse
import logging
import sys

from buzon import Buzones
from config import cargar_config
from smtp_sesion import SesionSMTP
from srv_tcp import ServidorTCP

log = logging.getLogger("correo")


def _crear_servidor_smtp(config, buzones=None, puerto=None, host=None):
    """Monta y devuelve el ServidorTCP del SMTP (sin arrancarlo todavia).

    Si se pasa ``buzones`` (arranque combinado SMTP+webmail) se reutiliza
    esa instancia; si no, se crea una nueva a partir de la configuracion.
    """
    if puerto:
        config.smtp_puerto = puerto
    if host:
        config.smtp_host = host
    if buzones is None:
        buzones = Buzones(config)   # usuarios.json + buzones/ (validacion RCPT)
    return ServidorTCP(
        host=config.smtp_host,
        puerto=config.smtp_puerto,
        max_conexiones=config.max_conexiones,
        timeout_seg=config.timeout_seg,
        manejar=lambda sock, addr: SesionSMTP(
            sock, addr, config, buzones=buzones
        ).ejecutar(),
        # Respuesta enviada a quien se conecta cuando no quedan huecos.
        mensaje_rechazo=(
            f"421 4.7.0 {config.dominio} Demasiadas conexiones, "
            "intente mas tarde\r\n"
        ).encode("utf-8"),
    )


def cmd_smtp(args) -> int:
    config = cargar_config(args.config)
    servidor = _crear_servidor_smtp(config, puerto=args.puerto, host=args.host)
    print(f"SMTP escuchando en {config.smtp_host}:{config.smtp_puerto} "
          f"(dominio {config.dominio}). Ctrl+C para salir.")
    try:
        servidor.arrancar(bloqueante=True)
    except KeyboardInterrupt:
        print("\nDeteniendo...")
        servidor.parar()
    return 0


def cmd_todo(args) -> int:
    """SMTP + webmail en un unico proceso (lo tipico en la VM)."""
    config = cargar_config(args.config)
    buzones = Buzones(config)
    servidor = _crear_servidor_smtp(config, buzones,
                                    puerto=args.puerto, host=args.host)

    from webmail import Webmail   # import perezoso: smtp no depende de el

    web = Webmail(config, buzones)
    web.arrancar()
    print(f"SMTP    escuchando en {config.smtp_host}:{config.smtp_puerto} "
          f"(dominio {config.dominio})")
    print(f"Webmail en  http://{config.webmail_host}:{web.server_port}/")
    print("Ctrl+C para salir.")
    try:
        servidor.arrancar(bloqueante=True)
    except KeyboardInterrupt:
        print("\nDeteniendo...")
        servidor.parar()
        web.shutdown()
        web.server_close()
    return 0


def cmd_usuario(args) -> int:
    """alta <nombre> | baja <nombre> | listar -- gestion de buzones."""
    if args.accion in ("alta", "baja") and not args.nombre:
        print(f"error: la accion '{args.accion}' necesita un nombre "
              "(p. ej. usuario alta pepe)")
        return 2
    config = cargar_config(args.config)
    buzones = Buzones(config)
    try:
        if args.accion == "alta":
            buzones.alta(args.nombre)
            print(f"buzón creado: {args.nombre}@{config.dominio}")
        elif args.accion == "baja":
            buzones.baja(args.nombre)
            print(f"buzón eliminado: {args.nombre}@{config.dominio}")
        else:
            usuarios = buzones.listar()
            if not usuarios:
                print(f"(no hay usuarios en {config.dominio}; "
                      "crea uno con: usuario alta <nombre>)")
            for usuario in usuarios:
                print(f"{usuario}@{config.dominio}")
    except ValueError as exc:
        print(f"error: {exc}")
        return 1
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="servidor.py", description="Servidor de correo de la practica IFOR"
    )
    parser.add_argument(
        "--config", default=None, help="ruta alternativa a config.ini"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="registro detallado (DEBUG)"
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    p_smtp = sub.add_parser("smtp", help="arrancar el servidor SMTP")
    p_smtp.add_argument("--puerto", type=int, default=None,
                        help="sobreescribe el puerto de config.ini")
    p_smtp.add_argument("--host", default=None,
                        help="sobreescribe el host de config.ini")
    p_smtp.set_defaults(func=cmd_smtp)

    p_usu = sub.add_parser("usuario", help="gestionar buzones")
    p_usu.add_argument("accion", choices=["alta", "baja", "listar"],
                       help="que hacer con el buzón")
    p_usu.add_argument("nombre", nargs="?", default=None,
                       help="nombre de usuario (alta/baja)")
    p_usu.set_defaults(func=cmd_usuario)

    p_todo = sub.add_parser("todo", help="SMTP + webmail a la vez")
    p_todo.add_argument("--puerto", type=int, default=None,
                        help="sobreescribe el puerto SMTP de config.ini")
    p_todo.add_argument("--host", default=None,
                        help="sobreescribe el host SMTP de config.ini")
    p_todo.set_defaults(func=cmd_todo)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
