#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
 NU - CONSULTA BET  |  Bot do Slack
=============================================================================

Manda tres tipos de mensagem para o canal:

  mudancas   Uma casa entrou ou saiu da lista oficial.
             Dispara sozinho quando voce da merge no Pull Request do robo,
             ou seja: quando a mudanca realmente entra no ar.

  semanal    Resumo de toda segunda-feira, mesmo sem novidade.
             Serve de sinal de vida: se a mensagem nao chegar, algo esta
             errado. Silencio nunca fica ambiguo.

  aviso      Novidade escrita por voce (mudou o visual, entrou funcao nova).
             Voce roda na mao pelo GitHub e digita o texto.

Nao usa nenhuma biblioteca externa -- so o que ja vem com o Python.

COMO RODAR NA MAO
-----------------
    export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
    python avisar_slack.py semanal
    python avisar_slack.py mudancas
    python avisar_slack.py aviso --texto "Agora a busca mostra os dominios oficiais."

    # so montar a mensagem e imprimir, sem enviar:
    python avisar_slack.py semanal --simular

=============================================================================
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

# ----------------------------------------------------------------------------
# CONFIGURACAO -- ajuste o endereco do site aqui
# ----------------------------------------------------------------------------

URL_SITE = os.getenv("URL_SITE", "https://nuspacegb.github.io/consultabet/")

URL_FONTE_OFICIAL = (
    "https://www.gov.br/fazenda/pt-br/composicao/orgaos/secretaria-de-premios-e-apostas"
    "/transparencia-ativa-processos-de-autorizacao-de-apostas-de-quota-fixa/empresas-autorizadas"
)

ARQUIVO_DADOS = "dados.json"
ARQUIVO_HISTORICO = "historico.json"

# Quantos nomes listar antes de resumir com "e mais N".
# Evita mensagem gigante quando o governo mexe em muita coisa de uma vez.
MAXIMO_NOMES = 12


# ----------------------------------------------------------------------------
# LEITURA DOS ARQUIVOS
# ----------------------------------------------------------------------------

def ler_json(caminho, padrao):
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:  # noqa: BLE001
        print(f"AVISO: nao consegui ler {caminho} ({e}). Usando valor padrao.")
        return padrao


def carregar():
    dados = ler_json(ARQUIVO_DADOS, {})
    hist = ler_json(ARQUIVO_HISTORICO, {})

    if isinstance(dados, list):          # formato antigo
        empresas, meta = dados, {}
    else:
        empresas = dados.get("empresas", [])
        meta = dados.get("meta", {})

    return empresas, meta, hist


# ----------------------------------------------------------------------------
# MONTAGEM DAS MENSAGENS (formato Block Kit do Slack)
# ----------------------------------------------------------------------------

def texto(txt):
    return {"type": "section", "text": {"type": "mrkdwn", "text": txt}}


def contexto(txt):
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": txt}]}


def titulo(txt):
    return {"type": "header", "text": {"type": "plain_text", "text": txt, "emoji": True}}


def lista_de_nomes(nomes):
    """Transforma uma lista de empresas em bullets, cortando se for longa demais."""
    mostrar = nomes[:MAXIMO_NOMES]
    linhas = "\n".join(f"• {n}" for n in mostrar)
    if len(nomes) > MAXIMO_NOMES:
        linhas += f"\n_… e mais {len(nomes) - MAXIMO_NOMES}. Veja a lista completa no site._"
    return linhas


def rodape(meta):
    total = meta.get("total", "?")
    atualizado = meta.get("atualizado_em", "data não informada")
    return contexto(
        f"*{total}* casas na base · lista oficial atualizada em *{atualizado}* · "
        f"<{URL_SITE}|abrir o Consulta Bet> · <{URL_FONTE_OFICIAL}|fonte gov.br>"
    )


