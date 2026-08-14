import pandas as pd
import json
import re
import requests

# URLs oficiais da Secretaria de Prêmios e Apostas (SPA/MF)
urls = [
    "https://www.gov.br/fazenda/pt-br/composicao/orgaos/secretaria-de-premios-e-apostas/lista-de-empresas/empresas-autorizadas-1/empresas-autorizadas",
    "https://www.gov.br/fazenda/pt-br/composicao/orgaos/secretaria-de-premios-e-apostas/lista-de-empresas/empresas-autorizadas-1/processos-administrativos"
]

empresas_extraidas = []
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

for url in urls:
    try:
        print(f"Acessando: {url}...")
        
        # Tenta capturar a data de atualização dinâmica exibida no site
        data_atualizacao_gov = "14/08/2026"  # Fallback caso a busca regex falhe
        resposta = requests.get(url, headers=headers, timeout=15)
        
        if resposta.status_code == 200:
            match = re.search(r'Atualizado em\s*(\d{2}/\d{2}/\d{4})', resposta.text)
            if match:
                data_atualizacao_gov = match.group(1)

        # Extrai todas as tabelas HTML presentes na página
        tabelas = pd.read_html(url)
        for df in tabelas:
            # Normaliza os nomes das colunas para caixa alta
            df.columns = [str(col).upper().strip() for col in df.columns]
            
            for _, row in df.iterrows():
                cnpj = str(row.get('CNPJ', '')).strip()
                razao = str(row.get('DENOMINAÇÃO SOCIAL DA EMPRESA', row.get('RAZÃO SOCIAL', ''))).strip()
                marcas = str(row.get('MARCAS', '')).strip()
                portaria = str(row.get('PORTARIA', row.get('INFORMAÇÕES JUDICIAIS', 'SPA/MF'))).strip()
                requerimento = str(row.get('REQUERIMENTO', 'N/A')).strip()
                
                # Trata campos nulos/nan
                razao = '' if razao.lower() == 'nan' else razao
                marcas = '' if marcas.lower() == 'nan' else marcas
                portaria = 'SPA/MF' if portaria.lower() == 'nan' or not portaria else portaria
                requerimento = 'N/A' if requerimento.lower() == 'nan' or not requerimento else requerimento
                
                # Valida se possui um CNPJ com 14 dígitos numéricos
                cnpj_limpo = re.sub(r'\D', '', cnpj)
                if cnpj_limpo and len(cnpj_limpo) == 14:
                    empresa = {
                        "cnpj": cnpj,
                        "razao_social": razao,
                        "marcas": marcas,
                        "portaria": portaria,
                        "requerimento": requerimento,
                        "data_publicacao": "20/07/2026",
                        "data_atualizacao": data_atualizacao_gov
                    }
                    empresas_extraidas.append(empresa)

    except Exception as e:
        print(f"Aviso ao processar {url}: {e}")

# Processa e salva o arquivo final dados.json
if empresas_extraidas:
    # Deduplica empresas garantindo chave única pelo CNPJ
    empresas_unicas = list({e['cnpj']: e for e in empresas_extraidas}.values())
    
    with open('dados.json', 'w', encoding='utf-8') as f:
        for item in empresas_unicas:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
            
    print(f"✅ Sucesso! {len(empresas_unicas)} empresas processadas e salvas em dados.json.")
else:
    print("⚠️ Nenhuma empresa encontrada nas tabelas raspadas.")
