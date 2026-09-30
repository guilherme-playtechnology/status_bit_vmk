#!/usr/bin/env python3
"""
Baixa o relatório "Status da Licença" pela API pública do GravityZone,
mantém só as colunas Nome da Empresa e Uso e grava o dados.csv.

Variáveis de ambiente:
  GZ_API_KEY      (obrigatória) chave de API do GravityZone  -> Secret do GitHub
  GZ_API_URL      endereço de acesso da API (padrão: https://cloud.gravityzone.bitdefender.com/api)
  GZ_REPORT_ID    ID do relatório agendado (opcional; se vazio, procura pelo nome)
  GZ_REPORT_NAME  nome do relatório agendado no GravityZone
  SAIDA           caminho do arquivo gerado (padrão: dados.csv)

Segurança: o script nunca imprime o conteúdo do relatório original,
porque ele traz as chaves de licença e o log do Actions é público.
"""
import base64, csv, io, json, os, re, sys, urllib.request, zipfile

API_KEY = os.environ.get("GZ_API_KEY", "").strip()
API_URL = (os.environ.get("GZ_API_URL") or "https://cloud.gravityzone.bitdefender.com/api").strip().rstrip("/")
REPORT_ID = os.environ.get("GZ_REPORT_ID", "").strip()
REPORT_NAME = os.environ.get("GZ_REPORT_NAME", "").strip()
SAIDA = os.environ.get("SAIDA", "dados.csv")

AUTH = "Basic " + base64.b64encode((API_KEY + ":").encode()).decode()


def falha(msg):
    print("ERRO:", msg)
    sys.exit(1)


def rpc(servico, metodo, params):
    corpo = json.dumps({"jsonrpc": "2.0", "method": metodo, "params": params, "id": "gh-action"}).encode()
    req = urllib.request.Request(f"{API_URL}/v1.0/jsonrpc/{servico}", data=corpo,
                                 headers={"Content-Type": "application/json", "Authorization": AUTH})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.load(r)
    except urllib.error.HTTPError as e:
        falha(f"{servico}.{metodo} respondeu HTTP {e.code}. Confira a chave de API e o GZ_API_URL.")
    if resp.get("error"):
        err = resp["error"]
        falha(f"{servico}.{metodo}: {err.get('message')} {err.get('data', '')}")
    return resp.get("result")


def achar_relatorio():
    itens, pagina = [], 1
    while True:
        res = rpc("reports", "getReportsList", {"page": pagina, "perPage": 100}) or {}
        itens += res.get("items", [])
        if pagina >= res.get("pagesCount", 1):
            break
        pagina += 1
    print(f"Relatórios agendados encontrados: {len(itens)}")
    for it in itens:
        print(f"  - {it.get('name')}  (id {it.get('id')}, tipo {it.get('type')})")
    if not REPORT_NAME:
        falha("Defina GZ_REPORT_NAME ou GZ_REPORT_ID com um dos relatórios acima.")
    alvo = [it for it in itens if (it.get("name") or "").strip().lower() == REPORT_NAME.lower()]
    if not alvo:
        falha(f'Nenhum relatório com o nome "{REPORT_NAME}". Use um dos nomes listados acima.')
    return alvo[0]["id"]


def baixar(url):
    req = urllib.request.Request(url, headers={"Authorization": AUTH})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def extrair_csv(conteudo):
    if conteudo[:2] == b"PK":  # arquivo zip
        with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
            nomes = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if not nomes:
                falha("O zip do relatório não tem nenhum arquivo .csv. O relatório precisa estar em formato CSV.")
            conteudo = z.read(nomes[0])
    for cod in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return conteudo.decode(cod)
        except UnicodeDecodeError:
            pass


def normalizar(s):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn").strip()


def transformar(texto):
    primeira = texto.splitlines()[0] if texto else ""
    sep = ";" if primeira.count(";") > primeira.count(",") else ","
    linhas = list(csv.reader(io.StringIO(texto), delimiter=sep))
    cab = [normalizar(c) for c in linhas[0]]
    col = lambda *ks: next((i for i, c in enumerate(cab) if any(k in c for k in ks)), -1)
    i_nome, i_uso = col("empresa", "company"), col("uso", "usage")
    if i_nome < 0 or i_uso < 0:
        falha(f"Colunas Nome da Empresa / Uso não encontradas. Cabeçalho recebido: {linhas[0]}")
    saida = []
    for r in linhas[1:]:
        if len(r) <= max(i_nome, i_uso) or not r[i_nome].strip():
            continue
        uso = r[i_uso].strip()
        if not re.fullmatch(r"\d+\s*/\s*\d+", uso):
            falha(f'Valor de uso inesperado na unidade "{r[i_nome].strip()}".')
        saida.append((r[i_nome].strip(), uso))
    if not saida:
        falha("O relatório veio sem nenhuma unidade. O dados.csv atual foi mantido.")
    return saida


def main():
    if not API_KEY:
        falha("Secret GZ_API_KEY não configurado.")
    rid = REPORT_ID or achar_relatorio()
    links = rpc("reports", "getDownloadLinks", {"reportId": rid}) or {}
    if not links.get("readyForDownload") or not links.get("lastInstanceUrl"):
        falha("O relatório ainda não tem uma execução pronta para download.")
    linhas = transformar(extrair_csv(baixar(links["lastInstanceUrl"])))
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(["Nome da Empresa", "Uso"])
    w.writerows(linhas)
    with open(SAIDA, "w", encoding="utf-8-sig", newline="") as f:
        f.write(buf.getvalue())
    em = sum(int(u.split("/")[0]) for _, u in linhas)
    tot = sum(int(u.split("/")[1]) for _, u in linhas)
    print(f"dados.csv gerado: {len(linhas)} unidades, {em}/{tot} endpoints em uso.")


if __name__ == "__main__":
    main()
