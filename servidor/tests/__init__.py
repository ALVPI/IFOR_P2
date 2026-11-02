# Paquete de pruebas del servidor de correo.
# Se ejecutan desde el directorio servidor/ con:
#     python3 -m unittest discover -v
#
# Las pruebas afirman el comportamiento a traves del protocolo (codigos
# SMTP y ficheros en disco); el registro de logs solo ensuciara la salida.
# Comenta la linea siguiente si necesitas ver los logs al depurar.
import logging

logging.disable(logging.CRITICAL)
