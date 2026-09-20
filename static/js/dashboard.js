/* Painel principal — indicadores, gráficos e alertas do período. */
(function () {
  const inicio = () => document.getElementById('filtroInicio').value;
  const fim = () => document.getElementById('filtroFim').value;

  let ultimoConsumoFrotas = null; // km/L de todas as frotas (atual x anterior) para a impressão
  let ultimosGraficos = null; // guarda o retorno de /api/painel/graficos para a impressão
  let ultimoConsumoDiario = null; // guarda o histórico de /api/consumo-diario para a impressão
  let ultimoHorasMecanicos = null; // guarda o retorno de /api/painel/horas-mecanicos para a impressão

  function medidor(rotulo, valor, opcoes = {}) {
    return `<div class="medidor ${opcoes.classe || ''}">
      <div class="rotulo">${opcoes.icone ? `<i class="fa-solid ${opcoes.icone}"></i>` : ''}${rotulo}</div>
      <div class="valor num" style="${opcoes.estilo || ''}">${valor}</div>
      ${opcoes.nota ? `<div class="nota">${opcoes.nota}</div>` : ''}
    </div>`;
  }

  async function carregarIndicadores() {
    const d = await SGMF.get(`/api/painel/resumo?inicio=${inicio()}&fim=${fim()}`);
    const aderencia = d.orcamento_mes
      ? `${SGMF.numero(d.aderencia_orcamento, 1)}% do orçamento`
      : 'Sem meta cadastrada';

    document.getElementById('instrumentos').innerHTML = [
      medidor('Frota ativa', d.veiculos_total, {
        icone: 'fa-truck-front', nota: `${d.veiculos_disponiveis} disponíveis` }),
      medidor('Em manutenção', d.veiculos_manutencao, {
        classe: d.veiculos_manutencao ? 'atencao' : 'ok', icone: 'fa-screwdriver-wrench',
        nota: `${d.os_abertas} OS em aberto` }),
      medidor('Disponibilidade', `${SGMF.numero(d.disponibilidade, 1)}<small>%</small>`, {
        classe: d.disponibilidade >= 90 ? 'ok' : 'atencao', icone: 'fa-circle-check' }),
      medidor('Km rodados', SGMF.numero(d.km_rodados), { icone: 'fa-road', nota: 'no período' }),
      medidor('Consumo médio', `${SGMF.numero(d.consumo_medio, 2)} <small>km/L</small>`, {
        icone: 'fa-gas-pump',
        nota: `${SGMF.numero(d.litros, 1)} litros · média da média: ${SGMF.numero(d.consumo_medio_media_da_media, 2)} km/L` }),
      medidor('Custo por km', SGMF.moeda(d.custo_por_km), {
        icone: 'fa-coins', estilo: 'font-size:21px' }),
      medidor('Combustível', SGMF.moeda(d.gasto_combustivel), {
        icone: 'fa-fill-drip', estilo: 'font-size:19px', nota: `${d.abastecimentos} abastecimentos` }),
      medidor('Manutenção', SGMF.moeda(d.gasto_manutencao), {
        icone: 'fa-wrench', estilo: 'font-size:19px',
        nota: `${d.os_preventivas} preventivas · ${d.os_corretivas} corretivas · inclui terceiros` }),
      medidor('Serviços terceiros', SGMF.moeda(d.gasto_servicos_terceiros), {
        icone: 'fa-hand-holding-dollar', estilo: 'font-size:19px',
        nota: `${d.servicos_terceiros_qtd} lançamento(s) no período` }),
      medidor('Lavagem', SGMF.moeda(d.gasto_lavagem), {
        icone: 'fa-soap', estilo: 'font-size:19px',
        nota: `${d.lavagens_qtd} lançamento(s) no período` }),
      medidor('Compras (NF)', SGMF.moeda(d.gasto_compras), {
        icone: 'fa-file-invoice-dollar', estilo: 'font-size:19px',
        nota: `${d.notas_fiscais_qtd} nota(s) finalizada(s)` }),
      medidor('Gasto total', SGMF.moeda(d.gasto_total), {
        classe: d.orcamento_mes && d.aderencia_orcamento > 100 ? 'critico' : '',
        icone: 'fa-sack-dollar', estilo: 'font-size:19px', nota: aderencia }),
      medidor('Gasto total geral', SGMF.moeda(d.gasto_total_geral), {
        icone: 'fa-coins', estilo: 'font-size:19px',
        nota: 'frota + compras de peças (NF)' }),
      medidor('Economia no período', d.economia_periodo === null
          ? '—' : SGMF.moeda(Math.abs(d.economia_periodo)), {
        classe: d.economia_periodo === null ? '' : (d.economia_periodo >= 0 ? 'ok' : 'critico'),
        icone: d.economia_periodo >= 0 ? 'fa-arrow-trend-down' : 'fa-arrow-trend-up',
        estilo: 'font-size:19px',
        nota: d.economia_periodo === null
          ? 'Sem histórico suficiente ainda'
          : `${d.economia_periodo >= 0 ? 'Economia' : 'Gasto a mais'} de ` +
            `${SGMF.numero(Math.abs(d.variacao_custo_km), 1)}% no custo por km ` +
            `(histórico ${SGMF.moeda(d.custo_km_historico)})` }),
      medidor('OS com baixa pendente', d.os_estoque_pendentes, {
        classe: d.os_estoque_pendentes ? 'atencao' : 'ok', icone: 'fa-clipboard-check',
        nota: d.os_estoque_pendentes ? 'regularização de estoque necessária' : 'todas regularizadas' }),
      medidor('Estoque', SGMF.moeda(d.estoque_valor), {
        classe: d.estoque_critico ? 'atencao' : '', icone: 'fa-boxes-stacked',
        estilo: 'font-size:19px', nota: `${d.estoque_critico} itens a repor` })
    ].join('');
  }

  async function carregarGraficos() {
    const g = await SGMF.get(`/api/painel/graficos?inicio=${inicio()}&fim=${fim()}`);
    ultimosGraficos = g;

    SGMF.grafico('graficoMeses', {
      data: {
        labels: g.meses,
        datasets: [
          { type: 'bar', label: 'Combustível', data: g.combustivel_mes,
            backgroundColor: '#0F3D56', stack: 'gasto', borderRadius: 2 },
          { type: 'bar', label: 'Manutenção (incl. terceiros)', data: g.manutencao_mes,
            backgroundColor: '#7FA9C2', stack: 'gasto', borderRadius: 2 },
          { type: 'bar', label: 'Lavagem', data: g.lavagem_mes,
            backgroundColor: '#4FB0C6', stack: 'gasto', borderRadius: 2 },
          { type: 'bar', label: 'Compras (NF)', data: g.compras_mes,
            backgroundColor: '#16795D', stack: 'gasto', borderRadius: 2 },
          { type: 'line', label: 'Meta', data: g.meta_mes, borderColor: '#F5A800',
            borderWidth: 2, borderDash: [5, 4], pointRadius: 2, tension: .25, fill: false }
        ]
      },
      options: {
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { position: 'bottom', labels: { boxWidth: 10, usePointStyle: true } },
          tooltip: { callbacks: { label: c => `${c.dataset.label}: ${SGMF.moeda(c.parsed.y)}` } }
        },
        scales: {
          x: { stacked: true, grid: { display: false } },
          y: { stacked: true, ticks: { callback: v => 'R$ ' + SGMF.numero(v) },
               grid: { color: '#EBEFF3' } }
        }
      }
    });

    SGMF.grafico('graficoVeiculos', {
      type: 'bar',
      data: {
        labels: g.por_veiculo.map(v => v.veiculo),
        datasets: [
          { label: 'Combustível', data: g.por_veiculo.map(v => v.combustivel), backgroundColor: '#0F3D56' },
          { label: 'Manutenção', data: g.por_veiculo.map(v => v.manutencao), backgroundColor: '#F5A800' }
        ]
      },
      options: {
        indexAxis: 'y', maintainAspectRatio: false,
        plugins: { legend: { position: 'bottom', labels: { boxWidth: 10, usePointStyle: true } },
                   tooltip: { callbacks: { label: c => `${c.dataset.label}: ${SGMF.moeda(c.parsed.x)}` } } },
        scales: { x: { stacked: true, ticks: { callback: v => 'R$ ' + SGMF.numero(v) } },
                  y: { stacked: true, grid: { display: false } } }
      }
    });

    SGMF.grafico('graficoTipos', {
      type: 'doughnut',
      data: {
        labels: Object.keys(g.tipos_manutencao),
        datasets: [{ data: Object.values(g.tipos_manutencao),
                     backgroundColor: ['#16795D', '#F5A800', '#C4451D'], borderWidth: 0 }]
      },
      options: { maintainAspectRatio: false, cutout: '58%',
                 plugins: { legend: { position: 'bottom', labels: { boxWidth: 10, usePointStyle: true } } } }
    });

    SGMF.grafico('graficoGrupos', {
      type: 'bar',
      data: {
        labels: g.grupos.labels,
        datasets: [{ data: g.grupos.valores, backgroundColor: SGMF.PALETA, borderRadius: 2 }]
      },
      options: {
        indexAxis: 'y', maintainAspectRatio: false,
        plugins: { legend: { display: false },
                   tooltip: { callbacks: { label: c => SGMF.moeda(c.parsed.x) } } },
        scales: { x: { ticks: { callback: v => 'R$ ' + SGMF.numero(v) } }, y: { grid: { display: false } } }
      }
    });

    SGMF.grafico('graficoConsumo', {
      type: 'bar',
      data: {
        labels: g.consumo_veiculo.map(v => v.veiculo),
        datasets: [{ label: 'km/L', data: g.consumo_veiculo.map(v => v.consumo),
                     backgroundColor: '#16795D', borderRadius: 2 }]
      },
      options: {
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { x: { grid: { display: false } }, y: { grid: { color: '#EBEFF3' } } }
      }
    });

    SGMF.grafico('graficoLavagem', {
      type: 'bar',
      data: {
        labels: g.meses,
        datasets: [{ label: 'Lavagem', data: g.lavagem_mes,
                     backgroundColor: '#4FB0C6', borderRadius: 2 }]
      },
      options: {
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: c => SGMF.moeda(c.parsed.y) } }
        },
        scales: {
          x: { grid: { display: false } },
          y: { ticks: { callback: v => 'R$ ' + SGMF.numero(v) }, grid: { color: '#EBEFF3' } }
        }
      }
    });

    SGMF.grafico('graficoTopPecas', {
      type: 'bar',
      data: {
        labels: g.top_pecas.map(p => p.peca),
        datasets: [{ label: 'Quantidade consumida', data: g.top_pecas.map(p => p.quantidade),
                     backgroundColor: '#0F3D56', borderRadius: 2 }]
      },
      options: {
        indexAxis: 'y', maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: {
            label: c => `Qtde: ${SGMF.numero(c.parsed.x, 2)} · ${SGMF.moeda(g.top_pecas[c.dataIndex].valor)}`
          } }
        },
        scales: { x: { ticks: { callback: v => SGMF.numero(v) } }, y: { grid: { display: false } } }
      }
    });

    const top = g.por_veiculo.slice(0, 8);
    document.getElementById('tabelaTop').innerHTML = top.length
      ? `<table class="table table-sm mb-0 align-middle" style="font-size:13px">
          <thead><tr><th class="ps-3">Veículo</th><th class="text-end">Km</th>
          <th class="text-end">Km/L</th>
          <th class="text-end" title="Média simples do km/L de cada abastecimento do período">Km/L (média da média)</th>
          <th class="text-end">Custo/km</th>
          <th class="text-end pe-3">Total</th></tr></thead>
          <tbody>${top.map(v => `<tr>
            <td class="ps-3"><span class="prefixo">${SGMF.esc(v.veiculo)}</span>
              <span class="placa ms-1">${SGMF.esc(v.placa)}</span></td>
            <td class="text-end num">${SGMF.numero(v.km)}</td>
            <td class="text-end num">${v.consumo ? SGMF.numero(v.consumo, 2) : '—'}</td>
            <td class="text-end num">${v.consumo_media_da_media ? SGMF.numero(v.consumo_media_da_media, 2) : '—'}</td>
            <td class="text-end num">${v.custo_km ? SGMF.moeda(v.custo_km) : '—'}</td>
            <td class="text-end num pe-3"><strong>${SGMF.moeda(v.total)}</strong></td>
          </tr>`).join('')}</tbody></table>`
      : `<div class="vazio"><i class="fa-solid fa-chart-simple"></i>
          <strong>Sem lançamentos no período</strong>Registre abastecimentos e ordens de serviço.</div>`;
  }

  // Evolução diária do consumo da frota — série própria (não depende do
  // filtro de período do painel; sempre mostra os últimos 30 dias e é
  // recalculada no servidor a cada carregamento).
  async function carregarConsumoDiario() {
    const historico = await SGMF.get('/api/consumo-diario/historico?dias=30');
    ultimoConsumoDiario = historico;
    if (!historico.length) {
      document.getElementById('resumoConsumoDiario').innerHTML = '';
      document.getElementById('consumoAtualizadoEm').textContent = '';
      return;
    }
    const ultimo = historico[historico.length - 1];
    const classeEficiencia = { EXCELENTE: 'ok', BOM: 'ok', NORMAL: 'atencao', RUIM: 'atencao' };

    document.getElementById('resumoConsumoDiario').innerHTML = [
      medidor('Consumo médio', `${SGMF.numero(ultimo.km_por_litro, 2)} <small>km/L</small>`, { icone: 'fa-gas-pump' }),
      medidor('Litros/dia', SGMF.numero(ultimo.litros_por_dia, 1), { icone: 'fa-droplet' }),
      medidor('Eficiência', ultimo.eficiencia, {
        classe: classeEficiencia[ultimo.eficiencia] || '', icone: 'fa-gauge-high' })
    ].join('');
    document.getElementById('consumoAtualizadoEm').textContent =
      ultimo.atualizado_em ? `atualizado ${ultimo.atualizado_em}` : '';

    SGMF.grafico('graficoConsumoDiario', {
      type: 'line',
      data: {
        labels: historico.map(h => SGMF.data(h.data)),
        datasets: [{
          label: 'Consumo médio (km/L)', data: historico.map(h => h.km_por_litro),
          borderColor: '#0F3D56', backgroundColor: 'rgba(15,61,86,.08)',
          borderWidth: 2, pointRadius: 2, tension: .25, fill: true
        }]
      },
      options: {
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: c => `${SGMF.numero(c.parsed.y, 2)} km/L` } }
        },
        scales: {
          x: { grid: { display: false } },
          y: { ticks: { callback: v => SGMF.numero(v, 1) }, grid: { color: '#EBEFF3' } }
        }
      }
    });
  }

  // Horas trabalhadas por mecânico no período selecionado do painel
  // (mesmos filtros de data usados nos demais cards e gráficos).
  async function carregarHorasMecanicos() {
    const dados = await SGMF.get(`/api/painel/horas-mecanicos?inicio=${inicio()}&fim=${fim()}`);
    ultimoHorasMecanicos = dados;

    const canvasBox = document.getElementById('graficoHorasMecanicos').closest('.grafico-caixa');
    const tabela = document.getElementById('tabelaHorasMecanicos');

    if (!dados.length) {
      if (canvasBox) canvasBox.style.display = 'none';
      tabela.innerHTML = `<div class="vazio"><i class="fa-solid fa-user-clock"></i>
        <strong>Sem OS com mecânico e horário registrados</strong>
        Informe o mecânico e os horários de início/fim nas ordens de serviço.</div>`;
      return;
    }
    if (canvasBox) canvasBox.style.display = '';

    const top = dados.slice(0, 12);
    SGMF.grafico('graficoHorasMecanicos', {
      type: 'bar',
      data: {
        labels: top.map(m => m.mecanico),
        datasets: [{ label: 'Horas trabalhadas', data: top.map(m => m.horas),
                     backgroundColor: '#0F3D56', borderRadius: 2 }]
      },
      options: {
        indexAxis: 'y', maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: {
            label: c => `${top[c.dataIndex].horas_str} · ${top[c.dataIndex].os} OS`
          } }
        },
        scales: { x: { ticks: { callback: v => SGMF.numero(v, 1) } }, y: { grid: { display: false } } }
      }
    });

    tabela.innerHTML = `<table class="table table-sm mb-0 align-middle" style="font-size:13px">
        <thead><tr><th class="ps-3">Mecânico</th><th class="text-end">OS</th>
        <th class="text-end">Horas</th><th class="text-end pe-3">Custo das OS</th></tr></thead>
        <tbody>${dados.map(m => `<tr>
          <td class="ps-3">${SGMF.esc(m.mecanico)}</td>
          <td class="text-end num">${m.os}</td>
          <td class="text-end num">${m.horas_str}</td>
          <td class="text-end num pe-3">${SGMF.moeda(m.custo)}</td>
        </tr>`).join('')}</tbody></table>`;
  }

  async function carregarAlertas() {
    const lista = await SGMF.carregarContadorAlertas();
    const icones = { critico: 'fa-circle-exclamation', atencao: 'fa-triangle-exclamation', info: 'fa-circle-info' };
    const area = document.getElementById('painelAlertas');
    area.innerHTML = lista.length
      ? lista.slice(0, 12).map(a => `<div class="alerta-item ${a.nivel}">
          <div class="icone"><i class="fa-solid ${icones[a.nivel]}"></i></div>
          <div><div class="titulo">
                 ${a.frota ? `<span class="etiqueta ambar me-2">${SGMF.esc(a.frota)}${a.placa ? ' · ' + SGMF.esc(a.placa) : ''}</span>` : ''}
                 ${SGMF.esc(a.titulo)}
               </div>
               <div class="detalhe">${SGMF.esc(a.detalhe)}</div></div></div>`).join('')
      : `<div class="vazio"><i class="fa-solid fa-circle-check" style="color:var(--ok)"></i>
          <strong>Nenhum alerta ativo</strong>Preventivas, pneus e orçamento estão dentro do previsto.</div>`;
  }

  async function carregarConectados() {
    const area = document.getElementById('painelConectados');
    if (!area) return; // card só existe para admin (ver dashboard.html)

    let lista;
    try {
      lista = await SGMF.get('/api/painel/conectados');
    } catch (erro) {
      // Compatibilidade com deploys que ainda não possuem a rota principal.
      // O novo backend disponibiliza as duas rotas; assim o card não quebra
      // por cache/ordem de atualização entre frontend e backend.
      if ((erro && /Endereço não encontrado/i.test(erro.message || '')) ||
          (erro && /404/.test(erro.message || ''))) {
        lista = await SGMF.get('/api/painel/logins-conectados');
      } else {
        throw erro;
      }
    }
    const etiquetaQtd = document.getElementById('etiquetaConectados');
    if (etiquetaQtd) etiquetaQtd.textContent = `${lista.length} conectado${lista.length === 1 ? '' : 's'}`;

    const tempoAtras = (min) => min < 1 ? 'agora mesmo' : `há ${min} min`;

    area.innerHTML = lista.length
      ? lista.map(u => `<div class="alerta-item info">
          <div class="icone"><i class="fa-solid fa-circle-user"></i></div>
          <div>
            <div class="titulo">${SGMF.esc(u.nome)}${u.voce ? ' <span class="etiqueta cinza" style="font-size:9.5px;padding:1px 6px">você</span>' : ''}</div>
            <div class="detalhe">${SGMF.esc(u.cargo || u.perfil)} · ${tempoAtras(u.minutos_atras)}</div>
          </div>
        </div>`).join('')
      : `<div class="vazio"><i class="fa-solid fa-user-slash"></i>
          <strong>Nenhum login ativo</strong>Ninguém usou o sistema nos últimos minutos.</div>`;
  }

  /* Impressão genérica de "gráfico + tabela": qualquer card de gráfico do
     painel usa esta mesma função, só muda o título, o canvas e as colunas.
     Canvas não sai no SGMF.imprimir() normal (que só copia outerHTML de
     tabelas), então aqui a gente converte o gráfico em imagem
     (canvas.toDataURL) e monta a janela de impressão na mão, no mesmo
     estilo da impressão de OS. */
  function abrirImpressaoRelatorio({ titulo, canvasId, colunas, linhas, notaExtra = '', semPeriodo = false, rodape = '' }) {
    if (!linhas || !linhas.length) return SGMF.aviso('Não há dados para imprimir neste período.');

    const canvas = canvasId ? document.getElementById(canvasId) : null;
    const imagem = canvas ? canvas.toDataURL('image/png', 1.0) : null;

    const janela = window.open('', '_blank', 'width=900,height=720');
    if (!janela) return SGMF.aviso('Seu navegador bloqueou a janela de impressão. Libere pop-ups para este site.');

    const cabecalho = colunas.map(c => `<th class="${c.classe || ''}">${SGMF.esc(c.rotulo)}</th>`).join('');
    const corpo = linhas.map((linha, i) => `<tr>${colunas.map(c =>
      `<td class="${c.classe || ''}">${c.render ? c.render(linha, i) : SGMF.esc(linha[c.campo])}</td>`
    ).join('')}</tr>`).join('');

    const doc = janela.document;
    doc.title = `${titulo} · SGMF Pro`;

    const estilo = doc.createElement('style');
    estilo.textContent = `
      * { box-sizing: border-box; }
      body { font-family: Arial, Helvetica, sans-serif; color: #182530; padding: 26px 30px; margin: 0; }
      h1 { font-size: 19px; margin: 0 0 2px; color: #0F3D56; }
      .sub { font-size: 12px; color: #666; margin-bottom: 18px; }
      img.grafico { width: 100%; max-height: 320px; object-fit: contain; margin-bottom: 18px; }
      table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
      th, td { border: 1px solid #D3DBE2; padding: 6px 9px; text-align: left; }
      th { background: #0F3D56; color: #fff; text-transform: uppercase; font-size: 10.5px; letter-spacing: .02em; }
      tr:nth-child(even) td { background: #F5F7F9; }
      thead { display: table-header-group; }
      tr { page-break-inside: avoid; }
      .num, .text-end { text-align: right; }
      .rodape-impressao { margin-top: 16px; font-size: 10.5px; color: #888; }
      @media print { @page { margin: 14mm; } }
    `;
    doc.head.appendChild(estilo);

    const corpoDoc = doc.createElement('div');
    corpoDoc.innerHTML = `
      <h1>${SGMF.esc(titulo)}</h1>
      <div class="sub">${semPeriodo ? 'Últimos 12 meses' : `Período de ${SGMF.data(inicio())} a ${SGMF.data(fim())}`}${notaExtra}
        · Gerado em ${new Date().toLocaleString('pt-BR')}</div>
      ${imagem ? `<img class="grafico" src="${imagem}">` : ''}
      <table>
        <thead><tr>${cabecalho}</tr></thead>
        <tbody>${corpo}</tbody>
      </table>
      <div class="rodape-impressao">${rodape ? `${SGMF.esc(rodape)}<br>` : ''}Sistema de Gestão de Manutenção de Frotas</div>
    `;
    doc.body.appendChild(corpoDoc);

    janela.onload = () => { janela.focus(); janela.print(); };
    if (doc.readyState === 'complete') { janela.focus(); janela.print(); }
  }

  function precisaGraficos() {
    if (!ultimosGraficos) SGMF.aviso('Aguarde os gráficos carregarem e tente novamente.');
    return ultimosGraficos;
  }

  function imprimirGraficoMeses() {
    const g = precisaGraficos(); if (!g) return;
    const linhas = g.meses.map((mes, i) => ({
      mes, combustivel: g.combustivel_mes[i], manutencao: g.manutencao_mes[i],
      compras: g.compras_mes[i], meta: g.meta_mes[i], realizado: g.realizado_mes[i],
      realizadoGeral: g.realizado_geral_mes[i]
    }));
    abrirImpressaoRelatorio({
      titulo: 'Gasto mensal e meta (últimos 12 meses)', canvasId: 'graficoMeses', semPeriodo: true,
      colunas: [
        { rotulo: 'Mês', campo: 'mes' },
        { rotulo: 'Combustível', classe: 'text-end num', render: l => SGMF.moeda(l.combustivel) },
        { rotulo: 'Manutenção', classe: 'text-end num', render: l => SGMF.moeda(l.manutencao) },
        { rotulo: 'Compras (NF)', classe: 'text-end num', render: l => SGMF.moeda(l.compras) },
        { rotulo: 'Meta', classe: 'text-end num', render: l => SGMF.moeda(l.meta) },
        { rotulo: 'Realizado (frota)', classe: 'text-end num', render: l => SGMF.moeda(l.realizado) },
        { rotulo: 'Realizado geral', classe: 'text-end num', render: l => SGMF.moeda(l.realizadoGeral) }
      ],
      linhas
    });
  }

  function imprimirGraficoVeiculos() {
    const g = precisaGraficos(); if (!g) return;
    abrirImpressaoRelatorio({
      titulo: 'Custo por veículo', canvasId: 'graficoVeiculos',
      colunas: [
        { rotulo: 'Veículo', render: l => `${SGMF.esc(l.veiculo)}${l.placa ? ' · ' + SGMF.esc(l.placa) : ''}` },
        { rotulo: 'Combustível', classe: 'text-end num', render: l => SGMF.moeda(l.combustivel) },
        { rotulo: 'Manutenção', classe: 'text-end num', render: l => SGMF.moeda(l.manutencao) },
        { rotulo: 'Km/L', classe: 'text-end num', render: l => l.consumo ? SGMF.numero(l.consumo, 2) : '—' },
        { rotulo: 'Km/L (média da média)', classe: 'text-end num',
          render: l => l.consumo_media_da_media ? SGMF.numero(l.consumo_media_da_media, 2) : '—' },
        { rotulo: 'Total', classe: 'text-end num', render: l => SGMF.moeda(l.total) }
      ],
      linhas: g.por_veiculo
    });
  }

  function imprimirGraficoTipos() {
    const g = precisaGraficos(); if (!g) return;
    const linhas = Object.entries(g.tipos_manutencao).map(([tipo, qtd]) => ({ tipo, qtd }));
    abrirImpressaoRelatorio({
      titulo: 'Preventiva × corretiva × emergencial', canvasId: 'graficoTipos',
      colunas: [
        { rotulo: 'Tipo', campo: 'tipo' },
        { rotulo: 'Quantidade de OS', classe: 'text-end num', campo: 'qtd' }
      ],
      linhas
    });
  }

  function imprimirGraficoGrupos() {
    const g = precisaGraficos(); if (!g) return;
    const linhas = g.grupos.labels.map((grupo, i) => ({ grupo, valor: g.grupos.valores[i] }));
    abrirImpressaoRelatorio({
      titulo: 'Custo por grupo de peças', canvasId: 'graficoGrupos',
      colunas: [
        { rotulo: 'Grupo', campo: 'grupo' },
        { rotulo: 'Custo', classe: 'text-end num', render: l => SGMF.moeda(l.valor) }
      ],
      linhas
    });
  }

  // Imprime TODAS as frotas cadastradas com o km/L do período e o km/L do
  // período anterior (mesmo nº de dias), para acompanhar a evolução.
  function imprimirGraficoConsumo() {
    const d = ultimoConsumoFrotas;
    if (!d) return SGMF.aviso('Aguarde os dados carregarem e tente novamente.');

    const kml = v => v ? SGMF.numero(v, 2) : '—';
    const negrito = (l, texto) => l.total ? `<b>${texto}</b>` : texto;
    const rotulos = {
      melhorou: ['▲ Melhorou', '#1B7F3B'], piorou: ['▼ Piorou', '#C0392B'],
      estavel: ['= Estável', '#555'], sem_base: ['— Sem período anterior', '#888'],
      sem_dados: ['— Sem abastecimento', '#888']
    };
    const linhas = [...d.frotas, { ...d.total, total: true }];

    abrirImpressaoRelatorio({
      titulo: 'Consumo por frota (km/L) — comparativo de evolução',
      canvasId: 'graficoConsumo',
      notaExtra: ` · comparado com ${SGMF.data(d.periodo_anterior.inicio)} a ${SGMF.data(d.periodo_anterior.fim)}`,
      rodape: 'Km/L = km rodados ÷ litros no período. ▲ Melhorou = mais km por litro que no período anterior '
            + '(variação abaixo de 1% é considerada estável).',
      colunas: [
        { rotulo: 'Frota', render: l => negrito(l, SGMF.esc(l.veiculo)) },
        { rotulo: 'Placa', render: l => SGMF.esc(l.placa || '') },
        { rotulo: 'Litros', classe: 'text-end num', render: l => negrito(l, l.litros ? SGMF.numero(l.litros, 1) : '—') },
        { rotulo: 'Km rodados', classe: 'text-end num', render: l => negrito(l, l.km ? SGMF.numero(l.km, 0) : '—') },
        { rotulo: 'Km/L anterior', classe: 'text-end num', render: l => negrito(l, kml(l.consumo_anterior)) },
        { rotulo: 'Km/L atual', classe: 'text-end num', render: l => negrito(l, kml(l.consumo)) },
        { rotulo: 'Variação', classe: 'text-end num', render: l => l.variacao === null ? '—'
            : negrito(l, `${l.variacao > 0 ? '+' : ''}${SGMF.numero(l.variacao, 2)} (${l.variacao_pct > 0 ? '+' : ''}${SGMF.numero(l.variacao_pct, 1)}%)`) },
        { rotulo: 'Evolução', render: l => { const [txt, cor] = rotulos[l.evolucao];
            return `<span style="color:${cor};font-weight:bold">${txt}</span>`; } }
      ],
      linhas
    });
  }

  function imprimirGraficoLavagem() {
    const g = precisaGraficos(); if (!g) return;
    const linhas = g.meses.map((mes, i) => ({ mes, valor: g.lavagem_mes[i] }));
    abrirImpressaoRelatorio({
      titulo: 'Gasto com lavagem (últimos 12 meses)', canvasId: 'graficoLavagem', semPeriodo: true,
      colunas: [
        { rotulo: 'Mês', campo: 'mes' },
        { rotulo: 'Lavagem', classe: 'text-end num', render: l => SGMF.moeda(l.valor) }
      ],
      linhas
    });
  }

  function imprimirTopPecas() {
    const g = precisaGraficos(); if (!g) return;
    abrirImpressaoRelatorio({
      titulo: `Peças com maior consumo (Top ${g.top_pecas.length})`, canvasId: 'graficoTopPecas',
      notaExtra: ' · exceto uniformes',
      colunas: [
        { rotulo: '#', classe: 'num', render: (l, i) => i + 1 },
        { rotulo: 'Peça', campo: 'peca' },
        { rotulo: 'Qtde consumida', classe: 'text-end num', render: l => SGMF.numero(l.quantidade, 2) },
        { rotulo: 'Valor', classe: 'text-end num', render: l => SGMF.moeda(l.valor) }
      ],
      linhas: g.top_pecas
    });
  }

  function imprimirGraficoConsumoDiario() {
    if (!ultimoConsumoDiario || !ultimoConsumoDiario.length) {
      return SGMF.aviso('Aguarde o histórico de consumo carregar e tente novamente.');
    }
    abrirImpressaoRelatorio({
      titulo: 'Evolução do consumo da frota (últimos 30 dias)', canvasId: 'graficoConsumoDiario', semPeriodo: true,
      colunas: [
        { rotulo: 'Data', render: l => SGMF.data(l.data) },
        { rotulo: 'Consumo (km/L)', classe: 'text-end num', render: l => SGMF.numero(l.km_por_litro, 2) },
        { rotulo: 'Litros/dia', classe: 'text-end num', render: l => SGMF.numero(l.litros_por_dia, 1) },
        { rotulo: 'Eficiência', campo: 'eficiencia' }
      ],
      linhas: ultimoConsumoDiario
    });
  }

  function imprimirHorasMecanicos() {
    if (!ultimoHorasMecanicos || !ultimoHorasMecanicos.length) {
      return SGMF.aviso('Não há dados para imprimir neste período.');
    }
    abrirImpressaoRelatorio({
      titulo: 'Horas trabalhadas por mecânico', canvasId: 'graficoHorasMecanicos',
      colunas: [
        { rotulo: 'Mecânico', campo: 'mecanico' },
        { rotulo: 'OS', classe: 'text-end num', campo: 'os' },
        { rotulo: 'Horas', classe: 'text-end num', campo: 'horas_str' },
        { rotulo: 'Custo das OS', classe: 'text-end num', render: l => SGMF.moeda(l.custo) }
      ],
      linhas: ultimoHorasMecanicos
    });
  }

  // Litros abastecidos por dia (barras) + km/L do dia (linha) no período do
  // filtro. Os dados vêm da planilha diária importada na tela Combustível.
  async function carregarCombustivelDiario() {
    const d = await SGMF.get(`/api/painel/combustivel-diario?inicio=${inicio()}&fim=${fim()}`);
    const dias = d.dias || [];
    document.getElementById('resumoCombustivelDiario').innerHTML = dias.length ? [
      medidor('Litros no período', SGMF.numero(d.total_litros, 0), { icone: 'fa-droplet', nota: `${dias.length} dia(s) com abastecimento` }),
      medidor('Média por dia', SGMF.numero(d.media_litros_dia, 0), { icone: 'fa-calendar-day', nota: 'litros por dia' }),
      medidor('Consumo do período', `${SGMF.numero(d.km_por_litro, 2)} <small>km/L</small>`, { icone: 'fa-gas-pump' })
    ].join('') : `<div class="text-muted" style="font-size:12.5px">Sem abastecimentos neste período.
      Importe a planilha do dia na tela Combustível.</div>`;

    const rotulo = (iso) => {
      const dia = new Date(iso + 'T12:00:00').toLocaleDateString('pt-BR', { weekday: 'short' }).replace('.', '');
      return `${dia} ${SGMF.data(iso).slice(0, 5)}`;
    };
    SGMF.grafico('graficoCombustivelDiario', {
      type: 'bar',
      data: {
        labels: dias.map(x => rotulo(x.data)),
        datasets: [
          { type: 'bar', label: 'Litros', data: dias.map(x => x.litros), yAxisID: 'y',
            backgroundColor: '#0F3D56', borderRadius: 2 },
          { type: 'line', label: 'Km/L do dia', data: dias.map(x => x.km_por_litro || null), yAxisID: 'y1',
            borderColor: '#F5A800', backgroundColor: '#F5A800', borderWidth: 2, pointRadius: 3, tension: .25 }
        ]
      },
      options: {
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { position: 'bottom' },
          tooltip: { callbacks: {
            label: c => c.dataset.yAxisID === 'y1'
              ? `${SGMF.numero(c.parsed.y, 2)} km/L` : `${SGMF.numero(c.parsed.y, 0)} litros`,
            afterBody: itens => `${dias[itens[0].dataIndex].veiculos} veículo(s) abastecido(s)`
          } }
        },
        scales: {
          x: { grid: { display: false } },
          y: { beginAtZero: true, ticks: { callback: v => SGMF.numero(v) }, grid: { color: '#EBEFF3' } },
          y1: { position: 'right', beginAtZero: true, grid: { drawOnChartArea: false },
                ticks: { callback: v => SGMF.numero(v, 1) } }
        }
      }
    });
  }

  // Km/L de TODAS as frotas no período do filtro e no período anterior. Fica
  // guardado para o botão Imprimir do gráfico "Consumo por veículo".
  async function carregarConsumoFrotas() {
    ultimoConsumoFrotas = await SGMF.get(`/api/painel/consumo-frotas?inicio=${inicio()}&fim=${fim()}`);
  }

  Object.assign(window, {
    imprimirGraficoMeses, imprimirGraficoVeiculos, imprimirGraficoTipos,
    imprimirGraficoGrupos, imprimirGraficoConsumo, imprimirGraficoLavagem, imprimirTopPecas,
    imprimirGraficoConsumoDiario, imprimirHorasMecanicos
  });

  async function atualizar() {
    try {
      await Promise.all([carregarIndicadores(), carregarGraficos(), carregarConsumoDiario(), carregarCombustivelDiario(), carregarConsumoFrotas(),
                         carregarHorasMecanicos(), carregarAlertas(), carregarConectados()]);
    } catch (e) { SGMF.falha(e.message); }
  }

  document.getElementById('botaoAtualizar').onclick = atualizar;
  ['filtroInicio', 'filtroFim'].forEach(id =>
    document.getElementById(id).addEventListener('change', atualizar));
  atualizar();

  // "Conectados agora" muda com o tempo mesmo sem o usuário tocar em nada
  // (login/logout de outra pessoa, sessão que expirou) — atualiza sozinho
  // a cada 30s, sem recarregar gráficos e indicadores do período inteiro.
  setInterval(() => { carregarConectados().catch(() => {}); }, 30000);
})();
