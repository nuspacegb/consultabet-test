import pandas as pd
import json
import re
import requests
import os
from datetime import datetime

urls = [
    "https://www.gov.br/fazenda/pt-br/composicao/orgaos/secretaria-de-premios-e-apostas/lista-de-empresas/empresas-autorizadas-1/empresas-autorizadas",
    "https://www.gov.br/fazenda/pt-br/composicao/orgaos/secretaria-de-premios-e-apostas/lista-de-empresas/empresas-autorizadas-1/processos-administrativos"
]

headers = {'User-Agent': 'Mozilla/5.0'}

# 1. Carrega os dados antigos para comparação
dados_antigos = []
if os.path.exists('dados.json'):
    try:
        with open('dados.json', 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    dados_antigos.append(json.loads(line))
    except Exception as e:
        print(f"Aviso ao ler dados.json antigo: {e}")

cnpjs_antigos = {e['cnpj']: e['razao_social'] for e in dados_antigos if 'cnpj' in e}

# 2. Raspa os dados novos do Governo
empresas_novas = []
for url in urls:
    try:
        tabelas = pd.read_html(url)
        for df in tabelas:
            df.columns = [str(col).upper().strip() for col in df.columns]
            for _, row in df.iterrows():
                cnpj = str(row.get('CNPJ', '')).strip()
                razao = str(row.get('DENOMINAÇÃO SOCIAL DA EMPRESA', row.get('RAZÃO SOCIAL', ''))).strip()
                marcas = str(row.get('MARCAS', '')).strip()
                portaria = str(row.get('PORTARIA', row.get('INFORMAÇÕES JUDICIAIS', 'SPA/MF'))).strip()
                
                cnpj_limpo = re.sub(r'\D', '', cnpj)
                if cnpj_limpo and len(cnpj_limpo) == 14:
                    empresa = {
                        "cnpj": cnpj,
                        "razao_social": razao if razao.lower() != 'nan' else '',
                        "marcas": marcas if marcas.lower() != 'nan' else '',
                        "portaria": portaria if portaria.lower() != 'nan' else 'SPA/MF'
                    }
                    empresas_novas.append(empresa)
    except Exception as e:
        print(f"Erro ao acessar {url}: {e}")

if empresas_novas:
    empresas_novas_dict = {e['cnpj']: e for e in empresas_novas}
    cnpjs_novos = {e['cnpj']: e['razao_social'] for e in empresas_novas_dict.values()}
    
    # 3. Compara Diferenças (Diff)
    adicionadas = [f"{razao} ({cnpj})" for cnpj, razao in cnpjs_novos.items() if cnpj not in cnpjs_antigos]
    removidas = [f"{razao} ({cnpj})" for cnpj, razao in cnpjs_antigos.items() if cnpj not in cnpjs_novos]
    
    data_hoje = datetime.now().strftime("%d/%m/%Y")
    
    # Prepara o registro de histórico
    registro_historico = {
        "data": data_hoje,
        "adicionadas": adicionadas,
        "removidas": removidas,
        "total_adicionadas": len(adicionadas),
        "total_removidas": len(removidas)
    }
    
    # Salva o historico.json
    with open('historico.json', 'w', encoding='utf-8') as f:
        json.dump(registro_historico, f, ensure_ascii=False, indent=2)
        
    # Salva a nova base dados.json
    with open('dados.json', 'w', encoding='utf-8') as f:
        for item in empresas_novas_dict.values():
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
            
    print(f"✅ Atualizado! +{len(adicionadas)} adicionadas, -{len(removidas)} removidas.")
