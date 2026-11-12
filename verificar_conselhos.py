"""Confere se os links de conselhos.json abrem. Grava conselhos_status.json.

Regras (mesma ideia dos outros robôs: nunca afirmar o que não se sabe):
  - abriu (2xx/3xx)                          -> 'ok'
  - 404/410, site fora (5xx), DNS, recusou   -> falha 'dura'
  - 403/429, timeout, erro de SSL/robots      -> 'incerto' (pode ser só bloqueio ao robô)
  - uma falha dura vira 'fora' só depois de 3 execuções seguidas; antes disso fica 'incerto'.
Um site que bloqueia robôs nunca é marcado 'fora': aparece como 'não deu para verificar'.
O robô não altera conselhos.json; só informa. Sai com código 0 mesmo havendo links fora.
"""
import json, os, sys, datetime, concurrent.futures as cf
import requests

SEGUIDAS_PARA_FORA = 3
UA = "Mozilla/5.0 (compatible; NuConsultaVerificador/1.0; +link-check)"
ARQ_DADOS, ARQ_STATUS = "conselhos.json", "conselhos_status.json"


def coletar(dados):
    urls = set()
    for p in dados.get("profissoes", []):
        for k in ("principal", "plano_b", "site"):
            if p.get(k): urls.add(p[k])
    for grupo in dados.get("regionais", {}).values():
        for r in grupo:
            for k in ("consulta", "site"):
                if r.get(k): urls.add(r[k])
    return sorted(urls)


def testar(url):
    """Devolve (classe, codigo|motivo): ok | dura | incerta."""
    ultimo = ("incerta", "sem resposta")
    for tentativa in range(2):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=20, allow_redirects=True, stream=True)
            r.close()
            c = r.status_code
            if c < 400: return ("ok", c)
            if c in (404, 410) or c >= 500: ultimo = ("dura", c)
            elif c in (401, 403, 429): ultimo = ("incerta", c)
            else: ultimo = ("dura", c)
        except requests.exceptions.SSLError:
            ultimo = ("incerta", "ssl")
        except requests.exceptions.Timeout:
            ultimo = ("incerta", "timeout")
        except requests.exceptions.ConnectionError as e:
            txt = str(e).lower()
            ultimo = ("dura", "dns") if ("name or service" in txt or "nodename" in txt or "resolve" in txt) else ("incerta", "conexao")
        except Exception as e:
            ultimo = ("incerta", type(e).__name__)
    return ultimo


def main():
    with open(ARQ_DADOS, encoding="utf-8") as f: dados = json.load(f)
    try:
        with open(ARQ_STATUS, encoding="utf-8") as f: antes = json.load(f).get("links", {})
    except Exception:
        antes = {}
    urls = coletar(dados)
    hoje = datetime.date.today().isoformat()
    novo = {}
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for url, (cl, cod) in zip(urls, ex.map(testar, urls)):
            a = antes.get(url, {})
            if cl == "ok":
                novo[url] = {"estado": "ok", "codigo": cod, "falhas_seguidas": 0, "verificado_em": hoje, "ultimo_ok": hoje}
            else:
                n = a.get("falhas_seguidas", 0) + 1
                estado = "fora" if (cl == "dura" and n >= SEGUIDAS_PARA_FORA) else "incerto"
                novo[url] = {"estado": estado, "codigo": cod, "falhas_seguidas": n, "verificado_em": hoje,
                             "ultimo_ok": a.get("ultimo_ok", "")}
    cont = {e: sum(1 for v in novo.values() if v["estado"] == e) for e in ("ok", "incerto", "fora")}
    # segurança: se quase tudo falhou, o problema é o robô/a rede, não os sites
    if urls and cont["ok"] == 0:
        print("Nenhum link abriu: provável falha do robô/rede. Não gravo o status."); sys.exit(1)
    with open(ARQ_STATUS, "w", encoding="utf-8") as f:
        json.dump({"gerado_em": hoje, "resumo": cont, "links": novo}, f, ensure_ascii=False, indent=1)
    print(f"{len(urls)} links: {cont}")
    fora = [u for u, v in novo.items() if v["estado"] == "fora"]
    resumo = os.environ.get("GITHUB_STEP_SUMMARY")
    if resumo:
        with open(resumo, "a", encoding="utf-8") as f:
            f.write(f"### Links de conselhos: {cont['ok']} no ar, {cont['incerto']} sem verificação, {cont['fora']} fora\n")
            for u in fora: f.write(f"- fora do ar: {u} ({novo[u]['codigo']})\n")
    saida = os.environ.get("GITHUB_OUTPUT")
    if saida:
        with open(saida, "a") as f: f.write(f"fora={'sim' if fora else 'nao'}\nqtd_fora={len(fora)}\n")


if __name__ == "__main__":
    main()
