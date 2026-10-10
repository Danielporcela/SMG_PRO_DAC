# SGMF Pro

**Sistema de Gestão de Manutenção de Frotas** — ordens de serviço, abastecimentos, pneus,
estoque de peças, orçamento e indicadores, com alertas automáticos e relatórios em
PDF, Excel e CSV.

Python 3 · Flask · SQLAlchemy · SQLite (desenvolvimento) · PostgreSQL (produção) ·
HTML5 · CSS3 · JavaScript ES6 · Bootstrap 5 · Chart.js · DataTables · SweetAlert2 · FontAwesome

---

## 1. Rodar no seu computador

Você precisa do **Python 3.10 ou superior** instalado.

```bash
# 1. entre na pasta do projeto
cd SGMF

# 2. crie e ative um ambiente virtual
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# 3. instale as dependências
pip install -r requirements.txt

# 4. (opcional) carregue dados de demonstração para conhecer as telas
python seed.py

# 5. inicie o sistema
python app.py
```

Abra **http://localhost:5000**.

Primeiro acesso: **admin@sgmf.local** / **admin123** — troque a senha assim que entrar
(menu Usuários).

Para começar do zero com seus próprios dados, apague o arquivo `database/sgmf.db` e
inicie o sistema de novo: ele recria o banco vazio e o usuário administrador.

O sistema trabalha no fuso **America/São Paulo** (ajustável na variável `TZ`), então a
data de um lançamento feito às 22h é a do próprio dia, não a do dia seguinte.

---

## 2. Publicar no GitHub

```bash
cd SGMF
git init
git add .
git commit -m "SGMF Pro - versão inicial"
git branch -M main
git remote add origin https://github.com/SEU-USUARIO/sgmf-pro.git
git push -u origin main
```

O `.gitignore` já impede que banco de dados, arquivos `.env` e uploads subam para o
repositório. **Deixe o repositório privado** — é um sistema interno da sua empresa.

---

## 3. Publicar no Render

O arquivo `render.yaml` já descreve toda a infraestrutura. O Render cria sozinho o
serviço web e o banco PostgreSQL.

