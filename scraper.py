import pandas as pd
import json
import re
import requests
import os
from io import StringIO
from bs4 import BeautifulSoup
from datetime import datetime

print("==========================================")
print("--- RASPAGEM DE BETS (SPA/MF) ---")
print("==========================================")

# 1. Base fixa com as Autorizações Judiciais (Garantidas)
base_bets = {
    "55.997.392/0001-05": {
        "cnpj": "55.997.392/0001-05",
        "razao_social": "ZEROUMBET PLATAFORMA DIGITAL LTDA",
        "marcas": "ZEROUM ENERGIA SPORTVIP",
        "portaria": "5007941-50.2025.4.03.6100 (Decisão Judicial)"
    },
    "57.163.072/0001-77": {
        "cnpj": "57.163.072/0001-77",
        "razao_social": "ZONA DE JOGO NEGÓCIOS E PARTICIPAÇÕES LTDA",
        "marcas": "ZONA DE JOGO APOSTAONLINE ONLYBETS",
        "portaria": "1096849-60.2025.4.01.3400 (Decisão Judicial)"
    }
}

# 2. Raspagem da tabela oficial da SPA/MF no portal gov.br
url_spa = "https://www.gov.br/fazenda/pt-br/composicao/orgaos/secretaria-de-premios-e-apostas/lista-de-empresas/empresas-autorizadas"

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
}

try:
    print(f"Acessando: {url_spa}")
    res = requests.get(url_spa, headers=headers, timeout=25)
    if res.status_code == 200:
        soup = BeautifulSoup(res.text, 'html.parser')
        tabelas = soup.find_all('table')
        
        for table in tabelas:
            try:
                df = pd.read_html(StringIO(str(table)))[0]
                df.columns = [str(col).upper().strip() for col in df.columns]
                
                for _, row in df.iterrows():
                    cnpj_raw = str(row.get('CNPJ', '')).strip()
                    razao_raw = str(row.get('DENOMINAÇÃO SOCIAL DA EMPRESA', row.get('RAZÃO SOCIAL', row.get('EMPRESA', '')))).strip()
                    marcas_raw = str(row.get('MARCAS', '')).strip()
                    portaria_raw = str(row.get('PORTARIA', row.get('INFORMAÇÕES JUDICIAIS', 'SPA/MF'))).strip()
                    
                    cnpj_limpo = re.sub(r'\D', '', cnpj_raw)
                    
                    if cnpj_limpo and len(cnpj_limpo) == 14:
                        cnpj_fmt = f"{cnpj_limpo[:2]}.{cnpj_limpo[2:5]}.{cnpj_limpo[5:8]}/{cnpj_limpo[8:12]}-{cnpj_limpo[12:]}"
                        razao = '' if razao_raw.lower() in ['nan', 'none', ''] else razao_raw
                        marcas = '' if marcas_raw.lower() in ['nan', 'none', ''] else marcas_raw
                        portaria = 'SPA/MF' if portaria_raw.lower() in ['nan', 'none', ''] else portaria_raw
                        
                        base_bets[cnpj_fmt] = {
                            "cnpj": cnpj_fmt,
                            "razao_social": razao,
                            "marcas": marcas,
                            "portaria": portaria
                        }
            except Exception:
                continue
        print("✅ Sucesso ao raspar SPA/MF!")
    else:
        print(f"⚠️ Erro HTTP {res.status_code} ao acessar a SPA/MF")
except Exception as e:
    print(f"⚠️ Erro ao raspar {url_spa}: {e}")

# 3. Salva no dados.json
with open('dados.json', 'w', encoding='utf-8') as f:
    for item in base_bets.values():
        f.write(json.dumps(item, ensure_ascii=False) + '\n')

print(f"✅ Sucesso total! {len(base_bets)} Bets salvas em dados.json!")
