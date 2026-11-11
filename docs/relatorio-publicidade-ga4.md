# Relatório de publicidade do Portal Trivox no Google Analytics

O portal envia `view_promotion` para exibições de banners e `select_promotion`
para cliques. Cada evento identifica a campanha, a arte e o espaço ocupado.
Usamos os campos de promoções do GA4; não é necessário criar dimensões
personalizadas nem conectar o Analytics ao WhatsApp.

## Gerar um resumo do período

1. Entre no Google Analytics e selecione a propriedade do Portal Trivox,
   cujo fluxo da Web usa o ID de medição `G-7BBRM65BLQ`.
2. Abra **Relatórios → Monetização → Promoções**. Em algumas propriedades,
   o caminho aparece como **Impulsionar vendas on-line → Promoções**.
3. Escolha as datas inicial e final no seletor de período.
4. Na dimensão da tabela, selecione **Nome da promoção do item**. O nome
   corresponde ao **Título interno** cadastrado no banner, em
   **Administração do portal → Publicidade → Gerenciar**.
5. Consulte **Itens visualizados na promoção** e **Itens clicados na promoção**.
   Pesquise o nome da campanha para limitar a tabela ao anunciante desejado.
6. Use **Compartilhar este relatório → Fazer download do arquivo → PDF ou CSV**.
   Para evidenciar as datas de veiculação, inclua também a tabela por dia abaixo.

Se Promoções não aparecer na navegação, um editor/administrador pode adicioná-lo
pela Biblioteca de relatórios. Outra opção é criar a exploração descrita abaixo.

## Gerar a tabela por dia e posição

1. Abra **Explorar → Em branco / Formato livre** e defina o período.
2. Em **Variáveis → Dimensões → +**, importe **Data**, **Nome da promoção do
   item**, **ID da promoção do item** e **Posição do criativo da promoção do item**.
   Os nomes podem aparecer em inglês: Date, Item promotion name, Item promotion
   ID e Item promotion creative slot.
3. Em **Métricas → +**, importe **Itens visualizados na promoção** e **Itens
   clicados na promoção** (Items viewed in promotion / Items clicked in promotion).
4. Em **Configurações**, coloque Data, Nome da promoção do item e Posição do
   criativo em **Linhas**. Coloque as duas métricas em **Valores**. Use **Data**
   como primeira linha e ordene do dia mais antigo para o mais recente.
5. Em **Filtros**, limite Nome da promoção do item à campanha desejada.
   Para distinguir duas artes com o mesmo título, adicione o ID da promoção
   às linhas. Os espaços aparecem como Topo / Cabeçalho, Topo / Lateral 1,
   Topo / Lateral 2, Meio / Esquerda ou Meio / Direita.
6. Dê um nome à exploração, como **Veiculação de publicidade por dia**, para
   reutilizá-la. Clique em **Exportar dados** e escolha CSV ou PDF.

## Como interpretar os números

- Uma exibição exige imagem carregada, pelo menos 50% do banner visível e
  um segundo contínuo com a aba em primeiro plano.
- Cada arte/posição conta no máximo uma exibição por carregamento de página.
  Voltar a rolar ou rever a mesma arte no carrossel não aumenta esse número.
- Cliques são interações reais no banner. Um clique rápido pode existir sem
  uma exibição que tenha completado o segundo exigido.
- Uma arte nova, outro link ou outro título cria outro ID de campanha. Para
  campanhas diferentes, use títulos internos diferentes e reconhecíveis.
- Datas seguem o fuso configurado na propriedade do Analytics. O administrador
  deve conferir se ele corresponde a Brasília/São Paulo para comparar os prints.
- A coleta começa com a implantação desta alteração; não há recuperação de
  exibições anteriores. Consentimento, bloqueadores e falhas de rede podem
  reduzir a coleta. Ausência de eventos não prova que o anúncio esteve fora do ar.
- O processamento dos relatórios pode levar 24 a 48 horas. O cliente pode
  conferir `view_promotion` e `select_promotion` no relatório Em tempo real.
- Esses números complementam os prints e mostram exibições registradas;
  não certificam veiculação contínua. A aceitação como comprovante depende da agência.
- A medição cobre os banners do editor visual. Anúncios inseridos como HTML
  manual precisam ser convertidos ou instrumentados separadamente.

Referências oficiais:

- https://support.google.com/analytics/answer/13458990?hl=pt-BR
- https://support.google.com/analytics/answer/12216232?hl=pt-BR
- https://support.google.com/analytics/answer/9317657?hl=pt-BR
- https://support.google.com/analytics/answer/11198161?hl=pt-BR
