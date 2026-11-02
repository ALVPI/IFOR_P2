# Guía de uso del correo — en lenguaje sencillo

Esto es un **servidor de correo privado** para la práctica. Funciona como un
Gmail casero: cada persona tiene su buzón (`pepe@empresa.local`), puede
enviar mensajes con archivos adjuntos y leerlos desde el navegador.

No hace falta internet. Solo Python y las VMs de siempre.

---

## 1. Qué necesitas

- Tener **Python 3 instalado** en la VM (compruébalo en una consola con
  `python --version`; si no lo tienes, pídelo al profesor o instálalo desde
  python.org).
- La carpeta **`servidor/`** de este repositorio dentro de la VM (clónala o
  cópiala en un pendrive).

---

## 2. Primer paso: crear los buzones

Abre una consola **dentro de la carpeta `servidor/`** y escribe (una línea
por buzón):

```bat
py -3 servidor.py usuario alta pepe
py -3 servidor.py usuario alta ana
```

Verás: `buzón creado: pepe@empresa.local`.

Si `py -3` no funciona, cambia `py -3` por `python`.

> Si te da un aviso de "permisos", no te preocupes: es solo para cuando
> más adelante arranques el servidor en el puerto 25.

---

## 3. Arrancar el servidor

**Forma fácil:** doble clic en **`arrancar.bat`**.

**Forma manual** (consola dentro de la carpeta `servidor/`):

```bat
py -3 servidor.py todo
```

Debes ver:

```text
SMTP    escuchando en 0.0.0.0:25 (dominio empresa.local)
Webmail en  http://0.0.0.0:8080/
```

**Déjala abierta esa ventana** mientras uséis el correo (para pararlo:
Ctrl+C).

> ⚠️ El puerto 25 pide **ejecutar la consola como Administrador**
> (clic derecho → "Ejecutar como administrador"). Si no tienes permisos,
> arranca con puerto alternativo: `py -3 servidor.py todo --puerto 2525`.

---

## 4. Enviar un correo con el Confidencial.pdf

1. Abre el navegador (Edge/Chrome) en **cualquier VM** y ve a:

   ```text
   http://IP-del-servidor:8080/
   ```

   (La IP la sacas con `ipconfig` en la VM del servidor; usa la misma red
   NAT de VirtualBox de siempre.)

2. Haz clic en **tu buzón**, por ejemplo `pepe@empresa.local`.
3. Pulsa **«Redactar mensaje»**.
4. Rellena:
   - **Para:** `ana@empresa.local` (tiene que ser de este dominio;
     si pones un correo de fuera, te lo rechaza a propósito).
   - **Asunto:** lo que quieras.
   - **Cuerpo:** un mensaje.
   - **Adjunto:** botón "Examinar" → el `Confidencial.pdf`.
5. Pulsa **«Enviar»**. Si todo va bien verás: *"Mensaje entregado"*.

---

## 5. Leer el correo y descargar el adjunto

1. En `http://IP-del-servidor:8080/` elige el buzón **destino** (`ana`).
2. Verás la lista de correos. Pulsa **«abrir»**.
3. En la página del correo verás los **adjuntos**: haz clic en
   `Confidencial.pdf` y se descarga al equipo.

---

## 6. Probar entre dos VMs (el caso real del Escenario 1)

1. En la VM 1: arranca el servidor y crea los buzones `pepe` y `ana`.
2. En la VM 2: abre el navegador → `http://IP-del-servidor:8080/` →
   redacta como `pepe` y envía el PDF a `ana`.
3. En la VM 1 (o en cualquier otra): bandeja de `ana` → descargar el PDF.

Si la VM 2 no conecta, casi siempre es una de estas tres cosas:

- **Firewall**: en la VM del servidor, consola como Administrador:

  ```bat
  netsh advfirewall firewall add rule name="Correo IFOR SMTP" dir=in action=allow protocol=TCP localport=25
  netsh advfirewall firewall add rule name="Correo IFOR web" dir=in action=allow protocol=TCP localport=8080
  ```

- **IP equivocada**: comprueba con `ipconfig`.
- **Las VMs no están en la misma red NAT** de VirtualBox (Configuración →
  Red → adaptador 1 → Red NAT).

---

## 7. Qué guardar como evidencia

Cuando llegue un correo, el servidor deja dos ficheros en la VM del
servidor, dentro de la carpeta `servidor/`:

```text
buzones/ana/mensajes/20261102-... .eml     ← el correo entero (con quién, cuándo)
buzones/ana/adjuntos/20261102-.../Confidencial.pdf   ← el archivo adjunto
```

Eso es lo que se usa para la cadena de custodia. **No borres la carpeta
`buzones/`** y ten en cuenta que esas carpetas **no se suben a git** (son
datos de cada VM).

---

## 8. Mensajes de error — qué significan

| Ves esto... | Quiere decir... | Qué hacer |
|---|---|---|
| `550 Destinatario desconocido` | Ese buzón no existe | Créalo: `usuario alta nombre` |
| `554 Relay denegado` | Pusiste un correo de otro dominio | Usa solo `@empresa.local` |
| `421 Demasiadas conexiones` | Hay muchas conexiones a la vez | Espera unos segundos y reintenta |
| `552 Mensaje demasiado grande` | El adjunto pasa de 25 MB | Parte el archivo o sube `max_tamano_mb` en `config.ini` |
| No conecta nada | Firewall, IP o red NAT | Mira el punto 6 |
| `Acceso denegado` al arrancar | Puerto 25 sin permisos | Consola como Administrador, o `--puerto 2525` |

---

## 9. Preguntas rápidas

**¿Hace falta cuenta y contraseña?**
No. Es una red de laboratorio cerrada: quien entra ve las bandejas. Por eso
el servidor solo envía dentro de `empresa.local` y no a internet.

**¿Se puede usar Outlook/Thunderbird en vez del navegador?**
Ahora mismo no: el sistema es SMTP (enviar) + webmail (leer). Si el grupo
lo necesita, se puede añadir después.

**¿Cómo miro quién ha enviado qué?**
Cada `.eml` lleva una cabecera `Received` con la IP de origen, el momento
y por dónde pasó. Ábrelo con cualquier editor de texto.

**¿Y si borro un buzón?**
`py -3 servidor.py usuario baja pepe` lo quita de la lista; los ficheros
se quedan en disco por si acaso.

---

Más detalles técnicos (códigos SMTP, límites, estructura del código):
[`servidor/README.md`](servidor/README.md) · Diseño:
[`PLAN.md`](PLAN.md)
