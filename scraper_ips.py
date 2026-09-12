#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
 NU - CONSULTA  |  Instituicoes de Pagamento autorizadas pelo BCB
=============================================================================

O QUE ESTE SCRIPT FAZ
---------------------
Consulta a API publica de Dados Abertos do Banco Central e monta a lista de
Instituicoes de Pagamento autorizadas a funcionar no pais.

  Servico: BcBase v2
  Recurso: EntidadesSupervisionadas
  Portal:  https://dadosabertos.bcb.gov.br/dataset/dados-cadastrais-de-entidades-autorizadas

POR QUE ELE "TENTA VARIAS URLS"
-------------------------------
A API do Olinda aceita mais de um formato de chamada, e a documentacao nao
deixa claro qual deles este recurso exige. Em vez de chutar um e torcer, o
script testa os formatos em ordem, usa o primeiro que devolver dados, e
IMPRIME NO LOG qual funcionou.

Depois que a primeira execucao revelar o formato certo, da para apagar os
outros e deixar so ele -- mas manter todos tambem funciona, e protege contra
o BCB mudar o formato no futuro.

MODO EXPLORACAO
---------------
    python scraper_ips.py --explorar

Nao salva nada. So mostra o que a API devolveu: qual URL funcionou, quantos
registros vieram, quais tipos de entidade existem e como e um registro
completo. Use isto na primeira vez.

MODO NORMAL
-----------
    python scraper_ips.py

Salva ips.json e historico_ips.json, com as mesmas travas de seguranca do
robo das bets: se o resultado nao fizer sentido, aborta sem escrever nada.

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

# ----------------------------------------------------------------------------
# FORCAR IPv4
# ----------------------------------------------------------------------------
# Mesma historia do robo das bets: os servidores do GitHub Actions so tem rede
# IPv4, e tentar IPv6 falha na hora com "Network is unreachable".
# ----------------------------------------------------------------------------

def forcar_ipv4():
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

BASE = ("https://olinda.bcb.gov.br/olinda/servico/BcBase/versao/v2/odata/"
        "EntidadesSupervisionadas")

FONTE_HUMANA = ("https://dadosabertos.bcb.gov.br/dataset/"
                "dados-cadastrais-de-entidades-autorizadas")

# O que conta como Instituicao de Pagamento. A comparacao e feita sem acento
# e em minusculas, entao "Instituição de Pagamento" casa com "instituicao de
# pagamento".
TERMO_TIPO_IP = "instituicao de pagamento"

# --- TRAVAS DE SEGURANCA ---------------------------------------------------
# A planilha de referencia tinha ~214 IPs. 120 e um piso confortavel.
MINIMO_IPS = 120
QUEDA_MAXIMA_ACEITAVEL = 0.30
# ---------------------------------------------------------------------------

ARQUIVO_DADOS = "ips.json"
ARQUIVO_HISTORICO = "historico_ips.json"

CABECALHO_HTTP = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/json",
    "Accept-Language": "pt-BR,pt;q=0.9",
}

TIMEOUT = (12, 90)     # a API pode demorar: o recurso inteiro e grande
FUSO_BRASILIA = timezone(timedelta(hours=-3))


# ----------------------------------------------------------------------------
# UTILITARIOS
# ----------------------------------------------------------------------------

def log(msg=""):
    print(msg, flush=True)


def avisar_workflow(**campos):
    destino = os.getenv("GITHUB_OUTPUT")
    if not destino:
        return
    try:
        with open(destino, "a", encoding="utf-8") as f:
            for chave, valor in campos.items():
                f.write(f"{chave}={valor}\n")
    except Exception:  # noqa: BLE001
        pass


def morrer(msg, transitorio=False):
    """Mesma logica do robo das bets: rede != problema nosso."""
    log()
    log("=" * 70)
    log("  SEM ATUALIZACAO - NADA FOI SALVO" if transitorio
        else "  ABORTADO - NADA FOI SALVO")
    log("=" * 70)
    log(f"  Motivo: {msg}")
    log()
    log("  A base que ja esta no ar continua intacta.")
    if transitorio:
        log("  Isto NAO e uma falha: a API do BCB nao respondeu.")
        log("=" * 70)
        avisar_workflow(resultado="sem_acesso")
        sys.exit(0)
    log("=" * 70)
    avisar_workflow(resultado="erro")
    sys.exit(1)


def sem_acento(texto):
    nfkd = unicodedata.normalize("NFKD", str(texto or ""))
    limpo = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", limpo).strip().lower()


