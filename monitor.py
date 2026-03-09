import requests
from bs4 import BeautifulSoup
import os
import hashlib
from datetime import date

CALLMEBOT_PHONE  = os.environ["CALLMEBOT_PHONE"]
CALLMEBOT_APIKEY = os.environ["CALLMEBOT_APIKEY"]
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]
HASH_FILE        = "last_hash.txt"

def fetch_tdlc():
    url = "https://consultas.tdlc.cl/estadoDiario"
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    return soup.get_text(separator="\n", strip=True)

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
                f"Eres un asistente jurídico. A continuación está el estado diario del "
                f"TDLC (Tribunal de Defensa de la Libre Competencia de Chile) del {date.today().strftime('%d/%m/%Y')}.\n\n"
                f"Haz un resumen claro y conciso de las causas, resoluciones o actuaciones publicadas. "
                f"Usa viñetas. Máximo 300 palabras.\n\nCONTENIDO:\n{raw_text[:6000]}"
            )
        }]
    }
    r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=body)
    print("OpenRouter response:", r.json())  # para ver si hay error
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
