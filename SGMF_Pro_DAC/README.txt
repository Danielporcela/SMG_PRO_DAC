IMPLEMENTAÇÃO — NOTAS FISCAIS DE UNIFORMES

Arquivos substituídos:
- models.py
- routes/uniformes.py
- routes/relatorios.py
- services/indicadores.py
- services/compatibilidade_banco.py
- app.py
- templates/uniformes.html
- templates/relatorios.html
- static/js/dashboard.js

Fluxo:
1. Uniformes > Lançar nota fiscal.
2. Informe NF, série, fornecedor e data.
3. Adicione cada uniforme/tamanho/quantidade/valor unitário.
4. Salve a nota.
5. Finalize a nota para dar entrada no estoque por tamanho e contabilizar o gasto.
6. O valor da NF finalizada entra nos indicadores de gastos mensais como "Uniformes (NF)" e no "Gasto total geral".
7. O relatório "Gastos com uniformes" pode ser impresso em PDF ou exportado em Excel/CSV.

Observação:
A implementação usa a rotina de compatibilidade do banco existente, portanto não exige criar uma nova revisão Alembic. Em banco novo, db.create_all() cria as tabelas normalmente.
