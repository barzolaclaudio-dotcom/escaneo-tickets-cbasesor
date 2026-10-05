import os
import json
import logging
from pathlib import Path

logger = logging.getLogger("gdrive")

# Google Drive API Client imports
try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    GDRIVE_AVAILABLE = True
except ImportError:
    GDRIVE_AVAILABLE = False
    logger.warning("google-api-python-client no instalado. Sincronización con Google Drive desactivada.")

SERVICE_ACCOUNT_FILE = Path(__file__).resolve().parent / "credentials.json"
GDRIVE_FOLDER_NAME = "CB_Asesor_Tickets"

def get_gdrive_service():
    """Retorna un cliente autenticado de Google Drive API si existen credenciales."""
    if not GDRIVE_AVAILABLE:
        return None

    creds = None
    # 1. Intentar desde variable de entorno (ideal para Render.com / Railway)
    env_json = os.environ.get("GDRIVE_SERVICE_ACCOUNT_JSON")
    if env_json:
        try:
            info = json.loads(env_json)
            creds = service_account.Credentials.from_service_account_info(
                info, scopes=['https://www.googleapis.com/auth/drive.file']
            )
        except Exception as e:
            logger.error(f"Error parseando GDRIVE_SERVICE_ACCOUNT_JSON: {e}")

    # 2. Intentar desde archivo credentials.json local
    if not creds and SERVICE_ACCOUNT_FILE.exists():
        try:
            creds = service_account.Credentials.from_service_account_file(
                str(SERVICE_ACCOUNT_FILE), scopes=['https://www.googleapis.com/auth/drive.file']
            )
        except Exception as e:
            logger.error(f"Error cargando credentials.json: {e}")

    if creds:
        return build('drive', 'v3', credentials=creds)
    return None

def get_or_create_folder(service, folder_name: str) -> str:
    """Busca o crea una carpeta en la raíz de Google Drive."""
    try:
        query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = service.files().list(q=query, fields="files(id, name)").execute()
        files = results.get('files', [])

        if files:
            return files[0]['id']

        # Crear carpeta si no existe
        folder_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        folder = service.files().create(body=folder_metadata, fields='id').execute()
        return folder.get('id')
    except Exception as e:
        logger.error(f"Error al obtener/crear carpeta Google Drive '{folder_name}': {e}")
        return None

def sync_file_to_gdrive(file_path: Path, target_folder_name: str = GDRIVE_FOLDER_NAME) -> str:
    """
    Sube o actualiza un archivo local (PDF o JSON) en Google Drive.
    Retorna el link directo de Google Drive o None.
    """
    service = get_gdrive_service()
    if not service:
        return None

    try:
        folder_id = get_or_create_folder(service, target_folder_name)
        if not folder_id:
            return None

        filename = file_path.name
        query = f"name = '{filename}' and '{folder_id}' in parents and trashed = false"
        results = service.files().list(q=query, fields="files(id, webViewLink)").execute()
        files = results.get('files', [])

        mimetype = 'application/json' if file_path.suffix == '.json' else 'application/pdf'
        media = MediaFileUpload(str(file_path), mimetype=mimetype, resumable=True)

        if files:
            # Actualizar archivo existente
            file_id = files[0]['id']
            updated_file = service.files().update(
                fileId=file_id,
                media_body=media,
                fields='id, webViewLink'
            ).execute()
            return updated_file.get('webViewLink')
        else:
            # Subir nuevo archivo
            file_metadata = {
                'name': filename,
                'parents': [folder_id]
            }
            new_file = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, webViewLink'
            ).execute()
            return new_file.get('webViewLink')

    except Exception as e:
        logger.error(f"Error sincronizando {file_path.name} con Google Drive: {e}")
        return None

def restore_all_from_gdrive(pdfs_dir: Path, data_dir: Path):
    """
    Restaura automáticamente los archivos PDFs y JSONs desde Google Drive si el servidor se reinició.
    """
    service = get_gdrive_service()
    if not service:
        return

    try:
        folder_id = get_or_create_folder(service, GDRIVE_FOLDER_NAME)
        if not folder_id:
            return

        query = f"'{folder_id}' in parents and trashed = false"
        results = service.files().list(q=query, fields="files(id, name)").execute()
        files = results.get('files', [])

        for f_info in files:
            fname = f_info['name']
            fid = f_info['id']

            if fname.startswith("Tickets_") and fname.endswith(".pdf"):
                local_path = pdfs_dir / fname
            elif fname.startswith("Gastos_") and fname.endswith(".json"):
                local_path = data_dir / fname
            else:
                continue

            if not local_path.exists() or local_path.stat().st_size == 0:
                request = service.files().get_media(fileId=fid)
                content = request.execute()
                with open(local_path, "wb") as f:
                    f.write(content)
                logger.info(f"Archivo restaurado exitosamente de Google Drive: {fname}")
    except Exception as e:
        logger.error(f"Error al restaurar archivos de Google Drive: {e}")

def sync_month_to_gdrive(month_str: str, pdfs_dir: Path, data_dir: Path):
    """Sincroniza el PDF y JSON del mes especificado con Google Drive en segundo plano."""
    try:
        pdf_path = pdfs_dir / f"Tickets_{month_str}.pdf"
        json_path = data_dir / f"Gastos_{month_str}.json"
        
        if pdf_path.exists():
            sync_file_to_gdrive(pdf_path)
        if json_path.exists():
            sync_file_to_gdrive(json_path)
    except Exception as e:
        logger.error(f"Error en sincronización en segundo plano de {month_str}: {e}")

def delete_file_from_gdrive(filename: str, target_folder_name: str = GDRIVE_FOLDER_NAME):
    """Elimina un archivo de Google Drive por su nombre para evitar restauraciones fantasma."""
    service = get_gdrive_service()
    if not service:
        return
    try:
        folder_id = get_or_create_folder(service, target_folder_name)
        if not folder_id:
            return
        query = f"name = '{filename}' and '{folder_id}' in parents and trashed = false"
        results = service.files().list(q=query, fields="files(id)").execute()
        for f_item in results.get('files', []):
            service.files().delete(fileId=f_item['id']).execute()
            logger.info(f"Eliminado de Google Drive: {filename}")
    except Exception as e:
        logger.error(f"Error eliminando {filename} de Google Drive: {e}")