def montar_mudancas(empresas, meta, hist):
    """Mensagem disparada quando a lista oficial muda."""
    add = hist.get("adicionadas", [])
    rem = hist.get("removidas", [])
    alt = hist.get("marcas_alteradas", [])

    if not (add or rem or alt):
        return None   # nada mudou: nao enche o canal

    partes = []
    resumo = []
    if add:
        resumo.append(f"{len(add)} entrou" if len(add) == 1 else f"{len(add)} entraram")
    if rem:
        resumo.append(f"{len(rem)} saiu" if len(rem) == 1 else f"{len(rem)} saíram")
    if alt:
        resumo.append(f"{len(alt)} mudou de marca" if len(alt) == 1
                      else f"{len(alt)} mudaram de marca")

    blocos = [
        titulo("🔄 A lista oficial de bets mudou"),
        texto(f"*{' · '.join(resumo)}* — já está no ar no Consulta Bet."),
    ]

    if add:
        blocos.append(texto(f"*🟢 Entraram na lista*\n{lista_de_nomes(add)}"))
    if rem:
        blocos.append(texto(f"*🔴 Saíram da lista*\n{lista_de_nomes(rem)}"))
    if alt:
        linhas = "\n".join(
            f"• *{a['empresa']}*: {a['antes'] or '—'} → {a['depois'] or '—'}"
            for a in alt[:MAXIMO_NOMES]
        )
        if len(alt) > MAXIMO_NOMES:
            linhas += f"\n_… e mais {len(alt) - MAXIMO_NOMES}._"
        blocos.append(texto(f"*🟣 Marcas alteradas*\n{linhas}"))

    blocos.append({"type": "divider"})
    blocos.append(rodape(meta))
    partes.append(blocos)

    return {
        "text": f"A lista oficial de bets mudou: {' · '.join(resumo)}",  # notificacao do celular
        "blocks": blocos,
    }


def dias_desde_verificacao(meta):
    """
    Quantos dias desde a ultima verificacao bem-sucedida.
    Devolve None se a base nao tiver essa informacao.
    """
    iso = meta.get("verificado_em_iso")
    if not iso:
        return None
    try:
        from datetime import datetime, timezone
        quando = datetime.fromisoformat(iso)
        if quando.tzinfo is None:
            quando = quando.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - quando).days
    except Exception:  # noqa: BLE001
        return None


def montar_semanal(empresas, meta, hist):
    """Resumo de segunda-feira. Sai mesmo quando nada mudou."""
    add = hist.get("adicionadas", [])
    rem = hist.get("removidas", [])
    total = meta.get("total", len(empresas))
    atualizado = meta.get("atualizado_em", "data não informada")

    if add or rem:
        linha = (f"Desde a última verificação: *{len(add)}* entraram e "
                 f"*{len(rem)}* saíram da lista.")
        linha_simples = (f"Desde a última verificação: {len(add)} entraram e "
                         f"{len(rem)} saíram.")
    else:
        linha = "Nenhuma alteração desde a última verificação. A lista segue igual."
        linha_simples = linha

    blocos = [
        titulo("📊 Consulta Bet · resumo da semana"),
        texto(
            f"*{total}* casas de apostas autorizadas pelo Governo Federal.\n"
            f"{linha}"
        ),
    ]

    # Se a ultima verificacao bem-sucedida ficou velha, o robo pode estar
    # travado -- por exemplo, o gov.br bloqueando o servidor todos os dias.
    # Melhor dizer isso em voz alta do que deixar a base envelhecer calada.
    dias = dias_desde_verificacao(meta)
    if dias is not None and dias >= 8:
        blocos.append(texto(
            f"⚠️ *Atenção:* a última verificação bem-sucedida foi há *{dias} dias*. "
            "O robô pode estar sem conseguir acessar o gov.br. "
            "Vale conferir a aba Actions no GitHub."
        ))
    elif dias is not None:
        blocos.append(contexto(
            "Verificado com sucesso "
            + ("hoje." if dias == 0 else "ontem." if dias == 1 else f"há {dias} dias.")
        ))

    blocos += [
        contexto(f"Lista oficial publicada pela SPA/MF, atualizada em *{atualizado}*."),
        {"type": "divider"},
        contexto(
            f"<{URL_SITE}|Consultar uma casa> · <{URL_FONTE_OFICIAL}|Ver a fonte no gov.br>\n"
            "_Esta mensagem chega toda segunda. Se ela não chegar, o robô parou._"
        ),
    ]

    return {"text": f"Consulta Bet: {total} casas autorizadas. {linha_simples}",
            "blocks": blocos}


