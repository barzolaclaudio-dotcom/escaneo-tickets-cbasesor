import socket
import uvicorn
import sys
from pathlib import Path

def get_local_ip():
    """Detecta la IP local de la computadora en la red Wi-Fi / LAN."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        # No realiza una conexión real, pero permite determinar la interfaz predeterminada
        s.connect(('10.254.254.254', 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

def print_ascii_qr(url: str):
    """Imprime un código QR en consola en modo texto si qrcode está disponible."""
    try:
        import qrcode
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        print("\n  [ ESCANÉAME CON LA CÁMARA DE TU CELULAR ]")
        qr.print_ascii(invert=True)
    except Exception:
        pass

if __name__ == '__main__':
    port = 8000
    local_ip = get_local_ip()
    
    local_url = f"http://localhost:{port}"
    network_url = f"http://{local_ip}:{port}"
    
    print("=" * 60)
    print("       ESCÁNER DE TICKETS Y FACTURAS A - INICIADO")
    print("=" * 60)
    print(f"\n  Acceso desde esta PC:         {local_url}")
    print(f"  Acceso desde tu CELULAR:      {network_url}")
    print("\n  Nota: Tu celular y tu PC deben estar conectados a la misma red Wi-Fi.")
    
    print_ascii_qr(network_url)
    
    print("\n" + "=" * 60)
    print(" Presioná Ctrl+C para detener el servidor en cualquier momento.")
    print("=" * 60 + "\n")
    
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
