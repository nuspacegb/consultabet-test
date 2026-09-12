#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
 NU - CONSULTA  |  Instituicoes de Pagamento autorizadas pelo BCB
=============================================================================

  Servico: BcBase v2       Recurso: EntidadesSupervisionadas
  Portal:  https://dadosabertos.bcb.gov.br/dataset/dados-cadastrais-de-entidades-autorizadas

O QUE APRENDEMOS NA PRIMEIRA EXECUCAO
-------------------------------------
  Chamada SEM dataBase  -> HTTP 400 "The URI is malformed"
      A API recusa a URL. O parametro e obrigatorio.

  Chamada COM (dataBase=@dataBase) -> HTTP 500 "Erro desconhecido"
      A URL foi ACEITA -- o formato da chamada esta certo. O servidor
      engasgou no valor, ou faltou algum outro parametro obrigatorio.

Ou seja: nao adianta continuar chutando formato de data. Este script agora
pergunta para a propria API quais recursos existem e quais parametros cada um
exige, usando o catalogo OData ($metadata). So depois disso ele tenta.

MODOS
-----
    python scraper_ips.py --explorar
        Mostra o catalogo da API, os parametros exigidos e testa as chamadas.
        Nao salva nada. Use este primeiro.

    python scraper_ips.py --url "<URL completa>"
        Usa exatamente a URL que voce passar, sem tentar adivinhar.
        Serve para quando ja se sabe a chamada certa.

    python scraper_ips.py
        Modo normal: busca, valida e salva ips.json e historico_ips.json.

