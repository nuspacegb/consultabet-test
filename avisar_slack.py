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
import re
import sys
import urllib.error
import urllib.request

# ----------------------------------------------------------------------------
# CONFIGURACAO -- ajuste o endereco do site aqui
# ----------------------------------------------------------------------------

# Atencao ao "or": o GitHub Actions define a variavel como texto VAZIO quando
# ela nao existe, e texto vazio nao aciona o valor padrao do os.getenv.
# Sem o "or", o link da mensagem sai sem endereco.
URL_SITE = os.getenv("URL_SITE", "").strip() or "https://nuspacegb.github.io/consultabet/"

# ----------------------------------------------------------------------------
# MODO DE ENVIO
# ----------------------------------------------------------------------------
#
#   blocos   (padrao) Para o "Incoming Webhook" de um app do Slack.
#            Manda a mensagem formatada em blocos: titulo grande, secoes
#            separadas, links com texto clicavel. E o mais bonito.
#
#   simples  Para o Workflow Builder do Slack ou para o Zapier.
#            Esses dois nao entendem blocos -- eles recebem um campo de texto
#            e repassam. A mensagem vira texto corrido com negrito e emoji,
#            que ja fica boa.
#
# Trocar entre um e outro nao exige mexer no codigo: e so definir a variavel
# MODO_SLACK no GitHub (Settings > Secrets and variables > Actions > Variables).
# ----------------------------------------------------------------------------

MODO_SLACK = os.getenv("MODO_SLACK", "").strip().lower() or "blocos"

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


def dias_desde_alteracao(hist):
    """Ha quantos dias a lista mudou pela ultima vez. None se nao souber."""
    iso = hist.get("alterado_em_iso")
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


def montar_divulgacao(empresas, meta, hist):
    """
    Texto pronto para copiar e colar num canal com mais gente.

    E diferente do resumo pessoal: nada de "o robo parou", nada de link do
    GitHub. So o que interessa para quem nao cuida da ferramenta.
    """
    add = hist.get("adicionadas", [])
    rem = hist.get("removidas", [])
    alt = hist.get("marcas_alteradas", [])
    total = meta.get("total", len(empresas))
    atualizado = meta.get("atualizado_em", "")

    partes = ["📢 *Atualização na lista de casas de apostas autorizadas*", ""]

    if add:
        partes.append(f"*Entraram na lista ({len(add)}):*")
        partes += [f"• {n}" for n in add[:MAXIMO_NOMES]]
        if len(add) > MAXIMO_NOMES:
            partes.append(f"_… e mais {len(add) - MAXIMO_NOMES}._")
        partes.append("")
    if rem:
        partes.append(f"*Saíram da lista ({len(rem)}):*")
        partes += [f"• {n}" for n in rem[:MAXIMO_NOMES]]
        if len(rem) > MAXIMO_NOMES:
            partes.append(f"_… e mais {len(rem) - MAXIMO_NOMES}._")
        partes.append("")
    if alt:
        partes.append(f"*Mudaram de marca ({len(alt)}):*")
        partes += [f"• {a['empresa']}: {a['antes'] or '—'} → {a['depois'] or '—'}"
                   for a in alt[:MAXIMO_NOMES]]
        partes.append("")

    partes.append(
        f"São *{total}* casas autorizadas pelo Governo Federal"
        + (f", conforme lista da SPA/MF atualizada em {atualizado}." if atualizado else ".")
    )
    partes.append(f"Consulte qualquer casa por marca ou CNPJ: {URL_SITE}")

    return "\n".join(partes)


