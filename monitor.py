import os
import re
import hashlib
import time
import json
import requests
import datetime as dt
import pdfplumber
import subprocess
from playwright.sync_api import sync_playwright

HASH_FILE      = "last_hash.txt"
PAGE_HASH_FILE = "last_page_hash.txt"
URL_BASE       = "https://consultas.tdlc.cl"

# ── Fecha de hoy en Chile (UTC-4) ─────────────────────────────────────────────
hoy_chile = dt.datetime.now() - dt.timedelta(hours=4)
HOY_MS = int(dt.datetime(hoy_chile.year, hoy_chile.month, hoy_chile.day,
             tzinfo=dt.timezone.utc).timestamp() * 1000)

# ── Hash de página ────────────────────────────────────────────────────────────
def load_page_hash():
    if os.path.exists(PAGE_HASH_FILE):
        with open(PAGE_HASH_FILE) as f:
            return f.read().strip()
    return ""

def save_page_hash(h):
    with open(PAGE_HASH_FILE, "w") as f:
        f.write(h)

def push_page_hash():
    try:
        subprocess.run(["git", "config", "user.name", "tdlc-bot"], check=True)
        subprocess.run(["git", "config", "user.email", "bot@tdlc"], check=True)
        subprocess.run(["git", "add", PAGE_HASH_FILE], check=True)
        result = subprocess.run(["git", "diff", "--cached", "--quiet"])
        if result.returncode != 0:
            subprocess.run(["git", "commit", "-m", "update page hash"], check=True)
            subprocess.run(["git", "push", "origin", "main"], check=True)
            print("✅ Hash de página guardado en repo")
    except Exception as e:
        print(f"⚠️ No se pudo guardar hash de página: {e}")

# ── Descarga PDF con cookies de Playwright ────────────────────────────────────
def descargar_pdf(cookies_dict, url_pdf):
    session = requests.Session()
    for name, value in cookies_dict.items():
        session.cookies.set(name, value)
    session.headers.update({"User-Agent": "Mozilla/5.0", "Referer": URL_BASE})
    try:
        resp = session.get(url_pdf, timeout=30)
        if resp.status_code == 200 and resp.content[:4] == b'%PDF':
            with open("temp_resolucion.pdf", "wb") as f:
                f.write(resp.content)
            texto = ""
            with pdfplumber.open("temp_resolucion.pdf") as pdf:
                for p in pdf.pages:
                    t = p.extract_text()
                    if t:
                        texto += t + "\n"
            return texto.strip()
        return None
    except Exception as e:
        print(f"  Error descargando PDF: {e}")
        return None

# ── Limpieza de texto extraído del PDF ───────────────────────────────────────
def limpiar_contenido(texto):
    """Elimina encabezados de página y bloque de firma electrónica del PDF."""

    # Eliminar número de página + encabezado institucional
    texto = re.sub(
        r'\n\d+\s*\n[^\n]*(?:REP[ÚU\s]{0,2}BLICA|REPÚBLICA|REPUBLICA)\s+DE\s+CHILE[^\n]*\n'
        r'TRIBUNAL DE DEFENSA DE LA LIBRE COMPETENCIA\n',
        '\n',
        texto
    )

    # Eliminar bloque de firma electrónica
    texto = re.sub(
        r'\s*Autorizada por la Secretaria Abogada\(S\),.*?'
        r'verificación indicado bajo el código de barras\.',
        '',
        texto,
        flags=re.DOTALL
    )

    # Colapsar líneas en blanco excesivas
    texto = re.sub(r'\n{3,}', '\n\n', texto)

    return texto.strip()

# ── Extraer idCuaderno desde URLs capturadas ──────────────────────────────────
def extraer_ids_cuadernos(lista_urls):
    ids = []
    for u in lista_urls:
        partes = u.split("/")
        if "bloqueadossummary" in partes:
            idx = partes.index("bloqueadossummary")
            if idx + 1 < len(partes):
                id_c = partes[idx + 1].split("?")[0]  # quitar query string si lo hay
                if id_c and id_c not in ids:
                    ids.append(id_c)
    return ids

