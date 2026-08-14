import pandas as pd
import json
import re

# URLs oficiais do Governo Federal (SPA/MF)
urls = [
    "https://www.gov.br/fazenda/pt-br/composicao/orgaos/secretaria-de-premios-e-apostas/lista-de-empresas/empresas-autorizadas-1/empresas-autorizadas",
    "https://www.gov.br/fazenda/pt-br/composicao/orgaos/secretaria-de-premios-e-apostas/lista-de-empresas/empresas-autorizadas-1/processos-administrativos"
]

empresas_extraidas = []

for url in urls:
    try:
        # Lê todas as tabelas HTML presentes na página
        tabelas = pd.read_html(url)
        for df in tabelas:
            # Normaliza os cabeçalhos das colunas
            df.columns = [str(col).upper().strip() for col in df.columns]
            
            for _, row in df.iterrows():
                # Tenta localizar as colunas pelos nomes comuns usados no site
                cnpj = str(row.get('CNPJ', '')).strip()
                razao = str(row.get('DENOMINAÇÃO SOCIAL DA EMPRESA', row.get('RAZÃO SOCIAL', ''))).strip()
                marcas = str(row.get('MARCAS', '')).strip()
                portaria = str(row.get('PORTARIA', row.get('INFORMAÇÕES JUDICIAIS', 'SPA/MF'))).strip()
                requerimento = str(row.get('REQUERIMENTO', 'N/A')).strip()
                
                # Garante que só pega linhas que possuem um CNPJ válido
                if cnpj and cnpj != 'nan' and len(re.sub(r'\D', '', cnpj)) == 14:
                    empresa = {
                        "cnpj": cnpj,
                        "razao_social": razao,
                        "marcas": marcas if marcas != 'nan' else '',
                        "portaria": portaria if portaria != 'nan' else 'SPA/MF',
                        "requerimento": requerimento if requerimento != 'nan' else 'N/A'
                    }
                    empresas_extraidas.append(empresa)
    except Exception as e:
        print(f"Erro ao processar {url}: {e}")

# Se conseguiu extrair dados, atualiza o dados.json em linha única
if empresas_extraidas:
    # Remove duplicados com base no CNPJ
    empresas_unicas = {e['cnpj']: e for e in empresas_extraidas}.values()
    
    with open('dados.json', 'w', encoding='utf-8') as f:
        for item in empresas_unicas:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
    print(f"Sucesso! {len(empresas_unicas)} empresas atualizadas no dados.json.")
else:
    print("Nenhuma empresa foi encontrada para atualizar.")