def montar_semanal(empresas, meta, hist):
    """Resumo de segunda-feira. Sai mesmo quando nada mudou."""
    add = hist.get("adicionadas", [])
    rem = hist.get("removidas", [])
    alt = hist.get("marcas_alteradas", [])
    total = meta.get("total", len(empresas))
    atualizado = meta.get("atualizado_em", "data não informada")

    # O historico.json guarda a ULTIMA alteracao, que pode ser de meses atras.
    # Sem esta checagem, o resumo repetiria a mesma novidade toda segunda.
    dias_alt = dias_desde_alteracao(hist)
    houve = bool(add or rem or alt)
    recente = houve and dias_alt is not None and dias_alt <= 7
    quando_alt = hist.get("alterado_em") or hist.get("data") or "data não registrada"

    if recente:
        pedacos = []
        if add:
            pedacos.append(f"*{len(add)}* {'entrou' if len(add) == 1 else 'entraram'}")
        if rem:
            pedacos.append(f"*{len(rem)}* {'saiu' if len(rem) == 1 else 'saíram'}")
        if alt:
            pedacos.append(f"*{len(alt)}* mudou de marca" if len(alt) == 1
                           else f"*{len(alt)}* mudaram de marca")
        linha = "Nesta semana: " + " · ".join(pedacos) + "."
        linha_simples = re.sub(r"\*", "", linha)
    elif houve:
        linha = (f"Nenhuma alteração nesta semana. A última foi em *{quando_alt}*.")
        linha_simples = f"Nenhuma alteração nesta semana. A última foi em {quando_alt}."
    else:
        linha = "Nenhuma alteração registrada até agora."
        linha_simples = linha

    blocos = [
        titulo("📊 Consulta Bet · resumo da semana"),
        texto(
            f"*{total}* casas de apostas autorizadas pelo Governo Federal.\n"
            f"{linha}"
        ),
    ]

    # Quando houve mudanca de verdade nesta semana, ja entrega o texto pronto
    # para colar num canal com mais gente. Evita reescrever na mao.
    if recente:
        if add:
            blocos.append(texto("*🟢 Entraram*\n" + lista_de_nomes(add)))
        if rem:
            blocos.append(texto("*🔴 Saíram*\n" + lista_de_nomes(rem)))
        if alt:
            blocos.append(texto("*🟣 Marcas alteradas*\n" + "\n".join(
                f"• *{a['empresa']}*: {a['antes'] or '—'} → {a['depois'] or '—'}"
                for a in alt[:MAXIMO_NOMES])))
        blocos.append({"type": "divider"})
        blocos.append(texto(
            "📋 *Texto pronto para copiar no canal aberto* — copie daqui para baixo:"
        ))
        blocos.append(texto(montar_divulgacao(empresas, meta, hist)))
        blocos.append({"type": "divider"})

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


def montar_execucao(empresas, meta, hist, desfecho, url_log, ok=True):
    """
    Retorno de uma execucao que VOCE disparou na mao.

    Diferente do resumo semanal: aqui o que interessa e "o que acabou de
    acontecer e o que eu preciso fazer agora", nao o panorama.
    """
    total = meta.get("total", len(empresas))
    atualizado = meta.get("atualizado_em", "")

    icone = "✅" if ok else "⚠️"
    blocos = [
        titulo(f"{icone} Execução manual do robô da base"),
        texto(desfecho),
    ]

    detalhes = [f"*{total}* casas na base"]
    if atualizado:
        detalhes.append(f"lista oficial atualizada em *{atualizado}*")
    dias = dias_desde_verificacao(meta)
    if dias is not None:
        detalhes.append("verificada " + ("hoje" if dias == 0 else
                                         "ontem" if dias == 1 else f"há {dias} dias"))
    blocos.append(contexto(" · ".join(detalhes)))

    blocos.append({"type": "divider"})
    blocos.append(contexto(
        f"<{url_log}|Ver o log completo> · <{URL_SITE}|Abrir o Consulta Bet>"
    ))

    return {"text": f"Execução manual: {desfecho[:140]}", "blocks": blocos}


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

def texto_puro(txt):
    """
    Tira toda a formatacao do Slack de um trecho de texto.

    Isso e necessario no modo 'simples' porque o Workflow Builder insere o
    conteudo da variavel COMO TEXTO LITERAL. Ele nao interpreta *negrito*
    nem <link|rotulo> -- entao esses simbolos apareceriam crus na mensagem.

    Sem negrito disponivel, a hierarquia vem de outro lugar: MAIUSCULA nos
    titulos, linha em branco entre os blocos, e o emoji como marcador.
    """
    # <https://site.com|Abrir o site>  ->  Abrir o site: https://site.com
    txt = re.sub(r"<(https?://[^|>]+)\|([^>]+)>", r"\2: \1", txt)
    # <https://site.com>  ->  https://site.com
    txt = re.sub(r"<(https?://[^>]+)>", r"\1", txt)
    # *negrito* e _italico_ -> texto normal
    txt = re.sub(r"\*([^*\n]+)\*", r"\1", txt)
    txt = re.sub(r"_([^_\n]+)_", r"\1", txt)
    return txt


def achatar(mensagem):
    """
    Transforma a mensagem em blocos numa unica string de texto limpa,
    pronta para o Workflow Builder ou para o Zapier.
    """
    linhas = []
    for b in mensagem.get("blocks", []):
        tipo = b.get("type")
        if tipo == "divider":
            continue
        if tipo == "header":
            # sem negrito disponivel, o titulo vira maiuscula
            linhas.append(texto_puro(b["text"]["text"]).upper())
        elif tipo == "section":
            linhas.append(texto_puro(b["text"]["text"]))
        elif tipo == "context":
            limpo = texto_puro(" ".join(e["text"] for e in b.get("elements", [])))
            # Sem o rotulo clicavel, o endereco inteiro aparece. Dois deles na
            # mesma linha viram uma parede -- entao cada um ganha sua linha.
            if limpo.count("http") >= 2:
                limpo = limpo.replace(" · ", "\n")
            linhas.append(limpo)
    return "\n\n".join(l.strip() for l in linhas if l.strip())