# ── Scraping principal ────────────────────────────────────────────────────────
def fetch_tdlc():
    resultados  = []
    causas_hash = None

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()
        page    = context.new_page()

        # ── Paso 1: abrir modal y leer lista de causas ────────────────────
        page.goto(f"{URL_BASE}/estadoDiario", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(5000)

        try:
            detalle_icon = page.wait_for_selector(".glyphicon-new-window", timeout=15000)
            detalle_icon.click()
            page.wait_for_timeout(4000)
            print("✅ Modal abierto")
        except Exception as e:
            print(f"Error abriendo modal: {e}")
            browser.close()
            return [], None

        filas  = page.query_selector_all("#showDetalle tbody tr")
        causas = []
        for fila in filas:
            celdas = fila.query_selector_all("td")
            if len(celdas) >= 2:
                causas.append({
                    "rol":      celdas[0].inner_text().strip(),
                    "caratula": celdas[1].inner_text().strip()
                })
        print(f"✅ {len(causas)} causas en el estado diario de hoy")

        # ── Paso 2: calcular hash de la lista y comparar ──────────────────
        causas_hash = hashlib.md5(
            json.dumps(causas, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()

        if causas_hash == load_page_hash():
            print("📄 Lista de causas sin cambios. Nada que hacer.")
            browser.close()
            return [], causas_hash

        # Guardar y pushear hash inmediatamente antes del scraping completo
        save_page_hash(causas_hash)
        push_page_hash()
        print("🔄 Lista de causas cambió, entrando a cada causa...")

        # ── Paso 3: scraping completo ─────────────────────────────────────
        for i, causa in enumerate(causas):
            print(f"\n📂 [{i+1}/{len(causas)}] {causa['rol']}")

            # Reabrir modal para obtener idCausa
            page.goto(f"{URL_BASE}/estadoDiario", wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(5000)
            iconos = page.query_selector_all(".glyphicon-new-window")
            iconos[0].click()
            page.wait_for_timeout(4000)

            spans_causa = page.query_selector_all("#showDetalle tbody tr td span.glyphicon-new-window")
            if i >= len(spans_causa):
                continue

            # Abrir página de la causa
            with context.expect_page() as nueva_page_info:
                spans_causa[i].click()
            nueva_page = nueva_page_info.value
            nueva_page.wait_for_load_state("networkidle", timeout=30000)
            nueva_page.wait_for_timeout(8000)

            url_causa = nueva_page.url
            id_causa  = url_causa.split("idCausa=")[-1].split("&")[0] if "idCausa=" in url_causa else None
            print(f"  idCausa: {id_causa}")

            # ── Recargar y capturar cuadernos ─────────────────────────────
            requests_capturados = []

            def capturar_request(request):
                if "bloqueadossummary" in request.url:
                    requests_capturados.append(request.url)

            nueva_page.on("request", capturar_request)
            nueva_page.reload(wait_until="networkidle", timeout=30000)
            nueva_page.wait_for_timeout(10000)

            # IDs capturados en la carga inicial (cuaderno activo por defecto)
            ids_cuadernos_vistos = set(extraer_ids_cuadernos(requests_capturados))

            # ── Buscar pestañas de cuadernos adicionales y hacer click ────
            # El TDLC usa AngularJS; los selectores cubren los patrones más comunes.
            # Si ninguno matchea, agregar print(nueva_page.content()) para inspeccionar.
            pestanas = nueva_page.query_selector_all(
                "ul.nav-tabs li a, "
                "[ng-click*='Cuaderno'], "
                "[ng-click*='cuaderno'], "
                "li.cuaderno a, "
                ".cuadernos-tab, "
                "[data-cuaderno]"
            )
            print(f"  Pestañas de cuadernos encontradas: {len(pestanas)}")

            for pestana in pestanas:
                requests_capturados.clear()
                try:
                    nombre_tab = pestana.inner_text().strip()
                    pestana.click()
                    nueva_page.wait_for_timeout(4000)
                    nuevos = extraer_ids_cuadernos(requests_capturados)
                    for id_c in nuevos:
                        if id_c not in ids_cuadernos_vistos:
                            print(f"  + Cuaderno detectado vía pestaña '{nombre_tab}': {id_c}")
                            ids_cuadernos_vistos.add(id_c)
                except Exception as e:
                    print(f"  ⚠️ Error al hacer click en pestaña: {e}")
                    continue

            ids_cuadernos = list(ids_cuadernos_vistos)
            print(f"  idCuadernos totales: {ids_cuadernos}")

            if not ids_cuadernos:
                print("  ⚠️ No se detectó ningún cuaderno, saltando causa.")
                nueva_page.close()
                continue

            # Obtener cookies para descargar PDFs
            cookies_dict = {c["name"]: c["value"] for c in context.cookies()}

            # ── Consultar API de trámites para cada cuaderno ──────────────
            for id_cuaderno in ids_cuadernos:
                print(f"\n  📒 Consultando cuaderno: {id_cuaderno}")

                resp_raw = nueva_page.evaluate(f"""() => {{
                    var xhr = new XMLHttpRequest();
                    xhr.open('GET', '{URL_BASE}/rest/tramite/bloqueadossummary/{id_cuaderno}/10000/1/true/false', false);
                    xhr.setRequestHeader('Accept', 'application/json');
                    xhr.send();
                    return xhr.responseText;
                }}""")

                try:
                    data     = json.loads(resp_raw)
                    tramites = data.get("results", data) if isinstance(data, dict) else data
                except Exception:
                    print(f"  ❌ Error JSON en cuaderno {id_cuaderno}")
                    continue

                # Intentar obtener el nombre del cuaderno desde la respuesta
                nombre_cuaderno = None
                if isinstance(data, dict):
                    nombre_cuaderno = (
                        data.get("nombreCuaderno")
                        or data.get("nombre")
                        or data.get("tipoCuaderno")
                    )
                if not nombre_cuaderno:
                    nombre_cuaderno = f"Cuaderno {id_cuaderno}"

                # Filtrar resoluciones de hoy
                resoluciones_hoy = [
                    t for t in tramites
                    if isinstance(t, dict)
                    and t.get("tipoTramite") == "Resolución"
                    and t.get("fecha", 0) >= HOY_MS
                ]
                print(f"  [{nombre_cuaderno}] Resoluciones de hoy: {len(resoluciones_hoy)}")

                # Descargar PDF de cada resolución
                for tramite in resoluciones_hoy:
                    id_enc     = tramite.get("idDocumentoEncriptado")
                    referencia = tramite.get("referencia", "sin referencia")
                    fecha_dt   = dt.datetime.fromtimestamp(tramite.get("fecha", 0) / 1000)
                    print(f"  📄 {referencia} | {fecha_dt} | {nombre_cuaderno}")

                    if not id_enc:
                        continue

                    url_pdf = f"{URL_BASE}/download/{id_enc}?inlineifpossible=true"
                    texto   = descargar_pdf(cookies_dict, url_pdf)

                    if texto:
                        print(f"  ✅ PDF extraído ({len(texto)} chars)")
                        resultados.append({
                            "rol":        causa["rol"],
                            "caratula":   causa["caratula"],
                            "cuaderno":   nombre_cuaderno,
                            "referencia": referencia,
                            "fecha":      fecha_dt.strftime("%d/%m/%Y %H:%M"),
                            "contenido":  texto
                        })
                    else:
                        print(f"  ⚠️ No se pudo descargar PDF")

            nueva_page.close()

        browser.close()

    return resultados, causas_hash

# ── Formatear mensaje (Telegram) ──────────────────────────────────────────────
def formatear_mensaje(resultados):
    hoy = hoy_chile.strftime("%d/%m/%Y")
    if not resultados:
        return f"📋 TDLC Estado Diario {hoy}\n\nNo se encontraron resoluciones nuevas hoy."

    msg  = f"📋 TDLC — Estado Diario {hoy}\n"
    msg += f"{'='*50}\n\n"
    msg += f"Se encontraron {len(resultados)} resolución(es):\n\n"

    for r in resultados:
        msg += f"{'─'*50}\n"
        msg += f"📁 {r['rol']}\n"
        msg += f"📌 {r['caratula']}\n"
        msg += f"📒 {r.get('cuaderno', 'Cuaderno Principal')}\n"
        msg += f"⚖️  {r['referencia']}\n"
        msg += f"🕐 {r['fecha']}\n\n"

    msg += f"🔗 {URL_BASE}/estadoDiario"
    return msg

# ── Telegram ──────────────────────────────────────────────────────────────────
def send_telegram(message):
    max_chars = 4000
    partes    = []
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
            "text":    encabezado + parte
        })
        print(f"Telegram parte {i+1}/{total} enviada")
        time.sleep(1)

# ── Email con TXT adjunto ─────────────────────────────────────────────────────
def send_email(message, resultados):
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from email.mime.base import MIMEBase
    from email import encoders

    destinatarios = os.environ["EMAIL_TO"].split(",")
    hoy           = hoy_chile.strftime("%d/%m/%Y")
    ancho         = 70
    linea_gruesa  = "═" * ancho
    linea_delgada = "─" * ancho

    msg            = MIMEMultipart()
    msg["From"]    = os.environ["EMAIL_FROM"]
    msg["To"]      = ", ".join(destinatarios)
    msg["Subject"] = f"TDLC Estado Diario {hoy} — {len(resultados)} resolución(es)"
    msg.attach(MIMEText(message, "plain", "utf-8"))

    if resultados:

        # ── Encabezado ────────────────────────────────────────────────────
        txt  = f"{linea_gruesa}\n"
        txt += f"  ESTADO DIARIO TDLC — {hoy}\n"
        txt += f"  {len(resultados)} resolución(es)\n"
        txt += f"{linea_gruesa}\n\n"

        # ── Índice rápido ─────────────────────────────────────────────────
        txt += "ÍNDICE\n"
        txt += f"{linea_delgada}\n"
        for i, r in enumerate(resultados, 1):
            cuaderno_label = r.get("cuaderno", "Principal")
            txt += f"  {i:>2}. [{r['rol']}]  {r['referencia']}  — {cuaderno_label}\n"
            txt += f"      {r['caratula']}\n"
        txt += f"\n{linea_gruesa}\n\n"

        # ── Resoluciones ──────────────────────────────────────────────────
        for i, r in enumerate(resultados, 1):
            contenido_limpio = limpiar_contenido(r["contenido"])
            cuaderno_label   = r.get("cuaderno", "Principal")

            txt += f"RESOLUCIÓN {i} DE {len(resultados)}\n"
            txt += f"{linea_delgada}\n"
            txt += f"  Causa:      {r['rol']}\n"
            txt += f"  Carátula:   {r['caratula']}\n"
            txt += f"  Cuaderno:   {cuaderno_label}\n"
            txt += f"  Resolución: {r['referencia']}\n"
            txt += f"  Fecha:      {r['fecha']}\n"
            txt += f"{linea_delgada}\n\n"

            # Indentar el cuerpo de la resolución
            for linea in contenido_limpio.splitlines():
                txt += f"  {linea}\n" if linea.strip() else "\n"

            txt += f"\n{linea_gruesa}\n\n"

        adjunto = MIMEBase("application", "octet-stream")
        adjunto.set_payload(txt.encode("utf-8"))
        encoders.encode_base64(adjunto)
        adjunto.add_header(
            "Content-Disposition",
            f"attachment; filename=resoluciones_tdlc_{hoy_chile.strftime('%Y-%m-%d')}.txt"
        )
        msg.attach(adjunto)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(os.environ["EMAIL_FROM"], os.environ["GMAIL_PASSWORD"])
        server.sendmail(os.environ["EMAIL_FROM"], destinatarios, msg.as_string())
    print(f"Email enviado a {len(destinatarios)} destinatario(s)")

# ── Hash de resultados ────────────────────────────────────────────────────────
def get_hash(resultados):
    contenido = json.dumps(
        [{k: v for k, v in r.items() if k != "contenido"} for r in resultados],
        ensure_ascii=False, sort_keys=True
    )
    return hashlib.md5(contenido.encode()).hexdigest()

def load_last_hash():
    if os.path.exists(HASH_FILE):
        with open(HASH_FILE) as f:
            return f.read().strip()
    return ""

def save_hash(h):
    with open(HASH_FILE, "w") as f:
        f.write(h)

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Verificando TDLC — {hoy_chile.strftime('%d/%m/%Y %H:%M')}...")

    resultados, causas_hash = fetch_tdlc()

    if not resultados:
        print("Sin resoluciones nuevas hoy.")
    else:
        current_hash = get_hash(resultados)
        if current_hash == load_last_hash():
            print("Sin cambios desde la última ejecución.")
        else:
            print(f"¡{len(resultados)} resolución(es) nueva(s)! Enviando notificaciones...")
            mensaje = formatear_mensaje(resultados)
            send_telegram(mensaje)
            send_email(mensaje, resultados)
            save_hash(current_hash)
            print("✅ Listo.")
