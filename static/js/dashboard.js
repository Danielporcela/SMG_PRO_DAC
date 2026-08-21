/* Painel principal — indicadores, gráficos e alertas do período. */
(function () {
  const inicio = () => document.getElementById('filtroInicio').value;
  const fim = () => document.getElementById('filtroFim').value;

  let ultimosGraficos = null; // guarda o retorno de /api/painel/graficos para a impressão

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
        icone: 'fa-gas-pump', nota: `${SGMF.numero(d.litros, 1)} litros` }),
      medidor('Custo por km', SGMF.moeda(d.custo_por_km), {
        icone: 'fa-coins', estilo: 'font-size:21px' }),
      medidor('Combustível', SGMF.moeda(d.gasto_combustivel), {
        icone: 'fa-fill-drip', estilo: 'font-size:19px', nota: `${d.abastecimentos} abastecimentos` }),
      medidor('Manutenção', SGMF.moeda(d.gasto_manutencao), {
        icone: 'fa-wrench', estilo: 'font-size:19px',
        nota: `${d.os_preventivas} preventivas · ${d.os_corretivas} corretivas` }),
      medidor('Gasto total', SGMF.moeda(d.gasto_total), {
        classe: d.orcamento_mes && d.aderencia_orcamento > 100 ? 'critico' : '',
        icone: 'fa-sack-dollar', estilo: 'font-size:19px', nota: aderencia }),
      medidor('MTTR', `${SGMF.numero(d.mttr_dias, 1)} <small>dias</small>`, {
        icone: 'fa-clock-rotate-left', nota: 'para reparo' }),
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
      medidor('Prazo médio de atendimento', d.prazo_medio_atendimento === null
          ? '—' : `${SGMF.numero(d.prazo_medio_atendimento, 1)} <small>dias</small>`, {
        icone: 'fa-hourglass-half',
        classe: d.prazo_medio_atendimento !== null && d.prazo_medio_atendimento > 5 ? 'atencao' : '',
        nota: d.prazo_medio_atendimento === null
          ? 'Nenhuma OS finalizada no período'
          : `${d.os_finalizadas} OS finalizada(s)` }),
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
          { type: 'bar', label: 'Manutenção', data: g.manutencao_mes,
            backgroundColor: '#7FA9C2', stack: 'gasto', borderRadius: 2 },
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
          <th class="text-end">Km/L</th><th class="text-end">Custo/km</th>
          <th class="text-end pe-3">Total</th></tr></thead>
          <tbody>${top.map(v => `<tr>
            <td class="ps-3"><span class="prefixo">${SGMF.esc(v.veiculo)}</span>
              <span class="placa ms-1">${SGMF.esc(v.placa)}</span></td>
            <td class="text-end num">${SGMF.numero(v.km)}</td>
            <td class="text-end num">${v.consumo ? SGMF.numero(v.consumo, 2) : '—'}</td>
            <td class="text-end num">${v.custo_km ? SGMF.moeda(v.custo_km) : '—'}</td>
            <td class="text-end num pe-3"><strong>${SGMF.moeda(v.total)}</strong></td>
          </tr>`).join('')}</tbody></table>`
      : `<div class="vazio"><i class="fa-solid fa-chart-simple"></i>
          <strong>Sem lançamentos no período</strong>Registre abastecimentos e ordens de serviço.</div>`;
  }

  async function carregarAlertas() {
    const lista = await SGMF.carregarContadorAlertas();
    const icones = { critico: 'fa-circle-exclamation', atencao: 'fa-triangle-exclamation', info: 'fa-circle-info' };
    const area = document.getElementById('painelAlertas');
    area.innerHTML = lista.length
      ? lista.slice(0, 12).map(a => `<div class="alerta-item ${a.nivel}">
          <div class="icone"><i class="fa-solid ${icones[a.nivel]}"></i></div>
          <div><div class="titulo">${SGMF.esc(a.titulo)}</div>
               <div class="detalhe">${SGMF.esc(a.detalhe)}</div></div></div>`).join('')
      : `<div class="vazio"><i class="fa-solid fa-circle-check" style="color:var(--ok)"></i>
          <strong>Nenhum alerta ativo</strong>Preventivas, pneus e orçamento estão dentro do previsto.</div>`;
  }

  /* Impressão genérica de "gráfico + tabela": qualquer card de gráfico do
     painel usa esta mesma função, só muda o título, o canvas e as colunas.
     Canvas não sai no SGMF.imprimir() normal (que só copia outerHTML de
     tabelas), então aqui a gente converte o gráfico em imagem
     (canvas.toDataURL) e monta a janela de impressão na mão, no mesmo
     estilo da impressão de OS. */
  function abrirImpressaoRelatorio({ titulo, canvasId, colunas, linhas, notaExtra = '', semPeriodo = false }) {
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
      <div class="rodape-impressao">Sistema de Gestão de Manutenção de Frotas</div>
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
      meta: g.meta_mes[i], realizado: g.realizado_mes[i]
    }));
    abrirImpressaoRelatorio({
      titulo: 'Gasto mensal e meta (últimos 12 meses)', canvasId: 'graficoMeses', semPeriodo: true,
      colunas: [
        { rotulo: 'Mês', campo: 'mes' },
        { rotulo: 'Combustível', classe: 'text-end num', render: l => SGMF.moeda(l.combustivel) },
        { rotulo: 'Manutenção', classe: 'text-end num', render: l => SGMF.moeda(l.manutencao) },
        { rotulo: 'Meta', classe: 'text-end num', render: l => SGMF.moeda(l.meta) },
        { rotulo: 'Realizado', classe: 'text-end num', render: l => SGMF.moeda(l.realizado) }
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

  function imprimirGraficoConsumo() {
    const g = precisaGraficos(); if (!g) return;
    abrirImpressaoRelatorio({
      titulo: 'Consumo por veículo (km/L)', canvasId: 'graficoConsumo',
      colunas: [
        { rotulo: 'Veículo', campo: 'veiculo' },
        { rotulo: 'Km/L', classe: 'text-end num', render: l => SGMF.numero(l.consumo, 2) }
      ],
      linhas: g.consumo_veiculo
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

  Object.assign(window, {
    imprimirGraficoMeses, imprimirGraficoVeiculos, imprimirGraficoTipos,
    imprimirGraficoGrupos, imprimirGraficoConsumo, imprimirTopPecas
  });

  async function atualizar() {
    try {
      await Promise.all([carregarIndicadores(), carregarGraficos(), carregarAlertas()]);
    } catch (e) { SGMF.falha(e.message); }
  }

  document.getElementById('botaoAtualizar').onclick = atualizar;
  ['filtroInicio', 'filtroFim'].forEach(id =>
    document.getElementById(id).addEventListener('change', atualizar));
  atualizar();
})();
