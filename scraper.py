import pandas as pd
import json
import re
import requests
import os
from io import StringIO
from datetime import datetime

print("--- [1/2] Iniciando Raspagem de Bets (SPA/MF) ---")

# 1. Empresas Judiciais (Garantidas na base)
empresas_judiciais = [
    {
        "cnpj": "55.997.392/0001-05",
        "razao_social": "ZEROUMBET PLATAFORMA DIGITAL LTDA",
        "marcas": "ZEROUM ENERGIA SPORTVIP",
        "portaria": "5007941-50.2025.4.03.6100 (Decisão Judicial)"
    },
    {
        "cnpj": "57.163.072/0001-77",
        "razao_social": "ZONA DE JOGO NEGÓCIOS E PARTICIPAÇÕES LTDA",
        "marcas": "ZONA DE JOGO APOSTAONLINE ONLYBETS",
        "portaria": "1096849-60.2025.4.01.3400 (Decisão Judicial)"
    }
]

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7'
}

urls_bets = [
    "https://www.gov.br/fazenda/pt-br/composicao/orgaos/secretaria-de-premios-e-apostas/lista-de-empresas/empresas-autorizadas-1/empresas-autorizadas",
    "https://www.gov.br/fazenda/pt-br/composicao/orgaos/secretaria-de-premios-e-apostas/lista-de-empresas/empresas-autorizadas-1/processos-administrativos"
]

empresas_extraidas = {}

# Insere judiciais primeiro
for emp in empresas_judiciais:
    empresas_extraidas[emp['cnpj']] = emp

# Baixa as páginas do gov.br
for url in urls_bets:
    try:
        print(f"Buscando: {url}")
        res = requests.get(url, headers=headers, timeout=20)
        
        if res.status_code == 200:
            # Usa StringIO para evitar warnings de depreciação no Pandas
            tabelas = pd.read_html(StringIO(res.text))
            
            for df in tabelas:
                df.columns = [str(col).upper().strip() for col in df.columns]
                
                for _, row in df.iterrows():
                    cnpj_raw = str(row.get('CNPJ', '')).strip()
                    razao_raw = str(row.get('DENOMINAÇÃO SOCIAL DA EMPRESA', row.get('RAZÃO SOCIAL', ''))).strip()
                    marcas_raw = str(row.get('MARCAS', '')).strip()
                    portaria_raw = str(row.get('PORTARIA', row.get('INFORMAÇÕES JUDICIAIS', 'SPA/MF'))).strip()
                    
                    cnpj_limpo = re.sub(r'\D', '', cnpj_raw)
                    
                    if cnpj_limpo and len(cnpj_limpo) == 14:
                        razao = '' if razao_raw.lower() in ['nan', 'none', ''] else razao_raw
                        marcas = '' if marcas_raw.lower() in ['nan', 'none', ''] else marcas_raw
                        portaria = 'SPA/MF' if portaria_raw.lower() in ['nan', 'none', ''] else portaria_raw
                        
                        cnpj_fmt = f"{cnpj_limpo[:2]}.{cnpj_limpo[2:5]}.{cnpj_limpo[5:8]}/{cnpj_limpo[8:12]}-{cnpj_limpo[12:]}"
                        
                        empresas_extraidas[cnpj_fmt] = {
                            "cnpj": cnpj_fmt,
                            "razao_social": razao,
                            "marcas": marcas,
                            "portaria": portaria
                        }
        else:
            print(f"⚠️ Erro ao acessar gov.br (Status Code: {res.status_code})")
    except Exception as e:
        print(f"⚠️ Erro no processamento de {url}: {e}")

# Salva dados.json
if len(empresas_extraidas) > 0:
    with open('dados.json', 'w', encoding='utf-8') as f:
        for item in empresas_extraidas.values():
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
            
    print(f"✅ Sucesso! {len(empresas_extraidas)} Bets salvas em dados.json!")


print("\n--- [2/2] Buscando Instituições de Pagamento no Banco Central ---")

url_bcb = "https://olinda.bcb.gov.br/olinda/servico/BcBase_v2/versao/v1/odata/EntidadesBancariasEnquadramento?$top=10000&$format=json"

try:
    headers_bcb = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json'
    }
    
    resp = requests.get(url_bcb, headers=headers_bcb, timeout=30)
    
    if resp.status_code == 200:
        dados_raw = resp.json().get('value', [])
        ips_list = []
        
        for item in dados_raw:
            cnpj_raw = str(item.get('codigoCNPJ14', item.get('codigoCNPJ8', ''))).strip()
            nome = str(item.get('nomeEntidadeInteresse', item.get('nomeEntidadeInteresseNaoFormatado', ''))).strip()
            municipio = str(item.get('nomeDoMunicipio', '')).strip()
            uf = str(item.get('nomeDaUnidadeDaFederacao', '')).strip()
            
            cnpj_limpo = re.sub(r'\D', '', cnpj_raw)
            
            if nome and cnpj_limpo:
                if len(cnpj_limpo) == 14:
                    cnpj_fmt = f"{cnpj_limpo[:2]}.{cnpj_limpo[2:5]}.{cnpj_limpo[5:8]}/{cnpj_limpo[8:12]}-{cnpj_limpo[12:]}"
                else:
                    cnpj_fmt = cnpj_limpo
                    
                ips_list.append({
                    "cnpj": cnpj_fmt,
                    "nome": nome,
                    "municipio": f"{municipio}/{uf}" if municipio and uf else municipio,
                    "status": "Autorizada a Funcionar pelo Banco Central (BCB)"
                })
        
        ips_unicas = list({e['cnpj']: e for e in ips_list}.values())
        
        with open('ips.json', 'w', encoding='utf-8') as f:
            json.dump(ips_unicas, f, ensure_ascii=False, indent=2)
            
        print(f"✅ Sucesso! {len(ips_unicas)} Instituições de Pagamento salvas em ips.json!")
    else:
        print(f"⚠️ API BCB retornou status {resp.status_code}")
except Exception as e:
    print(f"⚠️ Erro ao consultar Banco Central: {e}")
