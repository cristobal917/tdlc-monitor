import requests
from bs4 import BeautifulSoup
import anthropic
import os
import hashlib
from datetime import date

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
CALLMEBOT_PHONE   = os.environ["CALLMEBOT_PHONE"]
CALLMEBOT_APIKEY  = os.environ["CALLMEBOT_APIKEY"]
HASH_FILE         = "last_hash.txt"

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
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=800,
        messages=[{
            "role": "user",
            "content": (
                f"Eres un asistente jurídico. A continuación está el estado diario del "
                f"TDLC (Tribunal de Defensa de la Libre Competencia de Chile) del {date.today().strftime('%d/%m/%Y')}.\n\n"
                f"Haz un resumen claro y conciso de las causas, resoluciones o actuaciones publicadas. "
                f"Usa viñetas. Máximo 300 palabras.\n\nCONTENIDO:\n{raw_text[:6000]}"
            )
        }]
    )
    return msg.content[0].text

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