def para_markdown(mensagem):
    """
    Converte a mensagem para Markdown de verdade (o do GitHub).

    Usado no corpo da issue que vira e-mail. A sintaxe do Slack e parecida
    mas nao igual: la o negrito e *assim*, aqui e **assim**; la o link e
    <endereco|rotulo>, aqui e [rotulo](endereco).
    """
    linhas = []
    for b in mensagem.get("blocks", []):
        tipo = b.get("type")
        if tipo == "divider":
            linhas.append("---")
            continue

        if tipo == "header":
            bruto, prefixo, sufixo = b["text"]["text"], "## ", ""
        elif tipo == "section":
            bruto, prefixo, sufixo = b["text"]["text"], "", ""
        elif tipo == "context":
            bruto = " ".join(e["text"] for e in b.get("elements", []))
            prefixo, sufixo = "", ""
        else:
            continue

        t = re.sub(r"<(https?://[^|>]+)\|([^>]+)>", r"[\2](\1)", bruto)
        t = re.sub(r"<(https?://[^>]+)>", r"\1", t)
        t = re.sub(r"\*([^*\n]+)\*", r"**\1**", t)   # negrito do Slack -> do Markdown
        t = re.sub(r"_([^_\n]+)_", r"*\1*", t)       # italico
        linhas.append(prefixo + t + sufixo)

    return "\n\n".join(l.strip() for l in linhas if l.strip())


def montar_corpo(mensagem):
    """Decide o formato do que vai ser enviado, conforme MODO_SLACK."""
    if MODO_SLACK == "simples":
        texto_puro = achatar(mensagem)
        # Manda o mesmo conteudo em varios nomes de campo porque cada
        # ferramenta espera um: o Workflow Builder costuma usar uma variavel
        # nomeada, e o Zapier deixa voce escolher qual campo usar.
        return {"texto": texto_puro, "text": texto_puro, "mensagem": texto_puro}
    return mensagem


def enviar(mensagem):
    url = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    if not url:
        print("ERRO: a variavel SLACK_WEBHOOK_URL nao esta definida.")
        print("      No GitHub: Settings > Secrets and variables > Actions > New secret.")
        sys.exit(1)

    print(f"Modo de envio: {MODO_SLACK}")
    corpo = json.dumps(montar_corpo(mensagem), ensure_ascii=False).encode("utf-8")
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
    p.add_argument("tipo", choices=["mudancas", "semanal", "aviso", "falha",
                                    "divulgacao", "execucao"])
    p.add_argument("--texto", default="", help="corpo da mensagem (so para 'aviso')")
    p.add_argument("--assunto", default="Novidade no Consulta Bet",
                   help="titulo da mensagem (so para 'aviso')")
    p.add_argument("--log", default="", help="link do log da execucao")
    p.add_argument("--desfecho", default="", help="o que aconteceu (so para 'execucao')")
    p.add_argument("--alerta", action="store_true",
                   help="marca a execucao como problematica (so para 'execucao')")
    p.add_argument("--simular", action="store_true",
                   help="monta a mensagem e imprime, sem enviar nada")
    p.add_argument("--markdown", action="store_true",
                   help="imprime em Markdown (para o corpo da issue), sem enviar")
    p.add_argument("--titulo-issue", action="store_true",
                   help="imprime so uma linha de resumo, para o titulo da issue")
    args = p.parse_args()

    empresas, meta, hist = carregar()

    # 'divulgacao' nao e mensagem de Slack: e o texto pronto para voce colar
    # num canal com mais gente. Sempre sai em texto puro.
    if args.tipo == "divulgacao":
        print(montar_divulgacao(empresas, meta, hist))
        return

    if args.tipo == "mudancas":
        msg = montar_mudancas(empresas, meta, hist)
        if msg is None:
            print("Nenhuma mudanca no historico. Nada a anunciar.")
            return
    elif args.tipo == "semanal":
        msg = montar_semanal(empresas, meta, hist)
    elif args.tipo == "execucao":
        msg = montar_execucao(empresas, meta, hist,
                              args.desfecho.strip() or "Execução concluída.",
                              args.log or URL_SITE,
                              ok=not args.alerta)
    elif args.tipo == "falha":
        msg = montar_falha(meta, args.log or URL_SITE)
    else:
        if not args.texto.strip():
            print("ERRO: o aviso precisa de um texto. Use --texto \"sua mensagem\".")
            sys.exit(1)
        msg = montar_aviso(empresas, meta, args.texto.strip(), args.assunto.strip())

    # Uma linha so, para virar titulo de issue / assunto de e-mail
    if args.titulo_issue:
        print(msg.get("text", "Consulta Bet"))
        return

    if args.markdown:
        print(para_markdown(msg))
        return

    if args.simular:
        if MODO_SLACK == "simples":
            print("--- modo simples: e isto que chega no canal ---\n")
            print(achatar(msg))
        else:
            print(json.dumps(montar_corpo(msg), ensure_ascii=False, indent=2))
        return

    enviar(msg)
    print("Mensagem enviada.")


if __name__ == "__main__":
    main()
