# Resumen de Configuración del Entorno de Red y Compartición
**Práctica Forense: Escenario de Fuga de Información**

Este documento sintetiza la configuración técnica realizada en el servidor **Windows Server 2008** y las máquinas cliente para permitir la correcta exfiltración del archivo `Confidencial.pdf` a través de la red local virtualizada.

---

## 1º Tipo de Red de las 2 Máquinas Virtuales (VirtualBox)

Para que el servidor y las máquinas cliente se comuniquen entre sí mediante protocolos de red corporativos (SMB/CIFS), se debe modificar el tipo de adaptador de red por defecto:

1. **Configuración en VirtualBox (Para WS2008 y VM Cliente):**
   * Apagar las máquinas virtuales.
   * Entrar a **Configuración** > **Red** > **Adaptador 1**.
   * Cambiar el modo de *Conectado a:* de **NAT** a **Red NAT** (*NAT Network*).
   * Confirmar que ambas VMs están seleccionando el mismo nombre de Red NAT.
2. **Resultado Técnico:**
   * En lugar de que ambas máquinas tengan la IP `10.0.2.15` aislada, el servidor DHCP de la Red NAT asigna IPs únicas dentro del mismo segmento de red (ej. `192.168.255.7` o `10.0.2.4`), permitiendo la conectividad directa por puerto TCP 445 (SMB).

---

## 2º Permisos para que la Carpeta se Comparta

Para garantizar que el archivo `Confidencial.pdf` sea accesible desde la red, se deben aplicar correctamente tanto los **permisos de red (Share Permissions)** como los **permisos de disco (NTFS)** en Windows Server 2008.

### Paso A: Permisos de Red (Compartición)
1. Navegar hasta la carpeta local (ej. `C:\Empresa\ConfidencialInfo`).
2. Haz clic derecho > **Propiedades** > pestaña **Compartir** > **Uso compartido avanzado...**
3. Marcar **Compartir esta carpeta** (Nombre del recurso: `ConfidencialInfo`).
4. Haz clic en **Permisos**:
   * Seleccionar el grupo `Todos` (o `Everyone`).
   * Asignar permisos de **Control total** / **Lectura** en la columna *Permitir*.

### Paso B: Permisos de Disco (Seguridad NTFS)
1. En la misma ventana de propiedades de la carpeta, ir a la pestaña **Seguridad**.
2. Hacer clic en **Editar...** > **Agregar...**.
3. Añadir el usuario o grupo deseado (ej. `Todos` o el usuario específico `pepe`) y marcar la casilla **Control total** / **Lectura**.

### Paso C: Ajustes de Firewall y Red
1. En **Panel de control** > **Centro de redes y recursos compartidos**:
   * Activar la **Detección de redes** y el **Uso compartido de archivos**.
   * Desactivar el uso compartido con protección por contraseña si no se requiere autenticación estricta, o dejarlo activado exigiendo credenciales.
2. Verificar que el Firewall de Windows Server no bloquee el protocolo SMB (Puerto 445) o deshabilitarlo temporalmente para el laboratorio.

---

## 3º Cómo Dar de Alta al Usuario en Windows Server 2008

Para autenticar las peticiones entrantes desde las máquinas clientes, la cuenta de usuario debe existir en la base de datos de seguridad local (SAM) del servidor:

1. Abre la consola de comandos (`cmd.exe`) o PowerShell en **Windows Server 2008** como Administrador.
2. **Crear el usuario:**
   ```cmd
   net user pepe TuContraseñaSegura123! /add
   ```
3. **Verificar que el usuario ha sido creado correctamente:**
   ```cmd
   net user pepe
   ```
4. *(Opcional)* Asignar permisos explícitos de red mediante comandos:
   ```cmd
   net share ConfidencialInfo=C:\Empresa\ConfidencialInfo /grant:pepe,FULL
   ```

---

## 4º Cómo Acceder al Fichero desde una VM que NO es la Propia del Usuario

Desde la máquina cliente (ej. Windows 11 o Windows 10), el usuario no debe escribir la ruta directa del archivo PDF en la ventana de conexión por red, sino llamar a la ruta del **recurso compartido (UNC)** indicando explícitamente el origen del dominio/servidor.

### Opción A: A través de la Interfaz Gráfica (Explorador / Ejecutar)
1. Abrir la ventana **Ejecutar** (usando `Ctrl + R` en la VM o desde el menú Inicio).
2. Introducir la ruta UNC del recurso compartido (no del archivo individual):
   ```text
   \\192.168.255.7\ConfidencialInfo
   ```
3. Cuando Windows pida credenciales de red, indicar la IP o nombre del servidor antes del usuario para evitar que busque el usuario localmente en la máquina cliente:
   * **Usuario:** `192.168.255.7\pepe` *(o `IFOR-WS-2008\pepe`)*
   * **Contraseña:** `TuContraseñaSegura123!`
4. Al ingresar a la carpeta, hacer doble clic o copiar el archivo `Confidencial.pdf`.

### Opción B: Mediante Consola de Comandos (Mapeo Directo)
Abrir `cmd.exe` en la máquina cliente y ejecutar:
```cmd
net use Z: \\192.168.255.7\ConfidencialInfo /user:192.168.255.7\pepe TuContraseñaSegura123!
```
Esto creará una unidad de disco `Z:` en el cliente con acceso directo al archivo `Confidencial.pdf` listo para ser exfiltrado en los escenarios de la práctica.