1. Acesse [render.com](https://render.com) e entre com a conta do GitHub.
2. **New → Blueprint**, escolha o repositório `sgmf-pro` e confirme.
3. O Render lê o `render.yaml` e mostra o que vai criar: o serviço `sgmf-pro` e o banco
   `sgmf-banco`. Clique em **Apply**.
4. Informe as duas variáveis marcadas como `sync: false`:

   | Variável | O que colocar |
   |---|---|
   | `ADMIN_EMAIL` | o e-mail do administrador, ex.: `voce@suaempresa.com.br` |
   | `ADMIN_SENHA` | a senha do primeiro acesso |

   O `SECRET_KEY` e a `DATABASE_URL` o Render preenche automaticamente.
5. Aguarde o build (3 a 5 minutos). O endereço fica como
   `https://sgmf-pro.onrender.com`.

A cada `git push` na branch `main` o Render publica a nova versão sozinho.

### Se preferir criar o serviço manualmente

- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `gunicorn app:app --workers 2 --threads 4 --timeout 120`
- **Health Check Path:** `/saude`
- Crie um PostgreSQL no Render e copie a *Internal Connection String* para a variável
  `DATABASE_URL` do serviço web.

### Sobre o plano gratuito

O plano free do Render hiberna o serviço após 15 minutos sem acesso — o primeiro
carregamento depois disso demora cerca de 30 segundos. O banco PostgreSQL gratuito
expira em 90 dias. Para uso diário na empresa, o plano pago mais barato resolve os dois
pontos. Enquanto isso, use **Relatórios → Baixar backup** para guardar os dados.

---

## 4. Configuração

Todas as regras ficam em variáveis de ambiente (no Render, em *Environment*; na sua
máquina, em um arquivo `.env` copiado de `.env.example`).

| Variável | Padrão | Para que serve |
|---|---|---|
| `SECRET_KEY` | — | Assina a sessão de login. Obrigatória em produção. |
| `DATABASE_URL` | SQLite local | Conexão do PostgreSQL. |
| `ADMIN_EMAIL` / `ADMIN_SENHA` | `admin@sgmf.local` / `admin123` | Primeiro acesso criado automaticamente. |
| `TZ` | `America/Sao_Paulo` | Fuso usado em todas as datas e horas do sistema. |
| `SULCO_MINIMO_MM` | `4` | Abaixo disso o pneu entra em alerta de troca. |
| `SMTP_HOST` / `SMTP_PORTA` | `smtp.gmail.com` / `587` | Servidor de envio de e-mail. |
| `SMTP_USUARIO` / `SMTP_SENHA` | — | Conta de envio e senha de aplicativo. Sem a senha, o envio fica desligado. |
| `EMAIL_DESTINATARIOS` | — | Quem recebe os avisos (separe por vírgula). |
| `ALERTAS_HORA` | `7` | Hora do envio diário (0 a 23). |
| `ALERTAS_EMAIL_ATIVO` | `1` | `0` desliga os avisos automáticos. |
| `TAREFAS_CHAVE` | — | Chave da URL de tarefa para agendador externo. |
| `KM_AVISO_TROCA_OLEO` | `500` | Quantos km antes o sistema avisa da troca de óleo. |
| `DESVIO_CONSUMO_ALERTA` | `0.15` | Quanto o consumo pode piorar (15%) antes do alerta. |

### Mudanças na estrutura do banco

O projeto usa **Flask-Migrate (Alembic)**. Um banco novo é criado automaticamente na
primeira execução. Quando você alterar ou acrescentar um campo em `models.py`:

```bash
flask db migrate -m "descreva a mudança"   # gera o script em migrations/versions/
flask db upgrade                           # aplica no banco local
```

Confira o script gerado antes de aplicar, e faça o commit dele junto com o código. No
Render, o `render.yaml` roda `flask db upgrade` antes de publicar a nova versão — assim
o banco de produção acompanha o código **sem perder dados**. Se o seu plano não tiver
pre-deploy, rode o mesmo comando no *Shell* do serviço.

---

## 5. O que o sistema faz

### Cadastros
- **Veículos** — prefixo, placa, centro de custo, setor, hodômetro, horímetro, situação,
  intervalo de troca de óleo, intervalo de preventiva e orçamento mensal.
- **Motoristas** — CNH, categoria e validade (a validade vencida aparece em vermelho).
- **Oficinas, postos e fornecedores.**

### Manutenção (ordens de serviço)
Número gerado automaticamente (`OS202600001`), tipo (preventiva, corretiva,
emergencial), prioridade, status (aberta, em execução, aguardando peça, finalizada),
grupo do componente, oficina, mecânico e avaliação do serviço.

O custo é montado sozinho: **peças + mão de obra + serviços externos = total**.

Ao abrir uma OS o veículo passa para *Em manutenção*; ao finalizar, volta para
*Disponível*. Se a OS for preventiva, a data da última preventiva do veículo é
atualizada; se envolver troca de óleo, o km da troca também.

### Combustível
Você informa data, veículo, motorista, posto, km do painel e litros. O sistema calcula
**km percorridos, km/L e custo por km** comparando com o abastecimento anterior, e
atualiza o hodômetro do veículo. Km menor que o último lançado é recusado.

### Pneus
Posição no veículo, medida, marca, vida (novo ou recapagem), sulco em milímetros e km
rodados desde a instalação. Sulco abaixo de **4 mm** gera alerta de troca.

### Estoque de peças
Entrada, saída e ajuste de inventário, cada um com registro no histórico. O custo
unitário é recalculado por **média ponderada** a cada entrada. Quando uma peça é
aplicada em uma OS, ela sai do estoque automaticamente — e volta se o item for removido.
Saída maior que o saldo é recusada.

### Painel e indicadores
Disponibilidade da frota, MTBF, MTTR, custo por km, consumo médio, km rodados, gasto de
combustível e manutenção, aderência ao orçamento e valor em estoque. Mais dois
indicadores de gestão:

- **Economia no período** — compara o custo por km do período com a média histórica da
  frota e mostra em reais quanto foi economizado (ou gasto a mais). Só aparece quando já
  existe histórico suficiente para a conta fazer sentido.
- **Prazo médio de atendimento** — quantos dias, em média, uma OS leva da abertura ao
  fechamento. Conta apenas as ordens finalizadas; as em aberto não distorcem a média.
Gráficos: gasto mensal contra meta (12 meses), custo por veículo, preventiva × corretiva,
custo por grupo de peças e consumo por veículo.

### Rankings
Motoristas com melhor consumo e menor custo por km; veículos mais econômicos, de maior
custo e com maior tempo parado.

### Alertas automáticos
- Troca de óleo próxima ou vencida
- Preventiva atrasada ou a vencer
- Pneu abaixo do sulco mínimo
- Peça abaixo do estoque mínimo
- Veículo acima do orçamento do mês
- Consumo pior que a média histórica do próprio veículo
- Mesmo componente com 3 ou mais corretivas em 90 dias

### Relatórios
Sete relatórios (abastecimentos, ordens de serviço, custos por veículo, frota, pneus,
estoque e movimentação) em **PDF, Excel e CSV**, com filtros de período, veículo,
motorista e oficina. Mais o **backup completo em JSON**.

### Importar planilhas
Para não digitar a frota inteira à mão. Em **Importar planilha** você escolhe o que vai
importar (veículos, motoristas, oficinas ou peças), baixa o modelo `.xlsx` já com os
cabeçalhos certos e as colunas obrigatórias marcadas com `*`, preenche e envia.

O sistema faz uma **conferência antes de gravar**: mostra quantas linhas estão prontas,
quantas foram recusadas e o motivo de cada recusa, com o número da linha da planilha
("linha 6 → placa já existe no sistema"). Nada é gravado nessa etapa. Você confirma e só
as linhas boas entram — as recusadas você corrige e reenvia. Peças importadas já entram
com o saldo inicial lançado como movimento de entrada.

### Anexos
Ordens de serviço e abastecimentos aceitam arquivos: nota fiscal, cupom do posto, foto do
defeito. Aceita JPG, PNG, WEBP e PDF, até 5 MB por arquivo. Fotos aparecem em miniatura,
dá para abrir, baixar e excluir, e a lista mostra quantos anexos cada registro tem.
Excluir a OS leva os anexos junto.

Os arquivos ficam **dentro do banco de dados**, não no disco. É de propósito: o disco do
Render é apagado a cada nova publicação, e assim seus anexos entram no backup e
sobrevivem aos deploys.

### Avisos por e-mail
Todo dia, no horário configurado, o sistema envia um resumo dos alertas ativos —
preventiva atrasada, óleo vencido, pneu no limite, estoque baixo. Se não houver nada
crítico, não manda e-mail nenhum (para o aviso não virar ruído).

**Vem desligado.** Para ativar com o Gmail:

1. Na Conta Google, ative a verificação em duas etapas.
2. Em *Segurança → Senhas de app*, gere uma senha de 16 letras.
3. No Render, em *Environment*, cole essa senha em `SMTP_SENHA`.
4. Salve e volte à tela **Avisos por e-mail** para mandar um teste.

A tela mostra a situação atual (ligado ou desligado e o que falta), permite enviar uma
mensagem de teste e disparar o resumo na hora, antes de confiar no envio automático. A
senha fica só nas variáveis do Render — nunca no código nem no repositório.

Como o plano gratuito do Render hiberna o serviço, o disparo diário depende de a
aplicação estar acordada. Se você mantiver um ping periódico, o agendador interno resolve
sozinho; se não, existe também uma URL de tarefa protegida por chave
(`/tarefas/alertas?chave=...`) para um agendador externo chamar.

### Cuidados de segurança já embutidos
- Senhas guardadas como hash, nunca em texto.
- Cookie de sessão só trafega por HTTPS em produção.
- Texto digitado pelo usuário é escapado antes de virar HTML — um nome com
  `<script>` aparece como texto, não executa.
- Consultas ao banco usam parâmetros, então texto com aspas ou comandos SQL é
  gravado como texto comum.
- Baixa de estoque e numeração de OS resistem a dois usuários lançando ao mesmo
  tempo: o banco arbitra a disputa em vez de o saldo furar.

### Perfis de acesso
- **Administrador** — tudo, incluindo usuários, auditoria e restauração de backup.
- **Operador** — lança, edita e exclui registros do dia a dia.
- **Consulta** — apenas visualiza. Os botões de novo, editar e excluir somem da tela, e
  o servidor também recusa qualquer tentativa de gravação (não adianta contornar pela
  API).

Qualquer usuário troca a própria senha em **Trocar minha senha**, no rodapé do menu.

### Auditoria
O sistema registra quem criou, editou ou excluiu cada registro, com data e hora. O
administrador consulta esse histórico em **Auditoria**, com filtro por módulo.

### Restaurar um backup
Em **Relatórios**, o administrador envia um arquivo JSON baixado antes e o sistema
recarrega veículos, motoristas, oficinas, ordens de serviço, abastecimentos, pneus,
peças e metas. A restauração é total nesses módulos e pede confirmação digitada.
**Usuários e senhas não são alterados** — quem tem acesso hoje continua tendo. Se o
arquivo tiver qualquer inconsistência, nada é gravado e o banco permanece como estava.

---

## 6. Testes

```bash
pip install pytest
python -m pytest tests -q
```

São **185 testes automatizados** cobrindo login e permissões dos três perfis, todas as
telas, os cadastros, os cálculos de consumo e custo, a baixa de estoque, os alertas, o
fuso horário, a auditoria, a restauração de backup, a importação de planilhas, os
anexos, o envio de e-mail, a disputa entre usuários simultâneos e os 21 arquivos de
relatório (7 relatórios × 3 formatos). Cada teste roda
em um banco temporário, sem tocar nos seus dados.

Rode a suíte sempre que alterar alguma regra — é o jeito mais rápido de saber se algo
quebrou.

### Testar contra o PostgreSQL

O SQLite do desenvolvimento e o PostgreSQL da produção não se comportam igual em tudo.
Para rodar a mesma suíte contra um PostgreSQL local:

```bash
TEST_DATABASE_URL=postgresql://usuario:senha@localhost/sgmf_teste \
    python -m pytest tests -q
```

Atenção: o banco apontado é **apagado a cada teste**. Use um banco só para isso.

---

## 7. Estrutura do projeto

```
SGMF/
├── app.py                  # cria a aplicação e registra as rotas
├── config.py               # configurações e regras ajustáveis
├── extensions.py           # instância do banco
├── models.py               # tabelas: veículos, OS, abastecimentos, pneus, peças...
├── seed.py                 # dados de demonstração
├── requirements.txt
├── Procfile                # comando de execução (gunicorn)
├── render.yaml             # infraestrutura do Render
├── routes/
│   ├── auth.py             # login, sessão, usuários
│   ├── api.py              # API REST de todos os módulos
│   ├── extras.py           # importação, anexos e notificações
│   ├── paginas.py          # telas HTML
│   └── relatorios.py       # PDF, Excel, CSV e backup
├── services/
│   ├── crud.py             # camada genérica de CRUD e permissões
│   ├── calculos.py         # consumo, estoque, status do veículo
│   ├── indicadores.py      # KPIs, gráficos, rankings e alertas
│   ├── importacao.py       # leitura e conferência das planilhas
│   ├── notificacoes.py     # envio de e-mail e agendador diário
│   ├── restauracao.py      # leitura do backup JSON
│   └── tempo.py            # data e hora no fuso da empresa
├── migrations/             # histórico de estrutura do banco (Alembic)
├── templates/              # telas (Jinja2)
├── static/
│   ├── css/style.css       # identidade visual
│   ├── js/                 # core.js, crud.js, dashboard.js, anexos.js
│   └── vendor/             # Bootstrap, Chart.js, DataTables, SweetAlert2, FontAwesome
├── tests/                  # 185 testes automatizados
├── database/               # banco SQLite (não vai para o GitHub)
├── uploads/  backup/
```

As bibliotecas do front-end estão dentro do projeto (`static/vendor/`), não em CDN — o
sistema funciona mesmo em rede interna sem acesso externo.

---

## 8. Rotina sugerida de uso

1. Cadastre veículos, motoristas, oficinas e postos — ou carregue tudo de uma vez em
   *Importar planilha*.
2. Informe o hodômetro atual, o km da última troca de óleo e a data da última preventiva
   de cada veículo — é isso que liga os alertas.
3. Lance os abastecimentos conforme acontecem (é o que alimenta consumo e custo por km).
4. Abra uma OS para cada manutenção e aplique as peças nela.
5. Cadastre o estoque com o saldo inicial e vá registrando as entradas de compra.
6. Meça o sulco dos pneus periodicamente e atualize o campo.
7. Defina a meta mensal em *Meta × realizado*.
8. Baixe o backup uma vez por semana (Relatórios → Baixar backup).
9. Dê perfil **Consulta** a quem só precisa acompanhar (chefia, contabilidade) e
   **Operador** a quem lança no dia a dia.
10. Ligue os avisos por e-mail (*Avisos por e-mail*) para não depender de alguém abrir o
    sistema para ver um alerta.

---

## 9. Próximos passos possíveis

O sistema foi organizado em módulos independentes, então dá para crescer sem reescrever
o que existe. O que ficou combinado para depois:

- **Paginação no servidor** — hoje cada tela carrega todos os registros, o que deixa a
  busca instantânea. Medido com 2.000 abastecimentos, o painel responde em 0,04 s, então
  não há pressa; quando as listas passarem de alguns milhares de linhas, vale trocar.

Fora isso, o melhor guia são as próprias semanas de uso: anote o que trava o dia a dia da
equipe e trate essa lista como a fila de prioridades.
