import pandas as pd
import json
import re
import requests
import os
from io import StringIO
from bs4 import BeautifulSoup

print("==========================================")
print("--- [1/2] RASPAGEM DE BETS (SPA/MF) ---")
print("==========================================")

# 1. Base fixa com as empresas autorizadas por Decisão Judicial
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

# 2. Carrega base existente em dados.json se houver (Preservação de Histórico)
if os.path.exists('dados.json'):
    try:
        with open('dados.json', 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    item = json.loads(line)
                    if 'cnpj' in item:
                        base_bets[item['cnpj']] = item
        print(f"Base local preservada: {len(base_bets)} registros carregados.")
    except Exception as e:
        print(f"Aviso ao ler dados.json local: {e}")

# 3. URLs Corrigidas do Portal do Governo Federal (SPA/MF)
urls_bets = [
    "https://www.gov.br/fazenda/pt-br/composicao/orgaos/secretaria-de-premios-e-apostas/lista-de-empresas/empresas-autorizadas-1/empresas-autorizadas"
]

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
}

for url in urls_bets:
    try:
        print(f"Acessando: {url}")
        res = requests.get(url, headers=headers, timeout=25)
        
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
            print(f"✅ Sucesso ao raspar SPA/MF!")
        else:
            print(f"⚠️ Erro HTTP {res.status_code} ao acessar a SPA/MF")
    except Exception as e:
        print(f"⚠️ Erro ao raspar {url}: {e}")

# Salva a base completa
with open('dados.json', 'w', encoding='utf-8') as f:
    for item in base_bets.values():
        f.write(json.dumps(item, ensure_ascii=False) + '\n')

print(f"✅ Total de {len(base_bets)} Bets salvas em dados.json!")


print("\n==========================================")
print("--- [2/2] BUSCA DE IPs (BANCO CENTRAL) ---")
print("==========================================")

# URL Oficial e Ativa de Dados Abertos do Banco Central (Olinda BCB)
url_bcb = "https://olinda.bcb.gov.br/olinda/servico/BcBase/versao/v2/odata/EntidadesSupervisionadas?$top=10000&$format=json"

try:
    print("Consultando API oficial Olinda do Banco Central...")
    resp = requests.get(url_bcb, headers=headers, timeout=30)
    print(f"Status BCB: {resp.status_code}")
    
    if resp.status_code == 200:
        dados_raw = resp.json().get('value', [])
        ips_list = []
        
        for item in dados_raw:
            cnpj_raw = str(item.get('Cnpj', item.get('CNPJ', ''))).strip()
            nome = str(item.get('NomeInstituicao', item.get('Nome', ''))).strip()
            segmento = str(item.get('Segmento', item.get('Tipo', ''))).strip()
            
            cnpj_limpo = re.sub(r'\D', '', cnpj_raw)
            
            if nome and cnpj_limpo:
                if len(cnpj_limpo) == 14:
                    cnpj_fmt = f"{cnpj_limpo[:2]}.{cnpj_limpo[2:5]}.{cnpj_limpo[5:8]}/{cnpj_limpo[8:12]}-{cnpj_limpo[12:]}"
                else:
                    cnpj_fmt = cnpj_limpo
                    
                ips_list.append({
                    "cnpj": cnpj_fmt,
                    "nome": nome,
                    "municipio": segmento if segmento else "Instituição Autorizada",
                    "status": "Autorizada a Funcionar pelo Banco Central (BCB)"
                })
        
        ips_unicas = list({e['cnpj']: e for e in ips_list}.values())
        print(f"Total de IPs salvas: {len(ips_unicas)}")
        
        with open('ips.json', 'w', encoding='utf-8') as f:
            json.dump(ips_unicas, f, ensure_ascii=False, indent=2)
            
        print("✅ ips.json salvo com sucesso!")
    else:
        print(f"⚠️ BCB retornou HTTP {resp.status_code}")
except Exception as e:
    print(f"⚠️ Erro ao consultar Banco Central: {e}")
