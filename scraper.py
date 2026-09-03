#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
 NU - CONSULTA BET  |  Atualizador da base oficial (SPA/MF)
=============================================================================

O QUE ESTE SCRIPT FAZ
---------------------
1. Le as DUAS paginas oficiais do Ministerio da Fazenda:
     - Empresas autorizadas administrativamente
     - Empresas autorizadas por determinacao judicial
2. Captura tambem a linha "Publicado em ... Atualizado em ..." de cada pagina.
3. CONFERE se o resultado faz sentido antes de salvar (ver secao TRAVAS).
4. Compara com a base atual e monta o relatorio "o que mudou".
5. Salva dados.json e historico.json.

A REGRA DE OURO
---------------
Se qualquer coisa der errado, este script NAO salva nada e termina com erro.
E melhor o site ficar com a base de ontem do que com uma base errada.

Isso e o oposto da versao antiga, que engolia o erro em silencio e publicava
uma base vazia. Foi assim que a base zerou.

COMO RODAR NA MAO
-----------------
    pip install requests beautifulsoup4 lxml
    python scraper.py

=============================================================================
"""

import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

# ----------------------------------------------------------------------------
# CONFIGURACAO
# ----------------------------------------------------------------------------

URL_ADMINISTRATIVAS = (
    "https://www.gov.br/fazenda/pt-br/composicao/orgaos/secretaria-de-premios-e-apostas"
    "/transparencia-ativa-processos-de-autorizacao-de-apostas-de-quota-fixa/empresas-autorizadas"
)

URL_JUDICIAIS = (
    "https://www.gov.br/fazenda/pt-br/composicao/orgaos/secretaria-de-premios-e-apostas"
    "/transparencia-ativa-processos-de-autorizacao-de-apostas-de-quota-fixa"
    "/autorizadas-por-determinacao-judicial"
)

# --- TRAVAS DE SEGURANCA ---------------------------------------------------
# Se a raspagem devolver menos empresas que isto, o script aborta.
# A lista oficial tem ~85 hoje. 50 e um piso confortavel: da margem para o
# governo cassar varias autorizacoes de uma vez, mas pega qualquer falha grave.
MINIMO_ADMINISTRATIVAS = 50

# Se a base encolher mais que esta fracao de uma vez, aborta e pede revisao
# humana. 0.30 = uma queda de mais de 30% e suspeita.
QUEDA_MAXIMA_ACEITAVEL = 0.30
# ---------------------------------------------------------------------------

ARQUIVO_DADOS = "dados.json"
ARQUIVO_HISTORICO = "historico.json"

CABECALHO_HTTP = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
}

FUSO_BRASILIA = timezone(timedelta(hours=-3))


# ----------------------------------------------------------------------------
# UTILITARIOS
# ----------------------------------------------------------------------------

def log(msg):
    print(msg, flush=True)


def morrer(msg):
    """Aborta o script sem salvar nada. A base atual continua no ar."""
    log("")
    log("=" * 70)
    log("  ABORTADO - NADA FOI SALVO")
    log("=" * 70)
    log(f"  Motivo: {msg}")
    log("")
    log("  A base que ja esta no ar continua intacta.")
    log("  Verifique se o governo mudou o endereco ou o formato da pagina.")
    log("=" * 70)
    sys.exit(1)


def sem_acento(texto):
    """'Denominação' -> 'denominacao'. Usado para comparar nomes de coluna."""
    if not texto:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(texto))
    limpo = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", limpo).strip().lower()


def formatar_cnpj(bruto):
    """Aceita qualquer formato e devolve 00.000.000/0000-00, ou None."""
    digitos = re.sub(r"\D", "", str(bruto or ""))
    if len(digitos) != 14:
        return None
    return f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:]}"


def baixar(url, tentativas=3):
    """Baixa uma pagina. Se falhar nas 3 tentativas, aborta o script."""
    ultimo_erro = None
    for n in range(1, tentativas + 1):
        try:
            log(f"  Tentativa {n}/{tentativas}: {url}")
            resp = requests.get(url, headers=CABECALHO_HTTP, timeout=40)
            if resp.status_code == 200 and len(resp.text) > 5000:
                resp.encoding = resp.apparent_encoding or "utf-8"
                log(f"  OK ({len(resp.text):,} caracteres recebidos)")
                return resp.text
            ultimo_erro = f"HTTP {resp.status_code}, {len(resp.text)} caracteres"
        except Exception as e:  # noqa: BLE001
            ultimo_erro = str(e)
        log(f"  Falhou: {ultimo_erro}")
    morrer(f"Nao consegui baixar {url}. Ultimo erro: {ultimo_erro}")


# ----------------------------------------------------------------------------
# LEITURA DA DATA "Publicado em ... Atualizado em ..."
# ----------------------------------------------------------------------------

PADRAO_DATA = re.compile(
    r"Publicado\s+em\s+(\d{2}/\d{2}/\d{4}\s+\d{2}h\d{2})"
    r"(?:.*?Atualizado\s+em\s+(\d{2}/\d{2}/\d{4}\s+\d{2}h\d{2}))?",
    re.IGNORECASE | re.DOTALL,
)


def extrair_datas(soup, nome_pagina):
    """
    Pega a linha 'Publicado em 20/07/2026 17h28 Atualizado em 24/08/2026 11h47'
    que fica logo abaixo do titulo da materia no gov.br.
    """
    texto = soup.get_text(" ", strip=True)
    m = PADRAO_DATA.search(texto)
    if not m:
        log(f"  AVISO: nao achei a data de publicacao em '{nome_pagina}'.")
        return {"publicado_em": None, "atualizado_em": None}

    publicado = m.group(1)
    atualizado = m.group(2) or publicado
    log(f"  Publicado em {publicado} | Atualizado em {atualizado}")
    return {"publicado_em": publicado, "atualizado_em": atualizado}


# ----------------------------------------------------------------------------
# LEITURA DAS TABELAS
# ----------------------------------------------------------------------------

def texto_da_celula(td):
    """
    Devolve a lista de "pedacos" de uma celula.

    Isso importa porque no site do governo as marcas de uma mesma empresa vem
    em paragrafos separados dentro da mesma celula. Se a gente pegar o texto
    cru, "ZEROUM", "ENERGIA" e "SPORTVIP" viram "ZEROUMENERGIASPORTVIP".
    Aqui a gente preserva a separacao.
    """
    for br in td.find_all("br"):
        br.replace_with("\n")

    blocos = td.find_all(["p", "div", "li"], recursive=False)
    if blocos:
        pedacos = [b.get_text(" ", strip=True) for b in blocos]
    else:
        pedacos = td.get_text("\n", strip=True).split("\n")

    resultado = []
    for p in pedacos:
        for linha in p.split("\n"):
            limpo = re.sub(r"\s+", " ", linha).strip(" ;, ")
            if limpo:
                resultado.append(limpo)
    return resultado


def link_da_celula(td):
    a = td.find("a", href=True)
    return a["href"].strip() if a else None


# Como reconhecemos cada coluna: (nome interno, palavras que aparecem no cabecalho)
#
# A ORDEM IMPORTA. O cabecalho real da pagina do governo e
# "N° de Requerimento / Autorizacao / SIGAP" -- se "autorizacao" estivesse na
# lista da portaria, essa coluna seria confundida com a da portaria.
# Por isso o requerimento e testado antes, e a portaria so aceita as palavras
# que sao realmente exclusivas dela.
MAPA_COLUNAS = [
    ("cnpj",         ["cnpj"]),
    ("requerimento", ["requerimento", "sigap"]),
    ("razao_social", ["denominacao", "razao social", "empresa"]),
    ("marcas",       ["marca"]),
    ("dominio",      ["dominio", "endereco eletronico", "site", "url"]),
    ("portaria",     ["portaria", "informacoes judiciais"]),
    ("documento",    ["documento", "publicacao", "dou"]),
]


def identificar_colunas(cabecalhos):
    """Descobre qual indice de coluna corresponde a qual campo."""
    indices = {}
    for i, titulo in enumerate(cabecalhos):
        t = sem_acento(titulo)
        if not t:
            continue
        for campo, palavras in MAPA_COLUNAS:
            if campo in indices:
                continue
            if any(p in t for p in palavras):
                indices[campo] = i
                break
    return indices


def ler_tabelas(soup, origem):
    """
    Percorre todas as <table> da pagina e extrai as linhas que tenham CNPJ valido.
    Retorna uma lista de dicionarios.
    """
    registros = []

    for tabela in soup.find_all("table"):
        linhas = tabela.find_all("tr")
        if len(linhas) < 2:
            continue

        # --- cabecalho ---
        celulas_cab = linhas[0].find_all(["th", "td"])
        cabecalhos = [c.get_text(" ", strip=True) for c in celulas_cab]
        col = identificar_colunas(cabecalhos)

        if "cnpj" not in col:
            continue  # nao e uma tabela de empresas

        # --- linhas de dados ---
        for tr in linhas[1:]:
            tds = tr.find_all(["td", "th"])
            if len(tds) <= col["cnpj"]:
                continue

            cnpj = formatar_cnpj(" ".join(texto_da_celula(tds[col["cnpj"]])))
            if not cnpj:
                continue

            def campo(nome, separador=", "):
                idx = col.get(nome)
                if idx is None or idx >= len(tds):
                    return ""
                return separador.join(texto_da_celula(tds[idx]))

            registro = {
                "cnpj": cnpj,
                "razao_social": campo("razao_social", " "),
                "marcas": campo("marcas"),
                "dominio": campo("dominio"),
                "portaria": campo("portaria", " "),
                "requerimento": campo("requerimento", " "),
                "origem": origem,  # "administrativa" ou "judicial"
            }

            # Link do ato oficial: procura primeiro na coluna "Documento",
            # depois na coluna "Portaria".
            for nome_col in ("documento", "portaria"):
                idx = col.get(nome_col)
                if idx is not None and idx < len(tds):
                    href = link_da_celula(tds[idx])
                    if href:
                        registro["documento_url"] = href
                        break

            # Se a portaria veio vazia mas existe coluna "Documento", usa ela.
            if not registro["portaria"] and col.get("documento") is not None:
                registro["portaria"] = campo("documento", " ")

            registros.append(registro)

    return registros


def limpar_registros(registros):
    """Remove duplicatas exatas e linhas sem nome de empresa."""
    vistos = set()
    saida = []
    for r in registros:
        if not r["razao_social"]:
            continue
        chave = (r["cnpj"], r["portaria"], r["marcas"])
        if chave in vistos:
            continue
        vistos.add(chave)
        saida.append(r)
    return saida


# ----------------------------------------------------------------------------
# COMPARACAO COM A BASE ANTERIOR
# ----------------------------------------------------------------------------

def carregar_base_anterior():
    """Le o dados.json que ja esta no ar. Aceita o formato novo e o antigo."""
    if not os.path.exists(ARQUIVO_DADOS):
        return []

    try:
        with open(ARQUIVO_DADOS, "r", encoding="utf-8") as f:
            conteudo = f.read().strip()
        if not conteudo:
            return []

        dados = json.loads(conteudo)
        if isinstance(dados, dict):          # formato novo
            return dados.get("empresas", [])
        if isinstance(dados, list):          # formato antigo (lista pura)
            return dados
    except json.JSONDecodeError:
        # formato bem antigo: uma linha JSON por empresa
        try:
            with open(ARQUIVO_DADOS, "r", encoding="utf-8") as f:
                return [json.loads(l) for l in f if l.strip()]
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        pass

    return []


def rotulo(empresa):
    marcas = empresa.get("marcas", "")
    nome = empresa.get("razao_social", "?")
    return f"{nome} ({marcas})" if marcas else nome


def comparar(antes, depois):
    """Monta o relatorio de mudancas entre a base antiga e a nova."""
    por_cnpj_antes = {e["cnpj"]: e for e in antes if e.get("cnpj")}
    por_cnpj_depois = {e["cnpj"]: e for e in depois if e.get("cnpj")}

    novos = sorted(set(por_cnpj_depois) - set(por_cnpj_antes))
    sumidos = sorted(set(por_cnpj_antes) - set(por_cnpj_depois))

    alteradas = []
    for cnpj in set(por_cnpj_antes) & set(por_cnpj_depois):
        a, d = por_cnpj_antes[cnpj], por_cnpj_depois[cnpj]
        if sem_acento(a.get("marcas", "")) != sem_acento(d.get("marcas", "")):
            alteradas.append({
                "empresa": d.get("razao_social", cnpj),
                "antes": a.get("marcas", ""),
                "depois": d.get("marcas", ""),
            })

    return {
        "adicionadas": [rotulo(por_cnpj_depois[c]) for c in novos],
        "removidas": [rotulo(por_cnpj_antes[c]) for c in sumidos],
        "marcas_alteradas": sorted(alteradas, key=lambda x: x["empresa"]),
    }


# ----------------------------------------------------------------------------
# PROGRAMA PRINCIPAL
# ----------------------------------------------------------------------------

def main():
    agora = datetime.now(FUSO_BRASILIA)

    log("=" * 70)
    log("  NU - CONSULTA BET  |  Atualizacao da base oficial")
    log(f"  Execucao: {agora.strftime('%d/%m/%Y %H:%M')} (horario de Brasilia)")
    log("=" * 70)

    # ---------- 1. Empresas autorizadas administrativamente ----------
    log("")
    log("[1/5] Lendo empresas autorizadas (SPA/MF)...")
    html_adm = baixar(URL_ADMINISTRATIVAS)
    soup_adm = BeautifulSoup(html_adm, "html.parser")
    datas_adm = extrair_datas(soup_adm, "empresas autorizadas")
    adm = limpar_registros(ler_tabelas(soup_adm, "administrativa"))
    log(f"  -> {len(adm)} empresas encontradas")

    # ---------- 2. Autorizadas por determinacao judicial ----------
    log("")
    log("[2/5] Lendo autorizadas por determinacao judicial...")
    html_jud = baixar(URL_JUDICIAIS)
    soup_jud = BeautifulSoup(html_jud, "html.parser")
    datas_jud = extrair_datas(soup_jud, "autorizadas por determinacao judicial")
    jud = limpar_registros(ler_tabelas(soup_jud, "judicial"))
    log(f"  -> {len(jud)} empresas encontradas")

    # ---------- 3. TRAVAS DE SEGURANCA ----------
    log("")
    log("[3/5] Conferindo se o resultado faz sentido...")

    if len(adm) < MINIMO_ADMINISTRATIVAS:
        morrer(
            f"So encontrei {len(adm)} empresas autorizadas, e o minimo aceitavel "
            f"e {MINIMO_ADMINISTRATIVAS}. Provavelmente o governo mudou o endereco "
            f"ou o formato da tabela."
        )

    if len(jud) == 0:
        log("  AVISO: nenhuma empresa judicial encontrada. Pode ser correto "
            "(liminares caem), mas vale conferir na mao.")

    base_anterior = carregar_base_anterior()
    total_novo = len(adm) + len(jud)

    if base_anterior:
        queda = (len(base_anterior) - total_novo) / len(base_anterior)
        if queda > QUEDA_MAXIMA_ACEITAVEL:
            morrer(
                f"A base cairia de {len(base_anterior)} para {total_novo} empresas "
                f"({queda:.0%} de queda). Isso e alto demais para ser normal. "
                f"Confira as paginas oficiais antes de publicar."
            )

    # toda empresa precisa ter, no minimo, nome e CNPJ
    sem_nome = [e["cnpj"] for e in adm + jud if not e["razao_social"]]
    if sem_nome:
        morrer(f"{len(sem_nome)} empresa(s) vieram sem nome. Exemplo: {sem_nome[:3]}")

    log(f"  OK: {total_novo} empresas no total, dentro do esperado.")

    # ---------- 4. Comparacao ----------
    log("")
    log("[4/5] Comparando com a base anterior...")
    empresas = adm + jud
    mudancas = comparar(base_anterior, empresas)

    log(f"  Adicionadas ........ {len(mudancas['adicionadas'])}")
    log(f"  Removidas .......... {len(mudancas['removidas'])}")
    log(f"  Marcas alteradas ... {len(mudancas['marcas_alteradas'])}")

    for nome in mudancas["adicionadas"]:
        log(f"    + {nome}")
    for nome in mudancas["removidas"]:
        log(f"    - {nome}")

    # ---------- 5. Gravacao ----------
    log("")
    log("[5/5] Salvando arquivos...")

    saida_dados = {
        "meta": {
            "fonte_administrativas": URL_ADMINISTRATIVAS,
            "fonte_judiciais": URL_JUDICIAIS,
            "publicado_em": datas_adm["publicado_em"],
            "atualizado_em": datas_adm["atualizado_em"],
            "publicado_em_judicial": datas_jud["publicado_em"],
            "atualizado_em_judicial": datas_jud["atualizado_em"],
            "verificado_em": agora.strftime("%d/%m/%Y %H:%M"),
            "total": total_novo,
            "total_administrativas": len(adm),
            "total_judiciais": len(jud),
        },
        "empresas": sorted(empresas, key=lambda e: sem_acento(e["razao_social"])),
    }

    saida_historico = {
        "data": datas_adm["atualizado_em"] or agora.strftime("%d/%m/%Y %H:%M"),
        "verificado_em": agora.strftime("%d/%m/%Y %H:%M"),
        "adicionadas": mudancas["adicionadas"],
        "removidas": mudancas["removidas"],
        "marcas_alteradas": mudancas["marcas_alteradas"],
        "total_adicionadas": len(mudancas["adicionadas"]),
        "total_removidas": len(mudancas["removidas"]),
    }

    with open(ARQUIVO_DADOS, "w", encoding="utf-8") as f:
        json.dump(saida_dados, f, ensure_ascii=False, indent=2)

    with open(ARQUIVO_HISTORICO, "w", encoding="utf-8") as f:
        json.dump(saida_historico, f, ensure_ascii=False, indent=2)

    log(f"  {ARQUIVO_DADOS} gravado ({total_novo} empresas)")
    log(f"  {ARQUIVO_HISTORICO} gravado")

    # Deixa um resumo para o GitHub Actions usar no titulo/corpo do Pull Request
    resumo = (
        f"{total_novo} empresas | "
        f"+{len(mudancas['adicionadas'])} / -{len(mudancas['removidas'])} | "
        f"atualizado no gov.br em {datas_adm['atualizado_em']}"
    )
    if os.getenv("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"resumo={resumo}\n")
            f.write(f"total={total_novo}\n")
            f.write(f"adicionadas={len(mudancas['adicionadas'])}\n")
            f.write(f"removidas={len(mudancas['removidas'])}\n")

    log("")
    log("=" * 70)
    log(f"  CONCLUIDO: {resumo}")
    log("=" * 70)


if __name__ == "__main__":
    main()
