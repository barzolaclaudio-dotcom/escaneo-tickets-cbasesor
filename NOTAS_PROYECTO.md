# Notas del proyecto: Escaneo de Tickets (CB Asesor)

Registro de lo aprendido y decidido. Actualizar cada vez que aprendamos algo nuevo.

## Cómo funciona la app
- App web (FastAPI) instalada como PWA en el celular, alojada en Render. Repo: `barzolaclaudio-dotcom/escaneo-tickets-cbasesor` (rama `main`).
- **Subir cambios:** al hacer `git push origin main`, Render redespliega solo (`autoDeploy: true`). Tarda unos minutos.
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

## Mantener Render despierto
- Monitor en UptimeRobot (HTTP, cada 5 min) hacia `https://tickets-cbasesor.onrender.com`. Conviene usar la ruta `/health`, que es más liviana.
- **Error cometido:** el monitor se creó primero con la URL de ejemplo `TU-APP.onrender.com`, que no existe, y mostraba "Down". Siempre usar la URL real.
- El plan gratis da ~750 h/mes, y un servicio activo 24/7 consume ~744 h. Alcanza solo si es el único servicio activo en la cuenta.
- Alternativa sin monitor externo: plan pago de Render (~USD 7/mes).

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
