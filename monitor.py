import os
import hashlib
from datetime import date
import requests
from playwright.sync_api import sync_playwright

CALLMEBOT_PHONE    = os.environ["CALLMEBOT_PHONE"]
CALLMEBOT_APIKEY   = os.environ["CALLMEBOT_APIKEY"]
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]
HASH_FILE          = "last_hash.txt"

def fetch_tramites(causa_id, session_headers):
    url = f"https://consultas.tdlc.cl/rest/tramite/byorden/{causa_id}"
    r = requests.get(url, headers=session_headers, timeout=10)
    try:
        return r.json()
    except:
        return []

def fetch_tdlc():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()

        causas_data = []
        cookies_capturadas = {}

        def handle_response(response):
            try:
                if "byestadodiario" in response.url:
                    causas_data.extend(response.json())
            except:
                pass

        page = context.new_page()
        page.on("response", handle_response)
        page.goto("https://consultas.tdlc.cl/estadoDiario", wait_until="networkidle")
        page.wait_for_timeout(3000)

        # Hacer clic en detalle
        try:
            detalle_icon = page.query_selector(".glyphicon-new-window")
            if detalle_icon:
                detalle_icon.click()
                page.wait_for_timeout(3000)
        except Exception as e:
            print("Error al hacer clic:", e)

        # Capturar cookies para usarlas en requests
        cookies = context.cookies()
        browser.close()

    # Construir headers con cookies
    cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
    session_headers = {
        "User-Agent": "Mozilla/5.0",
        "Cookie": cookie_str,
        "Referer": "https://consultas.tdlc.cl/estadoDiario"
    }

    if not causas_data:
        return "No se encontraron causas"

    resultado = f"Estado Diario TDLC - {date.today().strftime('%d/%m/%Y')}\n"
    resultado += f"Total causas: {len(causas_data)}\n\n"

    for causa in causas_data:
        rol = f"{causa.get('procedimiento', {}).get('iniciales', '')}-{causa.get('folio', '')}-{causa.get('anio', '')}"
        descripcion = causa.get('descripcion', 'Sin descripción')
        causa_id = causa.get('idOrdenTrabajo')

        resultado += f"ROL: {rol}\n"
        resultado += f"Carátula: {descripcion}\n"

        # Obtener trámites de esta causa
        tramites = fetch_tramites(causa_id, session_headers)
        if tramites:
            for t in tramites:
                tipo = t.get('tipoTramite', {}).get('name', 'Sin tipo') if isinstance(t.get('tipoTramite'), dict) else 'Sin tipo'
                fecha = t.get('fechaTramite', '')[:10] if t.get('fechaTramite') else ''
                resultado += f"  → {tipo} ({fecha})\n"
        else:
            resultado += "  → Sin trámites detallados\n"

        resultado += "\n"

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
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/tdlc-monitor",
        "X-Title": "TDLC Monitor"
    }
    body = {
        "model": "google/gemma-3-4b-it:free",
        "messages": [{
            "role": "user",
            "content": (
                f"Eres un asistente juridico. A continuacion esta el estado diario del "
                f"TDLC (Tribunal de Defensa de la Libre Competencia de Chile) del {date.today().strftime('%d/%m/%Y')}.\n\n"
                f"Lista cada causa con su numero de rol, las partes involucradas y el tipo de actuacion o resolucion. "
                f"Usa vinetas. Maximo 300 palabras. Responde en espanol con tildes correctas.\n\nCONTENIDO:\n{raw_text[:8000]}"
            )
        }]
    }
    r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=body)
    print("OpenRouter response:", r.json())
    return r.json()["choices"][0]["message"]["content"]

def send_whatsapp(message):
    url = (
        f"https://api.callmebot.com/whatsapp.php"
        f"?phone={CALLMEBOT_PHONE}&text={requests.utils.quote(message)}&apikey={CALLMEBOT_APIKEY}"
    )
    r = requests.get(url)
    print("WhatsApp status:", r.status_code)

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