def formatar_cnpj(bruto):
    """Aceita numero ou texto e devolve 00.000.000/0000-00, ou None."""
    digitos = re.sub(r"\D", "", str(bruto or ""))
    if not digitos:
        return None
    digitos = digitos.zfill(14)          # a API devolve sem os zeros da frente
    if len(digitos) != 14:
        return None
    return f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:]}"


# ----------------------------------------------------------------------------
# AS TENTATIVAS DE URL
# ----------------------------------------------------------------------------

def candidatos(data_base=None):
    """
    Devolve (rotulo, url) em ordem de preferencia.

    As primeiras ja filtram as IPs na propria API -- e o que a colega descobriu
    ser necessario para nao dar timeout com a base inteira.
    """
    tipo = quote("Instituição de Pagamento")
    fmt = "$format=json"
    topo = "$top=5000"

    lista = []

    if data_base:
        d = data_base
        lista += [
            (f"funcao com dataBase={d} + filtro de tipo",
             f"{BASE}(dataBase=@dataBase)?@dataBase='{d}'&{fmt}&{topo}"
             f"&$filter=descricaoTipoEntidadeSupervisionada%20eq%20'{tipo}'"),
            (f"funcao com dataBase={d}, sem filtro",
             f"{BASE}(dataBase=@dataBase)?@dataBase='{d}'&{fmt}&{topo}"),
            (f"filtro por campo database={d} + tipo",
             f"{BASE}?{fmt}&{topo}"
             f"&$filter=database%20eq%20'{d}'%20and%20"
             f"descricaoTipoEntidadeSupervisionada%20eq%20'{tipo}'"),
        ]
    else:
        lista += [
            ("sem data, filtrando o tipo na API",
             f"{BASE}?{fmt}&{topo}"
             f"&$filter=descricaoTipoEntidadeSupervisionada%20eq%20'{tipo}'"),
            ("sem data, filtrando por 'contains'",
             f"{BASE}?{fmt}&{topo}"
             f"&$filter=contains(descricaoTipoEntidadeSupervisionada,'Pagamento')"),
            ("sem data, sem filtro (pode ser lento)",
             f"{BASE}?{fmt}&{topo}"),
        ]

    return lista


def datas_para_tentar(quantas=8):
    """
    A base do BCB e mensal e sai com alguns dias de atraso. Em vez de adivinhar
    o dia exato, tentamos os dias 5 dos ultimos meses -- que e o padrao visto
    na planilha de referencia (database 2026-09-05) -- e tambem o dia de hoje.
    """
    hoje = datetime.now(FUSO_BRASILIA).date()
    datas = [hoje.isoformat()]
    ano, mes = hoje.year, hoje.month
    for _ in range(quantas):
        datas.append(f"{ano:04d}-{mes:02d}-05")
        mes -= 1
        if mes == 0:
            mes, ano = 12, ano - 1
    return datas


def puxar(url, rotulo, tentativas=3):
    """Faz a chamada e devolve a lista de registros, ou None se nao der."""
    ultimo_erro = None
    for n in range(1, tentativas + 1):
        try:
            resp = requests.get(url, headers=CABECALHO_HTTP, timeout=TIMEOUT)
            if resp.status_code != 200:
                ultimo_erro = f"HTTP {resp.status_code}"
                trecho = resp.text[:180].replace("\n", " ")
                log(f"      {ultimo_erro} — resposta: {trecho}")
                break     # erro de formato nao melhora tentando de novo
            dados = resp.json()
            registros = dados.get("value", dados if isinstance(dados, list) else [])
            if registros:
                return registros
            ultimo_erro = "resposta vazia (0 registros)"
            log(f"      {ultimo_erro}")
            break
        except requests.exceptions.JSONDecodeError:
            ultimo_erro = "a resposta nao era JSON"
            log(f"      {ultimo_erro}")
            break
        except Exception as e:  # noqa: BLE001
            ultimo_erro = str(e)[:160]
            log(f"      erro de rede: {ultimo_erro}")
            if n < tentativas:
                time.sleep(3 * n)
    return None


