import pandas as pd
import json
import re
import requests
import os
from datetime import datetime

# ==========================================
# PARTE 1: SCRAPER CASAS DE APOSTAS (SPA/MF)
# ==========================================
print("--- Iniciando raspagem de Bets (SPA/MF) ---")

urls_bets = [
    "https://www.gov.br/fazenda/pt-br/composicao/orgaos/secretaria-de-premios-e-apostas/lista-de-empresas/empresas-autorizadas-1/empresas-autorizadas",
    "https://www.gov.br/fazenda/pt-br/composicao/orgaos/secretaria-de-premios-e-apostas/lista-de-empresas/empresas-autorizadas-1/processos-administrativos"
]

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

# Carrega histórico antigo para comparação (Diff)
dados_antigos = []
if os.path.exists('dados.json'):
    try:
        with open('dados.json', 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    dados_antigos.append(json.loads(line))
    except Exception as e:
        print(f"Aviso ao ler dados.json antigo: {e}")

cnpjs_antigos = {e['cnpj']: e.get('razao_social', '') for e in dados_antigos if 'cnpj' in e}

empresas_extraidas = {}

for url in urls_bets:
    try:
        print(f"Acessando: {url}")
        tabelas = pd.read_html(url)
        for df in tabelas:
            df.columns = [str(col).upper().strip() for col in df.columns]
            
            for _, row in df.iterrows():
                # Tenta localizar colunas equivalentes
                cnpj_raw = str(row.get('CNPJ', '')).strip()
                razao_raw = str(row.get('DENOMINAÇÃO SOCIAL DA EMPRESA', row.get('RAZÃO SOCIAL', ''))).strip()
                marcas_raw = str(row.get('MARCAS', '')).strip()
                portaria_raw = str(row.get('PORTARIA', row.get('INFORMAÇÕES JUDICIAIS', 'SPA/MF'))).strip()
                
                cnpj_limpo = re.sub(r'\D', '', cnpj_raw)
                
                if cnpj_limpo and len(cnpj_limpo) == 14:
                    razao = '' if razao_raw.lower() in ['nan', 'none', ''] else razao_raw
                    marcas = '' if marcas_raw.lower() in ['nan', 'none', ''] else marcas_raw
                    portaria = 'SPA/MF' if portaria_raw.lower() in ['nan', 'none', ''] else portaria_raw
                    
                    # Formata CNPJ xx.xxx.xxx/xxxx-xx
                    cnpj_formatado = f"{cnpj_limpo[:2]}.{cnpj_limpo[2:5]}.{cnpj_limpo[5:8]}/{cnpj_limpo[8:12]}-{cnpj_limpo[12:]}"
                    
                    empresas_extraidas[cnpj_formatado] = {
                        "cnpj": cnpj_formatado,
                        "razao_social": razao,
                        "marcas": marcas,
                        "portaria": portaria
                    }
    except Exception as e:
        print(f"Erro ao raspar {url}: {e}")

if empresas_extraidas:
    # Registra alterações para o historico.json
    cnpjs_novos = {e['cnpj']: e['razao_social'] for e in empresas_extraidas.values()}
    adicionadas = [f"{razao if razao else 'Empresa'} ({cnpj})" for cnpj, razao in cnpjs_novos.items() if cnpj not in cnpjs_antigos]
    removidas = [f"{razao if razao else 'Empresa'} ({cnpj})" for cnpj, razao in cnpjs_antigos.items() if cnpj not in cnpjs_novos]
    
    registro_historico = {
        "data": datetime.now().strftime("%d/%m/%Y"),
        "adicionadas": adicionadas,
        "removidas": removidas,
        "total_adicionadas": len(adicionadas),
        "total_removidas": len(removidas)
    }
    
    with open('historico.json', 'w', encoding='utf-8') as f:
        json.dump(registro_historico, f, ensure_ascii=False, indent=2)
        
    with open('dados.json', 'w', encoding='utf-8') as f:
        for item in empresas_extraidas.values():
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
            
    print(f"✅ {len(empresas_extraidas)} Bets salvas em dados.json!")
else:
    print("⚠️ Nenhuma empresa de aposta encontrada. MANTENDO BASE ANTERIOR.")


# ==========================================
# PARTE 2: INSTITUIÇÕES DE PAGAMENTO (BCB)
# ==========================================
print("\n--- Buscando Instituições de Pagamento no Banco Central ---")

url_bcb = "https://olinda.bcb.gov.br/olinda/servico/BcBase_v2/versao/v1/odata/EntidadesBancariasEnquadramento?$top=2000&$format=json"

try:
    resp = requests.get(url_bcb, headers=headers, timeout=30)
    if resp.status_code == 200:
        dados_bcb = resp.json().get('value', [])
        ips_list = []
        
        for item in dados_bcb:
            cnpj_raw = str(item.get('codigoCNPJ14', item.get('codigoCNPJ8', ''))).strip()
            nome = str(item.get('nomeEntidadeInteresse', '')).strip()
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
        
        # Deduplica IPs pelo CNPJ
        ips_unicas = list({e['cnpj']: e for e in ips_list}.values())
        
        with open('ips.json', 'w', encoding='utf-8') as f:
            json.dump(ips_unicas, f, ensure_ascii=False, indent=2)
            
        print(f"✅ {len(ips_unicas)} IPs do Banco Central salvas em ips.json!")
    else:
        print(f"⚠️ API BCB retornou status {resp.status_code}")
except Exception as e:
    print(f"⚠️ Erro ao consultar API do Banco Central: {e}")
