/* Painel principal — indicadores, gráficos e alertas do período. */
(function () {
  const inicio = () => document.getElementById('filtroInicio').value;
  const fim = () => document.getElementById('filtroFim').value;

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
      medidor('MTBF', `${SGMF.numero(d.mtbf_dias, 1)} <small>dias</small>`, {
        icone: 'fa-stopwatch', nota: 'entre falhas' }),
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
