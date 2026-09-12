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

# ============================================================================
#  A ARMADILHA DA DATA -- leia antes de mexer aqui
# ----------------------------------------------------------------------------
#  A API espera a data em MM/DD/YYYY (formato americano), e NAO avisa quando
#  voce manda no formato brasileiro. Ela simplesmente devolve outro mes.
#
#      pedimos '05/09/2026'  pensando em 5 de setembro
#      recebemos dados com   database = 2026-05-09   (9 de MAIO)
#
#  O robo funcionaria, o site mostraria dados, e estariam quatro meses
#  atrasados sem ninguem perceber. Por isso, depois de baixar, o script
#  CONFERE se a data que voltou e a que ele pediu.
# ============================================================================

def montar_url(data, com_filtro=True):
    """Monta a chamada no formato que a API aceita."""
    valor = data.strftime("%m/%d/%Y")        # MM/DD/YYYY -- veja o aviso acima
    url = (f"{BASE}(dataBase=@dataBase)?@dataBase='{valor}'"
           f"&$format=json&$top=5000")
    if com_filtro:
        tipo = quote("Instituição de Pagamento")
        url += f"&$filter=descricaoTipoEntidadeSupervisionada%20eq%20'{tipo}'"
    return url


def data_que_voltou(registros):
    """Le o campo 'database' dos registros e devolve como date, ou None."""
    bruto = str(registros[0].get("database") or "").strip()[:10]
    try:
        return datetime.strptime(bruto, "%Y-%m-%d").date()
    except Exception:  # noqa: BLE001
        return None


