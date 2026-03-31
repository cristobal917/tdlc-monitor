import requests

cookies = "JSESSIONID=4jkw7aGoonriUgIm7sYSlX0n; 5d92dbde16f2293987bf14d26bddee86=f8f71c34052e09662914c0baa3ccd00d"
headers = {
    "User-Agent": "Mozilla/5.0",
    "Cookie": cookies,
    "Referer": "https://consultas.tdlc.cl/estadoDiario",
    "X-Requested-With": "XMLHttpRequest"
}
r = requests.get("https://consultas.tdlc.cl/rest/causa/byestadodiario/54133", headers=headers)
print("Status:", r.status_code)
print("Response:", r.text[:1000])
