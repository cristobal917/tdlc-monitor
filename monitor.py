import os
import hashlib
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
        page = browser.new_page()
        page.goto("https://consultas.tdlc.cl/estadoDiario", wait_until="networkidle")
        page.wait_for_timeout(3000)
        
        # Captura el HTML completo para ver links y botones
        html = page.content()
        text = page.inner_text("body")
        
        # Intenta encontrar y hacer clic en el link de detalle
        try:
            # Busca links o botones en la tabla
            links = page.query_selector_all("table a, table button, td a")
            detalle_text = ""
            for link in links:
                link.click()
                page.wait_for_timeout(2000)
                detalle_text += page.inner_text("body") + "\n---\n"
                page.go_back()
                page.wait_for_timeout(2000)
        except Exception as e:
            print("Error al hacer clic en links:", e)
            detalle_text = ""
        
        browser.close()
        return text + "\n\nDETALLE:\n" + detalle_text

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
