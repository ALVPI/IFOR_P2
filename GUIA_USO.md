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

A los ~3 segundos el navegador se abre **solo** con el webmail
(`http://localhost:8080/`). Si sale una página de "no se puede conectar",
es que el servidor no ha arrancado (mira el aviso de abajo sobre el
puerto 25) o el navegador ha ido demasiado pronto: ábrelo tú a mano con
la misma dirección.

> ⚠️ El puerto 25 pide **ejecutar la consola como Administrador**
> (clic derecho → "Ejecutar como administrador"). Si no tienes permisos,
> arranca con puerto alternativo: `py -3 servidor.py todo --puerto 2525`.
> Ojo: en ese caso el SMTP está en el 2525, pero **el webmail sigue en el
> 8080**, que es por donde se manda y se lee desde el navegador.

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

El caso completo: pasar el **`Confidencial.pdf`** de `pepe` a `ana`
entre dos máquinas. Llama **VM A** a la del servidor y **VM B** a la otra.

### Paso 1 — En la VM A (la del servidor)

1. Crea los dos buzones (una línea por buzón, desde la carpeta
   `servidor/`; también vale doble clic en `crear_usuario.bat`):

   ```bat
   py -3 servidor.py usuario alta pepe
   py -3 servidor.py usuario alta ana
   ```

   > Si el servidor ya está arrancado también puedes crearlos: él los
   > recoge solo, no hace falta reiniciar.

2. Doble clic en **`arrancar.bat`** (como Administrador). A los ~3 s se
   abre solo el navegador con el webmail. **Deja esa ventana abierta**.
3. Apunta la IP de la VM A: consola → `ipconfig` → p. ej. `192.168.255.X`.

### Paso 2 — En la VM B (la que envía)

1. Abre el navegador y ve a la IP del paso 1:

   ```text
   http://192.168.255.X:8080/
   ```

2. Haz clic en **`pepe@empresa.local`** y pulsa **«Redactar mensaje»**.
3. Rellena:
   - **Para:** `ana@empresa.local`
   - **Asunto:** `Confidencial Escenario 1`
   - **Cuerpo:** un mensaje cualquiera.
   - **Adjunto:** «Examinar…» → selecciona el **`Confidencial.pdf`**.
4. Pulsa **«Enviar»**. Debe salir *«Mensaje entregado»*.

### Paso 3 — Comprobarlo (en la VM A, o en la que quieras)

1. En `http://IP-del-servidor:8080/` elige **`ana@empresa.local`** →
   **«abrir»** el mensaje.
2. Verás el PDF listado: haz clic y **se descarga**. Compáralo con el
   original (mismo tamaño y mismo contenido).
3. En la VM A, abre con el Bloc de notas
   `servidor\logs\envios.log`: hay **una línea por correo enviado** con
   fecha, quién lo envió, para quién, el asunto y el nombre del PDF
   adjunto. Eso es la evidencia del envío.

### Si la VM B no conecta

Casi siempre es una de estas tres cosas:

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

Cuando llegue un correo, el servidor deja **tres** cosas en la VM del
servidor, dentro de la carpeta `servidor/`:

```text
buzones/ana/mensajes/20261102-... .eml     ← el correo entero (con quién, cuándo)
buzones/ana/adjuntos/20261102-.../Confidencial.pdf   ← el archivo adjunto
logs/envios.log                            ← quién envió qué y con qué adjuntos
```

`logs/envios.log` es el **registro de envíos**: una línea por correo
(venga del navegador o del SMTP), con remitente, destinatario, asunto y
lista de adjuntos con su tamaño, por ejemplo:

```text
2026-11-05T12:22:09 | de: pepe@empresa.local | para: ana@empresa.local | asunto: Informe confidencial ¦ revision final | adjuntos: Confidencial.pdf (1 KB)
```

Solo se añade al final (nunca se borra ni se reescribe) y se puede cambiar
de sitio en `config.ini`, sección `[log] directorio`.

Eso es lo que se usa para la cadena de custodia. **No borres las carpetas
`buzones/` ni `logs/`** y ten en cuenta que esos datos **no se suben a
git** (son datos de cada VM).

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
y por dónde pasó. Ábrelo con cualquier editor de texto. Y en
`servidor\logs\envios.log` tienes el resumen de todos los envíos en una
sola línea cada uno (remitente, destinatario, asunto y adjuntos).

**¿Y si borro un buzón?**
`py -3 servidor.py usuario baja pepe` lo quita de la lista; los ficheros
se quedan en disco por si acaso.

---

Más detalles técnicos (códigos SMTP, límites, estructura del código):
[`servidor/README.md`](servidor/README.md) · Diseño:
[`PLAN.md`](PLAN.md)