def montar_aviso(empresas, meta, corpo, assunto):
    """Novidade escrita a mao: mudanca de interface, funcao nova, etc."""
    blocos = [
        titulo(f"📣 {assunto}"),
        texto(corpo),
        {"type": "divider"},
        contexto(f"<{URL_SITE}|Abrir o Consulta Bet>"),
    ]
    return {"text": f"{assunto} — {corpo[:120]}", "blocks": blocos}


def montar_falha(meta, url_log):
    """Alerta de que o robo nao conseguiu atualizar a base."""
    blocos = [
        titulo("⚠️ O robô da base não conseguiu atualizar"),
        texto(
            "*Nada foi publicado com erro.* O site continua com a última base válida, "
            "apenas possivelmente desatualizada.\n\n"
            "Causa mais comum: o gov.br mudou o endereço ou saiu do ar."
        ),
        contexto(f"<{url_log}|Ver o log da execução> · <{URL_FONTE_OFICIAL}|Conferir na fonte>"),
    ]
    return {"text": "O robô da base do Consulta Bet falhou. Nada foi publicado.", "blocks": blocos}


# ----------------------------------------------------------------------------
# ENVIO
# ----------------------------------------------------------------------------

def enviar(mensagem):
    url = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    if not url:
        print("ERRO: a variavel SLACK_WEBHOOK_URL nao esta definida.")
        print("      No GitHub: Settings > Secrets and variables > Actions > New secret.")
        sys.exit(1)

    corpo = json.dumps(mensagem, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=corpo,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            resposta = resp.read().decode("utf-8", "replace").strip()
            print(f"Slack respondeu: HTTP {resp.status} {resposta}")
            return True
    except urllib.error.HTTPError as e:
        detalhe = e.read().decode("utf-8", "replace").strip()
        print(f"ERRO do Slack: HTTP {e.code} - {detalhe}")
        if detalhe == "invalid_token" or e.code == 403:
            print("      O webhook foi revogado. Gere outro no Slack e atualize o segredo.")
        if detalhe == "no_service":
            print("      A URL do webhook esta errada ou o app foi removido do canal.")
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(f"ERRO ao falar com o Slack: {e}")
        sys.exit(1)


# ----------------------------------------------------------------------------
# PROGRAMA PRINCIPAL
# ----------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="Bot do Slack do Nu - Consulta Bet")
    p.add_argument("tipo", choices=["mudancas", "semanal", "aviso", "falha"])
    p.add_argument("--texto", default="", help="corpo da mensagem (so para 'aviso')")
    p.add_argument("--assunto", default="Novidade no Consulta Bet",
                   help="titulo da mensagem (so para 'aviso')")
    p.add_argument("--log", default="", help="link do log (so para 'falha')")
    p.add_argument("--simular", action="store_true",
                   help="monta a mensagem e imprime, sem enviar nada")
    args = p.parse_args()

    empresas, meta, hist = carregar()

    if args.tipo == "mudancas":
        msg = montar_mudancas(empresas, meta, hist)
        if msg is None:
            print("Nenhuma mudanca no historico. Nada a anunciar.")
            return
    elif args.tipo == "semanal":
        msg = montar_semanal(empresas, meta, hist)
    elif args.tipo == "falha":
        msg = montar_falha(meta, args.log or URL_SITE)
    else:
        if not args.texto.strip():
            print("ERRO: o aviso precisa de um texto. Use --texto \"sua mensagem\".")
            sys.exit(1)
        msg = montar_aviso(empresas, meta, args.texto.strip(), args.assunto.strip())

    if args.simular:
        print(json.dumps(msg, ensure_ascii=False, indent=2))
        return

    enviar(msg)
    print("Mensagem enviada.")


if __name__ == "__main__":
    main()