=============================================================================
"""

import argparse
import json
import os
import re
import socket
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import requests


def forcar_ipv4():
    """Os servidores do GitHub so tem rede IPv4."""
    try:
        import urllib3.util.connection as conexao
        conexao.allowed_gai_family = lambda: socket.AF_INET
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  AVISO: nao consegui forcar IPv4 ({e}).")
        return False


# ----------------------------------------------------------------------------
# CONFIGURACAO
# ----------------------------------------------------------------------------

SERVICO = "https://olinda.bcb.gov.br/olinda/servico/BcBase/versao/v2/odata"
RECURSO = "EntidadesSupervisionadas"
BASE = f"{SERVICO}/{RECURSO}"

FONTE_HUMANA = ("https://dadosabertos.bcb.gov.br/dataset/"
                "dados-cadastrais-de-entidades-autorizadas")

TERMO_TIPO_IP = "instituicao de pagamento"

MINIMO_IPS = 120
QUEDA_MAXIMA_ACEITAVEL = 0.30

ARQUIVO_DADOS = "ips.json"
ARQUIVO_HISTORICO = "historico_ips.json"

CABECALHO_HTTP = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/json",
    "Accept-Language": "pt-BR,pt;q=0.9",
}

TIMEOUT = (12, 90)
FUSO_BRASILIA = timezone(timedelta(hours=-3))


# ----------------------------------------------------------------------------
# UTILITARIOS
# ----------------------------------------------------------------------------

def log(msg=""):
    print(msg, flush=True)


def titulo(txt):
    log()
    log("-" * 70)
    log(f"  {txt}")
    log("-" * 70)


def avisar_workflow(**campos):
    destino = os.getenv("GITHUB_OUTPUT")
    if not destino:
        return
    try:
        with open(destino, "a", encoding="utf-8") as f:
            for c, v in campos.items():
                f.write(f"{c}={v}\n")
    except Exception:  # noqa: BLE001
        pass


def morrer(msg, transitorio=False):
    log()
    log("=" * 70)
    log("  SEM ATUALIZACAO - NADA FOI SALVO" if transitorio
        else "  ABORTADO - NADA FOI SALVO")
    log("=" * 70)
    log(f"  Motivo: {msg}")
    log()
    log("  A base que ja esta no ar continua intacta.")
    log("=" * 70)
    avisar_workflow(resultado="sem_acesso" if transitorio else "erro")
    sys.exit(0 if transitorio else 1)


def sem_acento(texto):
    nfkd = unicodedata.normalize("NFKD", str(texto or ""))
    limpo = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", limpo).strip().lower()


def formatar_cnpj(bruto):
    """A API devolve o CNPJ como numero, perdendo zeros da frente."""
    digitos = re.sub(r"\D", "", str(bruto or ""))
    if not digitos:
        return None
    digitos = digitos.zfill(14)
    if len(digitos) != 14:
        return None
    return f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:]}"


# ----------------------------------------------------------------------------
# CONVERSA COM A API
# ----------------------------------------------------------------------------

def pedir(url, tentativas=2):
    """
    Faz a chamada. Devolve (registros, erro_legivel).
    Um dos dois vem preenchido, nunca os dois.
    """
    ultimo = None
    for n in range(1, tentativas + 1):
        try:
            r = requests.get(url, headers=CABECALHO_HTTP, timeout=TIMEOUT)
            if r.status_code != 200:
                resumo = re.sub(r"\s+", " ", r.text[:150]).strip()
                return None, f"HTTP {r.status_code} — {resumo}"
            try:
                dados = r.json()
            except Exception:  # noqa: BLE001
                return None, f"resposta nao era JSON — {r.text[:120]}"
            registros = dados.get("value", dados if isinstance(dados, list) else [])
            if not registros:
                return None, "resposta vazia (0 registros)"
            return registros, None
        except Exception as e:  # noqa: BLE001
            ultimo = f"erro de rede: {str(e)[:140]}"
            if n < tentativas:
                time.sleep(3)
    return None, ultimo


def texto_cru(url):
    """Baixa como texto puro. Usado para o catalogo e o $metadata."""
    try:
        r = requests.get(url, headers={**CABECALHO_HTTP, "Accept": "*/*"},
                         timeout=TIMEOUT)
        return r.status_code, r.text
    except Exception as e:  # noqa: BLE001
        return None, str(e)


# ----------------------------------------------------------------------------
# O CATALOGO DA API
# ----------------------------------------------------------------------------

def mostrar_catalogo():
    """
    Pergunta para a API quais recursos ela tem e quais parametros exige.

    Toda API OData publica dois documentos de auto-descricao:
      /odata/           -> a lista de recursos disponiveis
      /odata/$metadata  -> o esquema completo, com os parametros de cada um

    E ali que esta a resposta para o erro 500: ou o parametro tem outro nome,
    ou o recurso exige mais de um parametro e a gente so mandou um.
    """
    titulo("CATALOGO: quais recursos esta API oferece")
    status, corpo = texto_cru(f"{SERVICO}/")
    log(f"  GET {SERVICO}/   ->  HTTP {status}")
    if corpo:
        for linha in corpo[:2500].splitlines():
            if linha.strip():
                log(f"  {linha[:160]}")
    log()

    titulo("ESQUEMA ($metadata): parametros que cada recurso exige")
    status, corpo = texto_cru(f"{SERVICO}/$metadata")
    log(f"  GET {SERVICO}/$metadata   ->  HTTP {status}")
    log()

    if not corpo or status != 200:
        log("  Nao consegui ler o esquema.")
        return []

    # O $metadata e um XML grande. Mostra so o que interessa: nomes de
    # recursos, de funcoes e os parametros de cada uma.
    interessantes = ("EntitySet", "FunctionImport", "Parameter",
                     "EntityType Name", "Function Name", "Action Name")
    linhas = [l.strip() for l in corpo.replace("><", ">\n<").splitlines()]
    mostradas = 0
    for l in linhas:
        if any(chave in l for chave in interessantes):
            log(f"  {l[:180]}")
            mostradas += 1
            if mostradas >= 160:
                log("  ... (cortado)")
                break
    if not mostradas:
        log("  Nenhuma linha reconhecivel. Comeco do documento:")
        log(f"  {corpo[:1200]}")

    # Tenta descobrir sozinho os parametros do nosso recurso
    parametros = sorted(set(re.findall(
        r'<Parameter\s+Name="([^"]+)"', corpo)))
    if parametros:
        log()
        log(f"  Parametros encontrados no esquema: {', '.join(parametros)}")
    return parametros


# ----------------------------------------------------------------------------
# AS TENTATIVAS
# ----------------------------------------------------------------------------

def formatos_de_data(data):
    """Varias grafias da mesma data, porque o 500 pode ser so isso."""
    a, m, d = data.split("-")
    return [
        (f"'{a}-{m}-{d}'", f"'{data}'"),
        (f"{a}-{m}-{d} sem aspas", data),
        (f"'{d}/{m}/{a}'", f"'{d}/{m}/{a}'"),
        (f"'{a}{m}{d}'", f"'{a}{m}{d}'"),
        (f"'{a}-{m}'", f"'{a}-{m}'"),
        (f"'{a}{m}'", f"'{a}{m}'"),
    ]


def datas_provaveis(quantas=6):
    hoje = datetime.now(FUSO_BRASILIA).date()
    datas, ano, mes = [], hoje.year, hoje.month
    for _ in range(quantas):
        datas.append(f"{ano:04d}-{mes:02d}-05")
        mes -= 1
        if mes == 0:
            mes, ano = 12, ano - 1
    return datas


def montar_tentativas(nomes_parametro):
    """
    Gera (rotulo, url). A ordem importa: comeca pelo mais provavel.
    Cada tentativa e barata, mas o total e limitado de proposito.
    """
    tipo = quote("Instituição de Pagamento")
    filtro = f"&$filter=descricaoTipoEntidadeSupervisionada%20eq%20'{tipo}'"
    fim = "&$format=json&$top=5000"

    tentativas = []
    for data in datas_provaveis():
        for rotulo_fmt, valor in formatos_de_data(data):
            for nome in nomes_parametro:
                tentativas.append((
                    f"{nome}={rotulo_fmt} (com filtro de tipo)",
                    f"{BASE}({nome}=@{nome})?@{nome}={valor}{fim}{filtro}",
                ))
                tentativas.append((
                    f"{nome}={rotulo_fmt} (sem filtro)",
                    f"{BASE}({nome}=@{nome})?@{nome}={valor}{fim}",
                ))
    return tentativas


def buscar(nomes_parametro, limite=60):
    titulo("TENTATIVAS DE CHAMADA")
    vistos_erros = {}
    tentativas = montar_tentativas(nomes_parametro)[:limite]
    log(f"  {len(tentativas)} combinacoes a testar")
    log()

    for rotulo, url in tentativas:
        registros, erro = pedir(url)
        if registros:
            log(f"  ✓ FUNCIONOU: {rotulo}")
            log(f"    {len(registros):,} registros")
            log(f"    URL: {url}")
            return registros, rotulo, url
        # agrupa erros iguais para o log nao virar uma parede
        chave = (erro or "")[:60]
        vistos_erros[chave] = vistos_erros.get(chave, 0) + 1
        if vistos_erros[chave] <= 2:
            log(f"  ✗ {rotulo}")
            log(f"    {erro}")

    log()
    log("  Resumo dos erros:")
    for erro, n in sorted(vistos_erros.items(), key=lambda x: -x[1]):
        log(f"    {n:3}x  {erro}")
    return None, None, None


# ----------------------------------------------------------------------------
# TRATAMENTO DOS REGISTROS
# ----------------------------------------------------------------------------

def eh_ip(registro):
    tipo = sem_acento(registro.get("descricaoTipoEntidadeSupervisionada", ""))
    return TERMO_TIPO_IP in tipo


def achar_situacao(registro):
    """
    Procura o campo de situacao sem depender do nome exato.

    A planilha de referencia mostra tres valores possiveis:
        "Autorizada em Atividade"
        "Autorizada sem Atividade"
        "Cancelada/Encerrada"

    Como o nome do campo na API pode ser descricaoSituacao,
    descricaoSituacaoPessoaJuridica ou outro, a busca e por conteudo.
    """
    for chave, valor in registro.items():
        if "situacao" in sem_acento(chave) and isinstance(valor, str) and valor.strip():
            return valor.strip()
    return ""


def classificar(situacao):
    """
    Traduz a situacao em um status que a tela pode usar direto.

    Esta e a parte mais importante deste arquivo. Uma IP com autorizacao
    CANCELADA continua aparecendo na base do BCB -- e mostra-la como
    "consta na lista" seria dar sinal verde para quem o BCB descredenciou.
    """
    s = sem_acento(situacao)
    if "cancelad" in s or "encerrad" in s or "liquidac" in s or "baixad" in s:
        return "cancelada"
    if "autorizada" in s and "sem atividade" in s:
        return "autorizada_sem_atividade"
    if "autorizada" in s:
        return "autorizada"
    return "indefinida"


def normalizar(registro):
    cnpj = formatar_cnpj(registro.get("codigoCNPJ14"))
    if not cnpj:
        return None
    razao = (registro.get("nomeEntidadeInteresse")
             or registro.get("nomeEntidadeInteresseNaoFormatado") or "").strip()
    if not razao:
        return None

    apelidos, vistos = [], set()
    for campo in ("nomeReduzido", "nomeFantasia", "siglaDaPessoaJuridica"):
        valor = (registro.get(campo) or "").strip()
        chave = sem_acento(valor)
        if valor and chave != sem_acento(razao) and chave not in vistos:
            vistos.add(chave)
            apelidos.append(valor)

    situacao = achar_situacao(registro)

    return {
        "cnpj": cnpj,
        "cnpj_raiz": re.sub(r"\D", "", str(registro.get("codigoCNPJ8") or ""))[:8].zfill(8),
        "razao_social": razao,
        "nomes": ", ".join(apelidos),
        "tipo": (registro.get("descricaoTipoEntidadeSupervisionada") or "").strip(),
        "natureza_juridica": (registro.get("descricaoNaturezaJuridica") or "").strip(),
        "situacao": situacao,              # texto original do BCB
        "status": classificar(situacao),   # o que a tela usa para colorir
        "municipio": (registro.get("nomeDoMunicipio") or "").strip(),
        "uf": (registro.get("nomeDaUnidadeFederacao") or "").strip(),
        "data_base": str(registro.get("database") or registro.get("dataBase") or "").strip(),
    }


def limpar(registros):
    saida, vistos = [], set()
    for r in registros:
        item = normalizar(r)
        if item and item["cnpj"] not in vistos:
            vistos.add(item["cnpj"])
            saida.append(item)
    return saida


# ----------------------------------------------------------------------------
# EXPLORACAO
# ----------------------------------------------------------------------------

def explorar(registros, rotulo, url):
    titulo("O QUE VEIO NA RESPOSTA")
    log(f"  Chamada: {rotulo}")
    log(f"  URL:     {url}")
    log(f"  Total:   {len(registros):,} registros")
    log()

    tipos = {}
    for r in registros:
        t = (r.get("descricaoTipoEntidadeSupervisionada") or "(sem tipo)").strip()
        tipos[t] = tipos.get(t, 0) + 1
    log("  Tipos de entidade presentes:")
    for t, n in sorted(tipos.items(), key=lambda x: -x[1])[:30]:
        marca = "   <-- e o que queremos" if TERMO_TIPO_IP in sem_acento(t) else ""
        log(f"    {n:6,}  {t}{marca}")
    log()

    ips = [r for r in registros if eh_ip(r)]
    log(f"  Instituicoes de Pagamento: {len(ips):,}")
    log()

    # A quebra por situacao e o dado mais importante desta exploracao:
    # define quantas das IPs estao de fato autorizadas.
    situacoes = {}
    for r in ips:
        s = achar_situacao(r) or "(sem situacao)"
        situacoes[s] = situacoes.get(s, 0) + 1
    log("  Situacao das IPs (ATENCAO: nem toda IP na base esta autorizada):")
    for s, n in sorted(situacoes.items(), key=lambda x: -x[1]):
        log(f"    {n:6,}  {s:35} -> status: {classificar(s)}")
    log()

    log("  Campos disponiveis em cada registro:")
    for campo in sorted(registros[0].keys()):
        log(f"    {campo:45} = {str(registros[0].get(campo))[:55]}")
    log()

    if ips:
        tratadas = limpar(ips)
        log("  Exemplo ja tratado pelo script:")
        log(json.dumps(tratadas[0], ensure_ascii=False, indent=2))
        log()
        log("  Primeiras 10:")
        for i in tratadas[:10]:
            log(f"    {i['cnpj']}  {i['razao_social'][:55]}")
    log()
    log("=" * 70)
    log("  Mande este log para o Claude.")
    log("=" * 70)


# ----------------------------------------------------------------------------
# GRAVACAO
# ----------------------------------------------------------------------------

def carregar_anterior():
    if not os.path.exists(ARQUIVO_DADOS):
        return []
    try:
        with open(ARQUIVO_DADOS, encoding="utf-8") as f:
            d = json.load(f)
        return d.get("instituicoes", []) if isinstance(d, dict) else d
    except Exception:  # noqa: BLE001
        return []


def rotulo_empresa(e):
    return f"{e['razao_social']} ({e['nomes']})" if e.get("nomes") else e["razao_social"]


def comparar(antes, depois):
    a = {e["cnpj"]: e for e in antes if e.get("cnpj")}
    d = {e["cnpj"]: e for e in depois if e.get("cnpj")}
    return {
        "adicionadas": [rotulo_empresa(d[c]) for c in sorted(set(d) - set(a))],
        "removidas": [rotulo_empresa(a[c]) for c in sorted(set(a) - set(d))],
    }


def salvar(ips, url, agora):
    anterior = carregar_anterior()

    if len(ips) < MINIMO_IPS:
        morrer(f"So encontrei {len(ips)} IPs, e o minimo aceitavel e {MINIMO_IPS}.")
    if anterior:
        queda = (len(anterior) - len(ips)) / len(anterior)
        if queda > QUEDA_MAXIMA_ACEITAVEL:
            morrer(f"A base cairia de {len(anterior)} para {len(ips)} ({queda:.0%}).")

    mudancas = comparar(anterior, ips)
    data_base = next((i["data_base"] for i in ips if i.get("data_base")), "")

    with open(ARQUIVO_DADOS, "w", encoding="utf-8") as f:
        json.dump({
            "meta": {
                "fonte": FONTE_HUMANA,
                "api": url,
                "data_base": data_base,
                "verificado_em": agora.strftime("%d/%m/%Y %H:%M"),
                "verificado_em_iso": agora.isoformat(timespec="seconds"),
                "total": len(ips),
                "escopo": "Apenas Instituições de Pagamento supervisionadas pelo BCB",
            },
            "instituicoes": sorted(ips, key=lambda e: sem_acento(e["razao_social"])),
        }, f, ensure_ascii=False, indent=2)
    log(f"  {ARQUIVO_DADOS} gravado ({len(ips)} IPs, data-base {data_base or '?'})")

    houve = bool(mudancas["adicionadas"] or mudancas["removidas"])
    if houve:
        with open(ARQUIVO_HISTORICO, "w", encoding="utf-8") as f:
            json.dump({
                "data_base": data_base,
                "alterado_em": agora.strftime("%d/%m/%Y %H:%M"),
                "alterado_em_iso": agora.isoformat(timespec="seconds"),
                **mudancas,
                "total_adicionadas": len(mudancas["adicionadas"]),
                "total_removidas": len(mudancas["removidas"]),
            }, f, ensure_ascii=False, indent=2)
        log(f"  {ARQUIVO_HISTORICO} gravado")

    resumo = (f"{len(ips)} IPs | +{len(mudancas['adicionadas'])} / "
              f"-{len(mudancas['removidas'])} | data-base {data_base or '?'}")
    avisar_workflow(resultado="ok", total=len(ips), resumo=resumo,
                    batimento="nao" if houve else "sim", data_base=data_base,
                    adicionadas=len(mudancas["adicionadas"]),
                    removidas=len(mudancas["removidas"]))
    log()
    log("=" * 70)
    log(f"  CONCLUIDO: {resumo}")
    log("=" * 70)


# ----------------------------------------------------------------------------
# PRINCIPAL
# ----------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--explorar", action="store_true",
                   help="mostra o catalogo da API e testa as chamadas, sem salvar")
    p.add_argument("--url", default="",
                   help="usa exatamente esta URL, sem tentar adivinhar")
    args = p.parse_args()

    agora = datetime.now(FUSO_BRASILIA)
    log("=" * 70)
    log("  NU - CONSULTA  |  Instituicoes de Pagamento (BCB)")
    log(f"  Execucao: {agora.strftime('%d/%m/%Y %H:%M')} (horario de Brasilia)")
    log("=" * 70)
    log(f"  IPv4 forcado: {'sim' if forcar_ipv4() else 'nao'}")

    # --- caminho curto: a URL ja e conhecida ---
    if args.url:
        titulo("USANDO A URL INFORMADA")
        log(f"  {args.url}")
        registros, erro = pedir(args.url)
        if not registros:
            morrer(f"A URL informada nao devolveu dados. {erro}",
                   transitorio="rede" in (erro or ""))
        if args.explorar:
            explorar(registros, "URL informada", args.url)
            return
        ips = limpar([r for r in registros if eh_ip(r)])
        log(f"  {len(registros):,} registros -> {len(ips):,} IPs")
        salvar(ips, args.url, agora)
        return

    # --- caminho longo: descobrir ---
    parametros = []
    if args.explorar:
        parametros = mostrar_catalogo()

    # Nomes de parametro a testar: os que o esquema revelou primeiro,
    # depois os palpites de sempre.
    nomes = [n for n in parametros if "data" in n.lower()]
    for palpite in ("dataBase", "DataBase", "database", "data"):
        if palpite not in nomes:
            nomes.append(palpite)

    registros, rotulo, url = buscar(nomes)

    if not registros:
        morrer(
            "Nenhuma combinacao funcionou.\n"
            "  Veja o resumo de erros acima e o esquema da API.\n"
            "  Caminho mais curto: pegar a URL pronta do Apps Script da planilha\n"
            "  e rodar com --url \"<a URL>\".",
        )

    if args.explorar:
        explorar(registros, rotulo, url)
        return

    ips = limpar([r for r in registros if eh_ip(r)])
    log(f"  {len(registros):,} registros -> {len(ips):,} IPs")
    salvar(ips, url, agora)


if __name__ == "__main__":
    main()
