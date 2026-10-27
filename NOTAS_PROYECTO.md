# Notas del proyecto: Escaneo de Tickets (CB Asesor)

Registro de lo aprendido y decidido. Actualizar cada vez que aprendamos algo nuevo.

## Infraestructura y Producción Oficial
- **Servidor Activo (Producción):** **Google Cloud Platform (GCP)** (Instancia en Frankfurt `europe-west3-c`, IP `34.159.160.162`).
- **Dominio Institucional y SSL:** **`https://tickets.cbasesor.com`** con certificado SSL Let's Encrypt (renovación automática) y reverse proxy Nginx redirigiendo a `127.0.0.1:8000`.
- **Servicio en Segundo Plano:** `tickets.service` administrado por `systemd` con reinicio automático.
- **Ventajas frente a Render:**
  - Sin límite de 750 horas mensuales (corre 24/7 de forma permanente).
  - No se duerme por inactividad.
  - Almacenamiento persistente en disco en `/var/www/tickets/`.
  - Costo marginal: $0,00 (aprovecha la misma instancia VM de GCP del bot financiero).
- **Subir cambios a producción:**
  - Al hacer `git push origin main` a GitHub, para actualizar en el servidor de GCP se ejecuta:
    ```bash
    cd /var/www/tickets && git pull && sudo systemctl restart tickets
    ```

## Cómo funciona la app
- App web (FastAPI) instalada como PWA en el celular.
- `app.py` sirve primero `index.html` de la raíz y, si no existe, `templates/index.html`. **Los dos archivos deben mantenerse idénticos.**
- Datos de cada mes:
  - `Gastos_YYYY_MM.json`: datos extraídos de cada ticket.
  - `Tickets_YYYY_MM.pdf`: una página por ticket, con la foto.
- **Orden:** el ticket N de la lista corresponde a la página N del PDF. Los nuevos se insertan siempre al principio.
- Cada usuario (email) tiene sus propias carpetas.

## Dónde se guardan los datos (3 capas)
1. **Servidor Render:** el disco gratis se borra al reiniciar o redesplegar.
2. **Google Drive:** respaldo automático (`gdrive_sync.py`); restaura al servidor cuando queda vacío.
3. **Celular (IndexedDB "Vault"):** copia local de datos y PDF.
- Reinstalar la app **no pierde datos**: al entrar con el mismo email se recuperan del servidor.
- La copia de seguridad manual (JSON) es una cuarta protección. Desde la versión 2 incluye los PDF con las imágenes. Los backups anteriores solo tienen datos.

## Problemas resueltos
| Problema | Causa | Solución |
|---|---|---|
| Al descargar Excel/CSV/ZIP/PDF la app quedaba en la pantalla de descarga y había que reiniciarla | Los botones eran enlaces que navegaban a la URL del archivo | Un script intercepta el clic, baja el archivo en segundo plano y lo guarda sin cambiar de pantalla |
| No se podía elegir dónde guardar el backup | Descarga directa del navegador | Menú "compartir" del celular (Drive, WhatsApp, Archivos); si no está disponible, se guarda en Descargas |
| El botón atrás del celular cerraba la app | Las pantallas internas no usaban el historial | `history.pushState` + `popstate`: atrás cierra la pantalla superior (imagen, edición, detalle) |
| Render se dormía a los 15 min y mostraba su pantalla de carga | Plan gratuito de Render | Endpoint `/health` + monitor en UptimeRobot cada 5 min |

## Funciones agregadas
- **Detalle por comercio:** tocar un comercio en Control de Gastos abre la lista de sus tickets (fecha y monto) con ver imagen, editar y eliminar.
- **Editar:** si la nueva fecha cae en otro mes, el ticket (datos e imagen) se mueve al mes correcto.
- **Backup con imágenes:** el JSON incluye el PDF de cada mes en base64.
- Código: `ticket_manager.py` y endpoints `/api/ticket-image`, `/api/ticket-edit` y `/api/ticket-delete` en `app.py`.

## Mantener Render despierto y límites de horas
- Monitor en UptimeRobot (HTTP, cada 10 min) hacia `https://tickets-cbasesor.onrender.com/health`.
- **Causa de suspensiones pasadas resuelta:** Render otorga 750 h/mes gratis por cuenta. Había 3 proyectos en la misma cuenta (`tickets-cbasesor`, `Whatsapp-bots` y `binance-quant-bot`), lo que consumía las horas hacia el día 10 de cada mes.
- **Solución implementada (Octubre 2026):**
  - `Whatsapp-bots` se migró a su propia cuenta de Render (`claudioabarzola@gmail.com`) con sus 750 h exclusivas.
  - `binance-quant-bot` se ejecuta localmente en la PC.
  - `tickets-cbasesor` queda como **único servicio** en la cuenta `barzolaclaudio@gmail.com`.
  - En meses de 31 días (744 h), las 750 h alcanzan para operar 24/7 sin suspensiones.
  - UptimeRobot configurado cada 10 min (menor a los 15 min de inactividad de Render para evitar que se duerma).

