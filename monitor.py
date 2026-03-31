import os
import hashlib
import time
from datetime import date
import requests
from playwright.sync_api import sync_playwright

HASH_FILE = "last_hash.txt"

def fetch_tdlc():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()

        causas_data = []
        uuid_map = {}  # idCausa -> uuid

        def handle_response(response):
            try:
                if "byestadodiario" in response.url:
                    data = response.json()
                    causas_data.extend(data)
                # Interceptar URLs con uuid
                if "uuid=" in response.url and "idCausa=" in response.url:
                    from urllib.parse import urlparse, parse_qs
                    params = parse_qs(urlparse(response.url).query)
                    id_causa = params.get("idCausa", [None])[0]
                    uuid = params.get("uuid", [None])[0]
                    if id_causa and uuid:
                        uuid_map[id_causa] = uuid
            except:
                pass

        page = context.new_page()
        page.on("response", handle_response)
        page.goto("https://consultas.tdlc.cl/estadoDiario", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(3000)

        try:
            detalle_icon = page.wait_for_selector(".glyphicon-new-window", timeout=15000)
            if detalle_icon:
                detalle_icon.click()
                page.wait_for_timeout(6000)
                print("Clic en detalle realizado")
        except Exception as e:
            print("Error al hacer clic:", e)

        # Intentar hacer clic en cada causa para capturar su uuid
        try:
            links_causa = page.query_selector_all("table a, td a, .glyphicon-eye-open")
            print(f"Links encontrados: {len(links_causa)}")
            for link in links_causa[:3]:  # solo primeros 3 para no demorar
                href = link.get_attribute("href") or ""
                if "uuid=" in href and "idCausa=" in href:
                    from urllib.parse import urlparse, parse_qs
                    params = parse_qs(urlparse(href).query)
                    id_causa = params.get("idCausa", [None])[0]
                    uuid = params.get("uuid", [None])[0]
                    if id_causa and uuid:
                        uuid_map[id_causa] = uuid
        except Exception as e:
            print("Error capturando links:", e)

        print("UUID map:", uuid_map)
        browser.close()

    if not causas_data:
        return "No se encontraron causas"

    resultado = f"Estado Diario TDLC - {date.today().strftime('%d/%m/%Y')}\n"
    resultado += f"Total causas: {len(causas_data)}\n\n"

    for causa in causas_data:
        rol = causa.get('rol', 'Sin ROL')
        descripcion = causa.get('descripcion', 'Sin descripción')
        n_tramites = causa.get('tramites', 0)
        id_causa = str(causa.get('id', ''))

        if id_causa in uuid_map:
            link = f"https://consultas.tdlc.cl/estadoDiario?idCausa={id_causa}&uuid={uuid_map[id_causa]}"
        else:
            link = f"https://consultas.tdlc.cl/do_search?proc={causa.get('procedimiento', {}).get('id', 3)}&idCausa={id_causa}&buscador=true"

        resultado += f"ROL: {rol}\n"
        resultado += f"Carátula: {descripcion}\n"
        resultado += f"Trámites hoy: {n_tramites}\n"
        resultado += f"🔗 {link}\n\n"

    return resultado

def get_hash(text):
    return hashlib.md5(text.encode()).hexdigest()

def load_last_hash():
    if os.path.exists(HASH_FILE):
        with open(HASH_FILE, "r") as f:
            return f.read().strip()
    return ""

def save_hash(h):
    with open(HASH_FILE, "w") as f:
        f.write(h)

def send_telegram(message):
    max_chars = 4000
    partes = []

    while len(message) > max_chars:
        corte = message[:max_chars].rfind("\n")
        if corte == -1:
            corte = max_chars
        partes.append(message[:corte])
        message = message[corte:].strip()
    partes.append(message)

    total = len(partes)
    for i, parte in enumerate(partes):
        encabezado = f"📋 Parte {i+1}/{total}\n\n" if total > 1 else ""
        url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_TOKEN']}/sendMessage"
        requests.post(url, json={
            "chat_id": os.environ["TELEGRAM_CHAT_ID"],
            "text": encabezado + parte
        })
        print(f"Telegram parte {i+1}/{total} enviado")
        time.sleep(1)

if __name__ == "__main__":
    print("Verificando TDLC...")
    raw = fetch_tdlc()
    print("Texto extraído:", raw[:300])

    if "No se encontraron causas" in raw:
        print("Página vacía, ignorando.")
    else:
        raw_sin_fecha = "\n".join(raw.split("\n")[1:])
        current_hash = get_hash(raw_sin_fecha)

        if current_hash == load_last_hash():
            print("Sin cambios.")
        else:
            print("¡Contenido nuevo! Enviando resumen...")
            mensaje = f"🔔 TDLC {date.today().strftime('%d/%m/%Y')}\n\n{raw}"
            send_telegram(mensaje)
            save_hash(current_hash)
            print("Listo.")
