import os
import hashlib
import time
from datetime import date
import requests
from playwright.sync_api import sync_playwright

CALLMEBOT_PHONE    = os.environ["CALLMEBOT_PHONE"]
CALLMEBOT_APIKEY   = os.environ["CALLMEBOT_APIKEY"]
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]
HASH_FILE          = "last_hash.txt"

def fetch_tdlc():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()

        causas_data = []

        def handle_response(response):
            try:
                if "byestadodiario" in response.url:
                    data = response.json()
                    causas_data.extend(data)
            except:
                pass

        page = context.new_page()
        page.on("response", handle_response)
        page.goto("https://consultas.tdlc.cl/estadoDiario", wait_until="networkidle")
        page.wait_for_timeout(3000)

        try:
            detalle_icon = page.query_selector(".glyphicon-new-window")
            if detalle_icon:
                detalle_icon.click()
                page.wait_for_timeout(3000)
        except Exception as e:
            print("Error al hacer clic:", e)

        browser.close()

    if not causas_data:
        return "No se encontraron causas"

    resultado = f"Estado Diario TDLC - {date.today().strftime('%d/%m/%Y')}\n"
    resultado += f"Total causas: {len(causas_data)}\n\n"

    for causa in causas_data:
        rol = causa.get('rol', 'Sin ROL')
        descripcion = causa.get('descripcion', 'Sin descripción')
        n_tramites = causa.get('tramites', 0)
        resultado += f"ROL: {rol}\n"
        resultado += f"Carátula: {descripcion}\n"
        resultado += f"Trámites hoy: {n_tramites}\n\n"

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

def summarize(raw_text):
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    headers = {"Content-Type": "application/json"}
    params = {"key": os.environ["GEMINI_API_KEY"]}
    body = {
        "contents": [{
            "parts": [{
                "text": (
                    f"Eres un asistente juridico. A continuacion esta el estado diario del "
                    f"TDLC (Tribunal de Defensa de la Libre Competencia de Chile) del {date.today().strftime('%d/%m/%Y')}.\n\n"
                    f"Lista cada causa con su numero de rol, las partes involucradas y la cantidad de tramites realizados hoy. "
                    f"Usa vinetas. Maximo 300 palabras. Responde en espanol con tildes correctas.\n\nCONTENIDO:\n{raw_text[:8000]}"
                )
            }]
        }]
    }
    r = requests.post(url, headers=headers, params=params, json=body)
    data = r.json()
    print("Gemini response:", data)
    if "candidates" in data:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    else:
        return raw_text

def send_whatsapp(message):
    max_chars = 1500
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
        url = (
            f"https://api.callmebot.com/whatsapp.php"
            f"?phone={CALLMEBOT_PHONE}&text={requests.utils.quote(encabezado + parte)}&apikey={CALLMEBOT_APIKEY}"
        )
        r = requests.get(url)
        print(f"WhatsApp parte {i+1}/{total} status:", r.status_code)
        time.sleep(3)

if __name__ == "__main__":
    print("Verificando TDLC...")
    raw = fetch_tdlc()
    print("Texto extraído:", raw[:300])
    current_hash = get_hash(raw)

    if current_hash == load_last_hash():
        print("Sin cambios.")
    else:
        print("¡Contenido nuevo! Enviando resumen...")
        summary = summarize(raw)
        mensaje = f"🔔 TDLC {date.today().strftime('%d/%m/%Y')}\n\n{summary}"
        send_whatsapp(mensaje)
        save_hash(current_hash)
        print("Listo.")