def buscar_na_api():
    """
    Percorre as tentativas ate uma funcionar.
    Devolve (registros, rotulo_da_url, url_usada).
    """
    houve_erro_de_rede = False

    log("[1/5] Procurando o formato de chamada que a API aceita...")
    log()

    for rotulo, url in candidatos():
        log(f"  Tentando: {rotulo}")
        registros = puxar(url, rotulo)
        if registros:
            log(f"  ✓ FUNCIONOU — {len(registros):,} registros")
            return registros, rotulo, url

    log()
    log("  Nenhum formato sem data funcionou. Tentando com datas-base...")
    log()

    for data in datas_para_tentar():
        for rotulo, url in candidatos(data):
            log(f"  Tentando: {rotulo}")
            registros = puxar(url, rotulo)
            if registros:
                log(f"  ✓ FUNCIONOU — {len(registros):,} registros")
                return registros, rotulo, url

    morrer(
        "Nenhum formato de chamada devolveu dados.\n"
        "  Veja acima qual erro cada tentativa deu. Se todas falharam por rede,\n"
        "  e transitorio. Se deram HTTP 400/404, a API mudou e o script precisa\n"
        f"  de ajuste -- confira a documentacao em {FONTE_HUMANA}",
        transitorio=houve_erro_de_rede,
    )


# ----------------------------------------------------------------------------
# TRATAMENTO DOS REGISTROS
# ----------------------------------------------------------------------------

def eh_instituicao_de_pagamento(registro):
    tipo = sem_acento(registro.get("descricaoTipoEntidadeSupervisionada", ""))
    return TERMO_TIPO_IP in tipo


def normalizar(registro):
    """Pega so os campos que interessam e padroniza os nomes."""
    cnpj = formatar_cnpj(registro.get("codigoCNPJ14"))
    if not cnpj:
        return None

    razao = (registro.get("nomeEntidadeInteresse")
             or registro.get("nomeEntidadeInteresseNaoFormatado") or "").strip()
    if not razao:
        return None

    # Tudo pelo que da para procurar: razao social, nome reduzido, fantasia, sigla
    apelidos = []
    for campo in ("nomeReduzido", "nomeFantasia", "siglaDaPessoaJuridica"):
        valor = (registro.get(campo) or "").strip()
        if valor and sem_acento(valor) != sem_acento(razao):
            apelidos.append(valor)

    # tira repetidos mantendo a ordem
    vistos, unicos = set(), []
    for a in apelidos:
        chave = sem_acento(a)
        if chave not in vistos:
            vistos.add(chave)
            unicos.append(a)

    cnpj8 = re.sub(r"\D", "", str(registro.get("codigoCNPJ8") or ""))[:8].zfill(8)

    municipio = (registro.get("nomeDoMunicipio") or "").strip()
    uf = (registro.get("nomeDaUnidadeFederacao") or "").strip()

    return {
        "cnpj": cnpj,
        "cnpj_raiz": cnpj8,
        "razao_social": razao,
        "nomes": ", ".join(unicos),
        "tipo": (registro.get("descricaoTipoEntidadeSupervisionada") or "").strip(),
        "natureza_juridica": (registro.get("descricaoNaturezaJuridica") or "").strip(),
        "situacao": (registro.get("descricaoSituacao")
                     or registro.get("situacao") or "").strip(),
        "municipio": municipio,
        "uf": uf,
        "data_base": (registro.get("database") or registro.get("dataBase") or "").strip(),
    }


def limpar(registros):
    saida, vistos = [], set()
    for r in registros:
        item = normalizar(r)
        if not item:
            continue
        if item["cnpj"] in vistos:
            continue
        vistos.add(item["cnpj"])
        saida.append(item)
    return saida


# ----------------------------------------------------------------------------
# MODO EXPLORACAO
# ----------------------------------------------------------------------------

def explorar(registros, rotulo, url):
    log()
    log("=" * 70)
    log("  MODO EXPLORACAO - nada sera salvo")
    log("=" * 70)
    log()
    log(f"URL que funcionou ({rotulo}):")
    log(f"  {url}")
    log()
    log(f"Registros recebidos: {len(registros):,}")
    log()

    # Quais tipos de entidade vieram
    tipos = {}
    for r in registros:
        t = (r.get("descricaoTipoEntidadeSupervisionada") or "(sem tipo)").strip()
        tipos[t] = tipos.get(t, 0) + 1
    log("Tipos de entidade presentes na resposta:")
    for t, n in sorted(tipos.items(), key=lambda x: -x[1])[:25]:
        marca = "  <-- e o que queremos" if TERMO_TIPO_IP in sem_acento(t) else ""
        log(f"  {n:6,}  {t}{marca}")
    log()

    ips = [r for r in registros if eh_instituicao_de_pagamento(r)]
    log(f"Instituicoes de Pagamento encontradas: {len(ips):,}")
    log()

    if registros:
        log("Campos disponiveis em cada registro:")
        for campo in sorted(registros[0].keys()):
            exemplo = str(registros[0].get(campo))[:60]
            log(f"  {campo:45} = {exemplo}")
        log()

    if ips:
        log("Exemplo de IP ja tratada pelo script:")
        log(json.dumps(limpar(ips[:1])[0], ensure_ascii=False, indent=2))
        log()
        log("Primeiras 10 IPs:")
        for item in limpar(ips[:10]):
            log(f"  {item['cnpj']}  {item['razao_social'][:55]}")
    log()
    log("=" * 70)
    log("  Mande este log para o Claude e ele finaliza o robo.")
    log("=" * 70)