## Lecciones y precauciones
- Antes de desinstalar la app, hacer un backup nuevo y guardarlo fuera del celular.
- Cada `git push` redespliega Render y puede borrar su disco. Los datos se recuperan desde Drive o el celular.
- Después de un cambio, cerrar la app por completo y abrirla de nuevo. Si no toma el cambio, es caché de la PWA (`sw.js`).
- No subir a git el video `WhatsApp Video ... .mp4`.

## Ideas pendientes
- Guardar el armazón de la app en el celular para que abra al instante aunque el servidor esté dormido.
- Si algún ticket antiguo tuviera el PDF desfasado respecto a sus datos, podría mostrar otra imagen (no pasa con los nuevos).

## Uso compartido (padre e hija, mismo email)
- Los dos celulares usan el mismo email; los datos viven en el servidor y se comparten.
- **Duplicados:** al guardar, el servidor compara con los tickets del mes (misma fecha y total, y mismo comercio o CUIT). Si coincide, la app avisa y pregunta si se quiere cargar igual (parametro `force` en `/api/upload`).
- **Borrados entre celulares:** el celular solo restaura un mes desde su copia local si el servidor quedo totalmente vacio. Si el servidor tiene otros meses, se respeta el borrado hecho desde otro celular.
- Las cargas simultaneas no se pisan: el servidor atiende las subidas de a una (un solo proceso).

## Infraestructura de Correos Institucionales (DonWeb & Gmail)
- **Servidor de Correo Host:** `c2631658.ferozo.com` (Puerto 465 SSL / 587 STARTTLS).
- **1. Casilla de Envío Automático / Servidor (`notificaciones@cbasesor.com`):**
  - **Estado:** Creada en DonWeb, configurada en Gmail como remitente y activa en Google Cloud VM (Octubre 2026).
  - Casilla técnica tipo robot para envíos desatendidos desde Google Cloud VM.
  - Envía códigos OTP de registro y validación a usuarios nuevos.
  - Envía paquetes contables mensuales con planillas Excel y documentación bancaria adjunta a los contadores de cada usuario.
  - Pasarela SMTP de producción: `smtp.gmail.com:587` (App Password autorizada con remitente `CB Asesor <notificaciones@cbasesor.com>`). Cero bloqueo de firewall y entrega 100% garantizada.
- **2. Casilla de Atención Humana / Soporte (`soporte@cbasesor.com`):**
  - **Estado:** Creada en DonWeb, Reenvío a `barzolaclaudio@gmail.com` activado y "Enviar como" en Gmail verificado y confirmado (Octubre 2026).
  - Casilla oficial de contacto que figurará en la ficha pública de **Google Play Store**.
  - Visible en el pie de página de la web y en todos los correos automáticos.
  - Permite responder y redactar directamente desde la interfaz de Gmail en PC y móvil sin abrir Ferozo Webmail.
- **3. Casilla Institucional General (`contacto@cbasesor.com`):**
  - **Estado:** Creada en DonWeb, Reenvío activado y "Enviar como" en Gmail verificado y confirmado (Octubre 2026). Opera desde la misma bandeja de Gmail.

## Cierre Contable Mensual & Gestión Documental (Octubre 2026)
- **Documentación del Período:** Soporte para adjuntar extractos bancarios, resúmenes de tarjetas de crédito corporativas/personales, comprobantes de cuotas de préstamos y boletos.
  - Almacenamiento aislado y privado por usuario en `Documentos_Mensuales/<safe_email>/<month_key>/`.
- **Selector de Paquete de Envío al Contador:** Modal interactivo con checkboxes que permite seleccionar exactamente qué archivos enviar al contador (Excel de gastos, PDF de comprobantes, extractos bancarios tildados).
- **Paquete Contable Mensual en ZIP (Integración con OneDrive/PC):**
  - Botón directo en el dashboard y dentro del modal del contador: **"Descargar Paquete Contador (.ZIP)"**.
  - Genera automáticamente un archivo comprimido nombrado con el período (ej. `Contador_Octubre_2026.zip`), listo para descomprimir o respaldar en la carpeta OneDrive `#responsable inscripto/Contador Octubre 2026`.
  - Contenido empaquetado:
    1. `Gastos_Octubre_2026.xlsx` (Resumen, Libro IVA Compras y Detalle de ítems).
    2. `Libro_IVA_Compras_Octubre_2026.csv` (para importación directa en sistemas contables como Tango/Holistor).
    3. `Tickets_Comprobantes_Octubre_2026.pdf` (todas las fotos de comprobantes escaneados).
    4. Todos los documentos bancarios/cuotas adjuntos en el período (ej. `Cuota Supervielle 2-24.pdf`, extractos).
    5. `RESUMEN_CIERRE.txt` con los totales fiscales calculados (Neto, IVA, Percepciones IIBB/IVA).
  - Descarga no bloqueante mediante blob en segundo plano, sin recargar ni salir de la app PWA.
