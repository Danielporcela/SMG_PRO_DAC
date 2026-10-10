SGMF PRO — ESTOQUE DE COMBUSTÍVEL (cópia de trabalho)
Base: SGMF_Pro_DAC(3).zip enviado em 01/10/2026.
O arquivo original não foi alterado.

IMPLEMENTADO
1. Nota fiscal de combustível na aba Abastecimentos.
2. A primeira NF ativa o estoque do respectivo combustível.
3. NF gera entrada em litros e valor.
4. Abastecimento manual ou importado gera baixa automática.
5. Estoque negativo é bloqueado com mensagem de litros disponíveis/faltantes.
6. Custo médio ponderado recalculado cronologicamente.
7. Valor por litro/valor total do abastecimento passam a refletir o custo médio quando o estoque por NF estiver ativo.
8. Histórico (kardex) de entradas e saídas.
9. Resumo por tipo de combustível: saldo, custo médio e valor do estoque.
10. Dashboard mostra combustível em controle separado.
11. NF de combustível e combustível consumido NÃO entram em Gasto total / Gasto total geral.
12. Orçamento/realizado geral passa a considerar despesas gerais sem combustível.
13. Gráfico de ciclos exibe combustível em pilha separada das despesas.
14. Exclusão/edição de NF é bloqueada quando causaria saldo histórico negativo.
15. Importação de abastecimentos é atômica em relação ao estoque: falta de saldo cancela a gravação.

IMPORTANTE
- Abastecimentos anteriores à data de ativação do estoque permanecem históricos e não exigem NF retroativa.
- Se for lançada uma NF retroativa anterior à data de ativação, o sistema passa a validar o estoque a partir dessa data.
- O custo operacional por km continua podendo considerar combustível para análise da eficiência da frota, mas o combustível fica fora do total de despesas gerais solicitado.

TESTES EXECUTADOS
- Compilação dos arquivos Python alterados: OK.
- Sintaxe JavaScript do Dashboard e da tela Combustível: OK.
- Parse dos templates Jinja: OK.
- Teste de custo médio: 1.000 L a R$ 6,00, saída 100 L, entrada 500 L a R$ 7,00, saída 200 L => saldo 1.200 L e custo médio ponderado aplicado: OK.
- Teste de bloqueio: tentativa de abastecer 120 L com 100 L em estoque => bloqueada: OK.
- Teste Dashboard: combustível comprado/consumido separado e Gasto total geral sem combustível: OK.

ARQUIVOS PRINCIPAIS ALTERADOS
- app.py
- models.py
- routes/api.py
- routes/combustivel_estoque.py (novo)
- services/compatibilidade_banco.py
- services/crud.py
- services/importacao.py
- services/indicadores.py
- services/estoque_combustivel.py (novo)
- static/js/dashboard.js
- templates/combustivel.html
- templates/dashboard.html
- templates/orcamento.html
