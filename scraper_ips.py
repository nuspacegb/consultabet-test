Run if [ -n "$DATA" ]; then
======================================================================
  NU - CONSULTA  |  Instituicoes de Pagamento (BCB)
  Execucao: 11/09/2026 22:11 (horario de Brasilia)
======================================================================
  IPv4 forcado: sim

----------------------------------------------------------------------
  CATALOGO: quais recursos esta API oferece
----------------------------------------------------------------------
  GET https://olinda.bcb.gov.br/olinda/servico/BcBase/versao/v2/odata/   ->  HTTP 200
  {"@odata.context":"https://olinda.bcb.gov.br/olinda/servico/BcBase/versao/v2/odata/$metadata","value":[{"name":"ClasseCooperativa","url":"ClasseCooperativa"},{"


----------------------------------------------------------------------
  ESQUEMA ($metadata): parametros que cada recurso exige
----------------------------------------------------------------------
  GET https://olinda.bcb.gov.br/olinda/servico/BcBase/versao/v2/odata/$metadata   ->  HTTP 200

  <EntityType Name="TipoEntidadeSupervisionada">
  <EntityType Name="CategoriaCooperativa">
  <EntityType Name="ClasseCooperativa">
  <EntityType Name="NaturezaJuridica">
  <EntityType Name="EntidadeSupervisionada">
  <EntityType Name="TipoCooperativa">
  <EntityType Name="Cooperativa">
  <EntityType Name="EsferaPublica">
  <EntityType Name="TipoSituacaoPessoaJuridica">
  <Function Name="EntidadesSupervisionadas" IsComposable="true">
  <Parameter Name="dataBase" Type="Edm.String" Nullable="false"/>
  <Function Name="Cooperativas" IsComposable="true">
  <Parameter Name="dataBase" Type="Edm.String" Nullable="false"/>
  <EntitySet Name="ClasseCooperativa" EntityType="br.gov.bcb.olinda.servico.BcBase.ClasseCooperativa"/>
  <EntitySet Name="_Cooperativas" EntityType="br.gov.bcb.olinda.servico.BcBase.Cooperativa"/>
  <EntitySet Name="TipoCooperativa" EntityType="br.gov.bcb.olinda.servico.BcBase.TipoCooperativa"/>
  <EntitySet Name="_EntidadesSupervisionadas" EntityType="br.gov.bcb.olinda.servico.BcBase.EntidadeSupervisionada"/>
  <EntitySet Name="CategoriaCooperativa" EntityType="br.gov.bcb.olinda.servico.BcBase.CategoriaCooperativa"/>
  <EntitySet Name="TipoSituacaoPessoaJuridica" EntityType="br.gov.bcb.olinda.servico.BcBase.TipoSituacaoPessoaJuridica"/>
  <EntitySet Name="TipoEntidadeSupervisionada" EntityType="br.gov.bcb.olinda.servico.BcBase.TipoEntidadeSupervisionada"/>
  <EntitySet Name="NaturezaJuridica" EntityType="br.gov.bcb.olinda.servico.BcBase.NaturezaJuridica"/>
  <EntitySet Name="EsferaPublica" EntityType="br.gov.bcb.olinda.servico.BcBase.EsferaPublica"/>
  <FunctionImport Name="Cooperativas" Function="br.gov.bcb.olinda.servico.BcBase.Cooperativas" EntitySet="br.gov.bcb.olinda.servico.BcBase._Cooperativas" IncludeInServiceDocument="tr
  <FunctionImport Name="EntidadesSupervisionadas" Function="br.gov.bcb.olinda.servico.BcBase.EntidadesSupervisionadas" EntitySet="br.gov.bcb.olinda.servico.BcBase._EntidadesSupervisi

  Parametros encontrados no esquema: dataBase

----------------------------------------------------------------------
  TIPOS DE ENTIDADE SUPERVISIONADA (catalogo do BCB)
----------------------------------------------------------------------
  36 tipos cadastrados. Os que mencionam 'pagamento':

    codigo    ?  Instituidor de Arranjo de Pagamento
    codigo    ?  Instituição de Pagamento não sujeita a autorização pelo BCB
    codigo    ?  Instituição de Pagamento  <-- E O NOSSO


----------------------------------------------------------------------
  PROCURANDO A BASE MAIS RECENTE
----------------------------------------------------------------------
  ✓ Base encontrada: 11/09/2026
    211 registros
    campo 'database' na resposta: 2026-09-11
    URL: https://olinda.bcb.gov.br/olinda/servico/BcBase/versao/v2/odata/EntidadesSupervisionadas(dataBase=@dataBase)?@dataBase='09/11/2026'&$format=json&$top=5000&$filter=descricaoTipoEntidadeSupervisionada%20eq%20'Institui%C3%A7%C3%A3o%20de%20Pagamento'

----------------------------------------------------------------------
  O QUE VEIO NA RESPOSTA
----------------------------------------------------------------------
  Chamada: dataBase=11/09/2026
  URL:     https://olinda.bcb.gov.br/olinda/servico/BcBase/versao/v2/odata/EntidadesSupervisionadas(dataBase=@dataBase)?@dataBase='09/11/2026'&$format=json&$top=5000&$filter=descricaoTipoEntidadeSupervisionada%20eq%20'Institui%C3%A7%C3%A3o%20de%20Pagamento'
  Total:   211 registros

  Tipos de entidade presentes:
       211  Instituição de Pagamento   <-- e o que queremos

  Instituicoes de Pagamento: 211

  Conferencia de contagem:
  211 registros recebidos da API
  nenhum registro descartado
  211 na base final

  Situacao das IPs (ATENCAO: nem toda IP na base esta autorizada):
       195  Autorizada em Atividade             -> status: autorizada
         7  Cancelada/Encerrada                 -> status: cancelada
         7  Autorizada sem Atividade            -> status: autorizada_sem_atividade
         2  Em Liquidação Extrajudicial         -> status: cancelada

  Campos disponiveis em cada registro:
    codigoCNPJ14                                  = 35523352000106
    codigoCNPJ8                                   = 35523352
    codigoDoMunicipioNoIBGE                       = 3550308
    codigoEsferaPublica                           = None
    codigoIdentificadorBacen                      = Z9215259
    codigoNaturezaJuridica                        = 35
    codigoSisbacen                                = 00179
    codigoTipoEntidadeSupervisionada              = 41
    codigoTipoSituacaoPessoaJuridica              = 3
    database                                      = 2026-09-11
    descricaoNaturezaJuridica                     = Sociedade Empresária Limitada
    descricaoTipoEntidadeSupervisionada           = Instituição de Pagamento
    descricaoTipoSituacaoPessoaJuridica           = Autorizada em Atividade
    indicadorEsferaPublica                        = 2
    nomeDaUnidadeFederativa                       = São Paulo
    nomeDoMunicipio                               = São Paulo
    nomeDoPais                                    = Brasil
    nomeEntidadeInteresse                         = BEES INSTITUICAO DE PAGAMENTO LTDA.
    nomeEntidadeInteresseNaoFormatado             = BEES INSTITUICAO DE PAGAMENTO LTDA.
    nomeFantasia                                  = None
    nomeReduzido                                  = BEES IP LTDA.
    siglaDaPessoaJuridica                         = None
    siglaISO3digitos                              = BRA

  Exemplo ja tratado pelo script:
{
  "cnpj": "35.523.352/0001-06",
  "cnpj_raiz": "35523352",
  "razao_social": "BEES INSTITUICAO DE PAGAMENTO LTDA.",
  "nomes": "BEES IP LTDA.",
  "tipo": "Instituição de Pagamento",
  "natureza_juridica": "Sociedade Empresária Limitada",
  "situacao": "Autorizada em Atividade",
  "status": "autorizada",
  "municipio": "São Paulo",
  "uf": "São Paulo",
  "codigo_bacen": "Z9215259"
}

  Primeiras 10:
    35.523.352/0001-06  BEES INSTITUICAO DE PAGAMENTO LTDA.
    12.481.100/0001-66  BIZ INSTITUIÇÃO DE PAGAMENTO S.A.
    12.102.128/0001-45  SAFETYPAY BRASIL INSTITUICAO DE PAGAMENTO LTDA
    31.531.997/0001-30  CONPAY INSTITUIÇÃO DE PAGAMENTO E TECNOLOGIA S.A
    35.713.491/0001-00  PROTOTYPE INSTITUICAO DE PAGAMENTO S.A.
    39.696.395/0001-44  CACTVS INSTITUICAO DE PAGAMENTO S.A
    22.121.209/0001-46  STRIPE BRASIL SOLUCOES DE PAGAMENTO INSTITUICAO DE PAGA
    30.944.783/0001-22  PAGPRIME INSTITUICAO DE PAGAMENTO LTDA
    32.219.232/0001-21  NUPAY FOR BUSINESS INSTITUICAO DE PAGAMENTO LTDA.
    44.154.779/0001-75  LEND INSTITUICAO DE PAGAMENTO LTDA

======================================================================
  Mande este log para o Claude.
======================================================================