# ----------------------------------------------------------------------------
# COMPARACAO E GRAVACAO
# ----------------------------------------------------------------------------

def carregar_anterior():
    if not os.path.exists(ARQUIVO_DADOS):
        return []
    try:
        with open(ARQUIVO_DADOS, "r", encoding="utf-8") as f:
            dados = json.load(f)
        return dados.get("instituicoes", []) if isinstance(dados, dict) else dados
    except Exception:  # noqa: BLE001
        return []


def rotulo_empresa(e):
    nomes = e.get("nomes", "")
    return f"{e['razao_social']} ({nomes})" if nomes else e["razao_social"]


def comparar(antes, depois):
    a = {e["cnpj"]: e for e in antes if e.get("cnpj")}
    d = {e["cnpj"]: e for e in depois if e.get("cnpj")}
    return {
        "adicionadas": [rotulo_empresa(d[c]) for c in sorted(set(d) - set(a))],
        "removidas": [rotulo_empresa(a[c]) for c in sorted(set(a) - set(d))],
    }


def main():
    p = argparse.ArgumentParser(description="Instituicoes de Pagamento autorizadas (BCB)")
    p.add_argument("--explorar", action="store_true",
                   help="so mostra o que a API devolveu, sem salvar nada")
    args = p.parse_args()

    agora = datetime.now(FUSO_BRASILIA)
    log("=" * 70)
    log("  NU - CONSULTA  |  Instituicoes de Pagamento (BCB)")
    log(f"  Execucao: {agora.strftime('%d/%m/%Y %H:%M')} (horario de Brasilia)")
    log("=" * 70)
    log()
    log(f"  IPv4 forcado: {'sim' if forcar_ipv4() else 'nao'}")
    log()

    registros, rotulo, url = buscar_na_api()

    if args.explorar:
        explorar(registros, rotulo, url)
        return

    log()
    log("[2/5] Separando as Instituicoes de Pagamento...")
    brutos = [r for r in registros if eh_instituicao_de_pagamento(r)]
    ips = limpar(brutos)
    log(f"  {len(registros):,} registros recebidos -> {len(ips):,} IPs")

    log()
    log("[3/5] Conferindo se o resultado faz sentido...")
    if len(ips) < MINIMO_IPS:
        morrer(f"So encontrei {len(ips)} IPs, e o minimo aceitavel e {MINIMO_IPS}. "
               f"Rode com --explorar para ver o que a API devolveu.")

    anterior = carregar_anterior()
    if anterior:
        queda = (len(anterior) - len(ips)) / len(anterior)
        if queda > QUEDA_MAXIMA_ACEITAVEL:
            morrer(f"A base cairia de {len(anterior)} para {len(ips)} IPs "
                   f"({queda:.0%}). Confira antes de publicar.")
    log(f"  OK: {len(ips)} IPs, dentro do esperado.")

    log()
    log("[4/5] Comparando com a base anterior...")
    mudancas = comparar(anterior, ips)
    log(f"  Adicionadas: {len(mudancas['adicionadas'])}")
    log(f"  Removidas:   {len(mudancas['removidas'])}")
    for n in mudancas["adicionadas"]:
        log(f"    + {n}")
    for n in mudancas["removidas"]:
        log(f"    - {n}")

    log()
    log("[5/5] Salvando...")
    data_base = next((i["data_base"] for i in ips if i.get("data_base")), "")

    saida = {
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
    }
    with open(ARQUIVO_DADOS, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)
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
    else:
        log(f"  {ARQUIVO_HISTORICO} nao mexido (nada mudou)")

    batimento = "nao" if houve else "sim"
    resumo = (f"{len(ips)} IPs | +{len(mudancas['adicionadas'])} / "
              f"-{len(mudancas['removidas'])} | data-base {data_base or '?'}")
    avisar_workflow(resultado="ok", total=len(ips), batimento=batimento,
                    resumo=resumo, data_base=data_base,
                    adicionadas=len(mudancas["adicionadas"]),
                    removidas=len(mudancas["removidas"]))

    log()
    log("=" * 70)
    log(f"  CONCLUIDO: {resumo}")
    log("=" * 70)


if __name__ == "__main__":
    main()