def buscar(dias_para_tras=45):
    """
    Procura a base mais recente disponivel.

    Comeca em hoje e volta um dia por vez. A primeira data que devolver dados
    e a mais fresca que existe -- nao precisamos adivinhar em que dia do mes
    o BCB publica.
    """
    titulo("PROCURANDO A BASE MAIS RECENTE")
    hoje = datetime.now(FUSO_BRASILIA).date()
    erros = {}

    for n in range(dias_para_tras):
        data = hoje - timedelta(days=n)
        url = montar_url(data)
        registros, erro = pedir(url, tentativas=1)

        if registros:
            voltou = data_que_voltou(registros)
            log(f"  ✓ Base encontrada: {data.strftime('%d/%m/%Y')}")
            log(f"    {len(registros):,} registros")
            log(f"    campo 'database' na resposta: {voltou}")

            # A conferencia que impede o erro silencioso
            if voltou and voltou != data:
                log(f"    ATENCAO: pedi {data} e vieram dados de {voltou}.")
                log("    A API interpretou a data de outro jeito. Ignorando esta.")
                continue

            log(f"    URL: {url}")
            return registros, data, url

        chave = (erro or "")[:70]
        erros[chave] = erros.get(chave, 0) + 1
        if n < 3 or erros[chave] == 1:
            log(f"  ✗ {data.strftime('%d/%m/%Y')} — {erro}")

    log()
    log("  Resumo dos erros:")
    for erro, n in sorted(erros.items(), key=lambda x: -x[1]):
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
    Pega a DESCRICAO da situacao, nao o codigo.

    A API traz os dois campos, e o codigo vem antes na ordem alfabetica:

        codigoTipoSituacaoPessoaJuridica     = 3
        descricaoTipoSituacaoPessoaJuridica  = "Autorizada em Atividade"

    Pegar o primeiro campo com "situacao" no nome devolvia "3", que nao
    diz nada. Por isso a busca exige "descricao" no nome do campo.
    """
    # 1) o nome exato, que ja conhecemos
    valor = registro.get("descricaoTipoSituacaoPessoaJuridica")
    if isinstance(valor, str) and valor.strip():
        return valor.strip()

    # 2) qualquer campo que seja descricao E situacao (caso o BCB renomeie)
    for chave, valor in registro.items():
        nome = sem_acento(chave)
        if "descricao" in nome and "situacao" in nome:
            if isinstance(valor, str) and valor.strip():
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
        # A raiz sao os 8 primeiros digitos do CNPJ completo. Se a API mandar
        # o campo proprio, usamos; se vier vazio, tiramos do CNPJ14 -- porque
        # e por ela que o analista acha a matriz quando so tem o CNPJ de
        # uma filial em maos.
        "cnpj_raiz": (re.sub(r"\D", "", str(registro.get("codigoCNPJ8") or "")).zfill(8)
                      if str(registro.get("codigoCNPJ8") or "").strip()
                      else re.sub(r"\D", "", cnpj)[:8]),
        "razao_social": razao,
        "nomes": ", ".join(apelidos),
        "tipo": (registro.get("descricaoTipoEntidadeSupervisionada") or "").strip(),
        "natureza_juridica": (registro.get("descricaoNaturezaJuridica") or "").strip(),
        "situacao": situacao,              # texto original do BCB
        "status": classificar(situacao),   # o que a tela usa para colorir
        "municipio": (registro.get("nomeDoMunicipio") or "").strip(),
        # Atencao ao nome: e "Federativa", nao "Federacao"
        "uf": (registro.get("nomeDaUnidadeFederativa")
               or registro.get("nomeDaUnidadeFederacao") or "").strip(),
        "codigo_bacen": str(registro.get("codigoIdentificadorBacen") or "").strip(),
        # A data-base NAO entra aqui de proposito: ela e a mesma para todos os
        # registros e ja fica no bloco "meta". Se ficasse em cada um, as 211
        # linhas mudariam todo dia e o diff do Git viraria inutil -- seria
        # impossivel ver, no meio do ruido, qual IP realmente entrou ou saiu.
    }


def limpar(registros, contar=False):
    """
    Converte os registros da API e descarta o que nao serve.

    O parametro 'contar' existe por um motivo especifico: descartar em
    silencio e como o robo antigo das bets engolia erro. Se a nossa base
    tiver menos registros que a fonte, precisamos saber se foi porque a
    fonte mudou ou porque NOS jogamos algo fora -- e quanto.
    """
    saida, vistos = [], set()
    descartes = {"sem_cnpj": 0, "sem_nome": 0, "repetido": 0}

    for r in registros:
        cnpj = formatar_cnpj(r.get("codigoCNPJ14"))
        if not cnpj:
            descartes["sem_cnpj"] += 1
            continue

        item = normalizar(r)
        if not item:
            descartes["sem_nome"] += 1
            continue

        if item["cnpj"] in vistos:
            descartes["repetido"] += 1
            continue

        vistos.add(item["cnpj"])
        saida.append(item)

    if contar:
        total = sum(descartes.values())
        log(f"  {len(registros):,} registros recebidos da API")
        if total:
            log(f"  {total} descartado(s): "
                f"{descartes['sem_cnpj']} sem CNPJ · "
                f"{descartes['sem_nome']} sem nome · "
                f"{descartes['repetido']} CNPJ repetido")
        else:
            log("  nenhum registro descartado")
        log(f"  {len(saida):,} na base final")

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

    # Quantos registros a API mandou e quantos sobraram depois da limpeza.
    # Sem isto, um descarte silencioso apareceria so como "um numero menor".
    log("  Conferencia de contagem:")
    tratadas = limpar(ips, contar=True)
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

    if tratadas:
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


def salvar(ips, url, agora, data_base=""):
    anterior = carregar_anterior()

    if len(ips) < MINIMO_IPS:
        morrer(f"So encontrei {len(ips)} IPs, e o minimo aceitavel e {MINIMO_IPS}.")
    if anterior:
        queda = (len(anterior) - len(ips)) / len(anterior)
        if queda > QUEDA_MAXIMA_ACEITAVEL:
            morrer(f"A base cairia de {len(anterior)} para {len(ips)} ({queda:.0%}).")

    mudancas = comparar(anterior, ips)

    # Quantas em cada situacao -- o site usa isso para explicar a base
    por_status = {}
    for i in ips:
        por_status[i["status"]] = por_status.get(i["status"], 0) + 1
    log("  Situacao: " + " · ".join(f"{n} {s}" for s, n in sorted(por_status.items())))

    with open(ARQUIVO_DADOS, "w", encoding="utf-8") as f:
        json.dump({
            "meta": {
                "fonte": FONTE_HUMANA,
                "api": url,
                "data_base": data_base,
                "verificado_em": agora.strftime("%d/%m/%Y %H:%M"),
                "verificado_em_iso": agora.isoformat(timespec="seconds"),
                "total": len(ips),
                "por_status": por_status,
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
    p.add_argument("--data", default="",
                   help="consulta uma data-base especifica, no formato DD/MM/AAAA. "
                        "Serve para comparar com outra base da mesma data.")
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
        ips = limpar([r for r in registros if eh_ip(r)], contar=True)
        voltou = data_que_voltou(registros)
        salvar(ips, args.url, agora, voltou.isoformat() if voltou else "")
        return

    # --- data-base especifica: util para comparar com outra base ---
    if args.data:
        titulo(f"CONSULTANDO A DATA-BASE {args.data}")
        try:
            alvo = datetime.strptime(args.data.strip(), "%d/%m/%Y").date()
        except ValueError:
            morrer(f"Data invalida: '{args.data}'. Use o formato DD/MM/AAAA.")

        url = montar_url(alvo)
        log(f"  {url}")
        registros, erro = pedir(url)
        if not registros:
            morrer(f"A data {args.data} nao devolveu dados. {erro}",
                   transitorio="rede" in (erro or ""))

        voltou = data_que_voltou(registros)
        log(f"  campo 'database' na resposta: {voltou}")
        if voltou and voltou != alvo:
            morrer(f"Pedi {alvo} e vieram dados de {voltou}. "
                   "A API interpretou a data de outro jeito.")

        ips = limpar([r for r in registros if eh_ip(r)], contar=True)
        if args.explorar:
            explorar(registros, f"dataBase={args.data}", url)
        else:
            salvar(ips, url, agora, alvo.isoformat())
        return

    # --- caminho normal ---
    if args.explorar:
        mostrar_catalogo()

    registros, data, url = buscar()

    if not registros:
        morrer(
            "Nao encontrei nenhuma base nos ultimos 45 dias.\n"
            "  Se os erros acima forem de rede, e transitorio.\n"
            "  Se forem HTTP 400/500, a API mudou o formato da chamada.",
            transitorio=True,
        )

    if args.explorar:
        explorar(registros, f"dataBase={data.strftime('%d/%m/%Y')}", url)
        return

    ips = limpar([r for r in registros if eh_ip(r)], contar=True)
    salvar(ips, url, agora, data.isoformat())


if __name__ == "__main__":
    main()