- **Envío Transaccional Seguro:** La casilla actúa como tubería SMTP (no almacena copias de adjuntos de usuarios).
- **Recuperación de Contraseña:** Flujo de autoservicio con código de seguridad OTP de 6 dígitos enviado por email y restablecimiento de contraseña.
- **Detección Inteligente de PDFs en Subida Principal:** Si el usuario selecciona un PDF o comprobante bancario/cuota desde el botón principal de recorte de fotos ("Elegir Archivo / Galería"), la app detecta que no es una foto de ticket, evita romper el visor de recorte y le ofrece guardarlo de inmediato en "Documentos del Mes" para su contador.
- **Módulo de Resúmenes de Tarjetas Inteligentes con IA (Etapa 1 - Octubre 2026):**
  - Procesador integral de resúmenes de tarjetas de crédito y bancarias (`card_processor.py`) usando PyMuPDF + Gemini IA.
  - Soporta resúmenes de Visa (BNA, Credicoop), Mastercard (Nativa BNA), Cabal (Credicoop), Lemon Cash y fintechs.
  - Extracción automática de:
    - Entidad bancaria, marca, tipo, terminación y fechas de cierre/vencimiento.
    - Total adeudado en Pesos ($) y Dólares (USD), y pago mínimo.
    - **Lista completa de consumos individuales** con fecha, comercio, plan de cuotas (ej. `02/06`), moneda e importe.
    - **Categorización inteligente:** Combustible, Peajes, Supermercado, Servicios y Software, Indumentaria, Varios, etc.
    - **Desglose de impuestos y tasas bancarias:** Sellos, Intereses de financiación, IVA 21% sobre intereses, Percepciones de Ingresos Brutos y Percepciones AFIP (RG 4815/5463).
  - Interfaz web interactiva: botón dedicado "Resúmenes de Tarjetas (IA)", modal visual con tarjetas estilizadas, visor desplegable de compras y control de eliminación.
  - **Integración con Excel:** Nueva pestaña institucional **`Resumen Tarjetas`** en el reporte `Gastos_Mes_Año.xlsx` con tablas formateadas con la identidad visual CB Asesor.
  - Inclusión automática en el paquete `.ZIP` y envío por correo al contador.

## Aspectos Legales, Marcas y Términos de Uso (Pendiente para Lanzamiento Comercial / Google Play)
- **Registro de Marca:**
  - Registrar la denominación y logotipo **"CB Asesor"** ante el INPI (Instituto Nacional de la Propiedad Industrial en Argentina) en las clases pertinentes (servicios financieros/asesoría contable y software/tecnología).
- **Términos y Condiciones del Servicio (T&C):**
  - **Delimitación de responsabilidad fiscal:** Establecer expresamente que la aplicación es una herramienta tecnológica de asistencia, digitalización y organización documental; no sustituye el juicio ni la labor de un profesional en ciencias económicas matriculado, ni asume responsabilidad por liquidaciones o declaraciones juradas presentadas ante AFIP/ARCA u organismos provinciales (ARBA, AGIP, etc.).
  - **Responsabilidad del usuario:** El usuario es el único responsable de la fidelidad, autenticidad y carga de sus comprobantes físicos o electrónicos.
  - **Prohibición de mal uso y fraude:** Cláusula estricta que prohíbe el uso de la aplicación para falsificación, adulteración de importes, CAE apócrifo o evasión fiscal.
- **Política de Privacidad y Tratamiento de Datos (Google Play Policy):**
  - Obligatorio para publicación en Google Play Store.
  - Documentar que la app opera bajo la premisa de **privacidad absoluta ("Zero-Cloud Image Storage")**: las fotos y documentos se procesan en memoria volátil en el servidor exclusivamente para extracción OCR y residen de forma privada en el almacenamiento local del dispositivo del usuario (IndexedDB Vault).
  - Especificar el uso del correo electrónico únicamente para autenticación segura (PIN/OTP) y remisión autorizada de reportes al contador.
