/* SGMF Pro — utilitários compartilhados por todas as telas. */
const SGMF = (() => {

  /* ------------------------------------------------------------ requisições */
  async function api(caminho, opcoes = {}) {
    const resposta = await fetch(caminho, {
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      ...opcoes,
      body: opcoes.corpo ? JSON.stringify(opcoes.corpo) : opcoes.body
    });
    /* Sessão expirada: manda para o login — mas só se ainda não estivermos
       nele. Sem essa checagem, se a própria tela de login (ou algo carregado
       nela) chamar a API, o navegador entra em recarga infinita: pede /login,
       recebe 401, pede /login de novo, sem parar. */
    if (resposta.status === 401) {
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login';
      }
      throw new Error('Sessão expirada. Entre novamente.');
    }
    let dados = null;
    try { dados = await resposta.json(); } catch (e) { dados = null; }
    if (!resposta.ok) throw new Error((dados && dados.erro) || 'Não foi possível concluir a operação.');
    return dados;
  }

  const get = (c) => api(c);
  const post = (c, corpo) => api(c, { method: 'POST', corpo });
  const put = (c, corpo) => api(c, { method: 'PUT', corpo });
  const del = (c) => api(c, { method: 'DELETE' });

  /* --------------------------------------------------------------- avisos */
  const toast = Swal.mixin({
    toast: true, position: 'top-end', showConfirmButton: false,
    timer: 2600, timerProgressBar: true
  });
  const sucesso = (texto) => toast.fire({ icon: 'success', title: texto });
  const falha = (texto) => Swal.fire({ icon: 'error', title: 'Não foi possível salvar',
                                      text: texto, confirmButtonColor: '#0F3D56' });
  /* Para o que o próprio usuário precisa corrigir antes de enviar. */
  const aviso = (texto) => Swal.fire({ icon: 'warning', title: 'Confira antes de continuar',
                                       text: texto, confirmButtonColor: '#0F3D56' });

  async function confirmar(titulo, texto, rotuloAcao = 'Confirmar') {
    const r = await Swal.fire({
      title: titulo, text: texto, icon: 'warning',
      showCancelButton: true, confirmButtonText: rotuloAcao, cancelButtonText: 'Cancelar',
      confirmButtonColor: '#C4451D', cancelButtonColor: '#5F7080', reverseButtons: true
    });
    return r.isConfirmed;
  }

  /* ------------------------------------------------------------- segurança */
  /* Texto digitado pelo usuário nunca vira HTML: um nome como
     "<img src=x onerror=...>" precisa aparecer como texto, não executar. */
  const MAPA_ESCAPE = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  const esc = (valor) => (valor === null || valor === undefined)
    ? '' : String(valor).replace(/[&<>"']/g, (c) => MAPA_ESCAPE[c]);
  /* Preserva números, datas e booleanos; escapa apenas texto. */
  const escSeTexto = (valor) => typeof valor === 'string' ? esc(valor) : valor;
  const escObjeto = (obj) => {
    const copia = {};
    Object.keys(obj || {}).forEach(k => copia[k] = escSeTexto(obj[k]));
    return copia;
  };

  /* ------------------------------------------------------------ formatação */
  const moeda = (v) => (Number(v) || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
  const numero = (v, casas = 0) => (Number(v) || 0).toLocaleString('pt-BR', {
    minimumFractionDigits: casas, maximumFractionDigits: casas
  });
  const data = (v) => v ? new Date(v + 'T00:00:00').toLocaleDateString('pt-BR') : '—';
  /* Usa a data local do navegador (fuso do usuário), nunca UTC: toISOString()
     converte para UTC e, à noite no Brasil, devolvia o dia seguinte —
     fazendo o registro nascer com data "no futuro" e sumir da listagem,
     que é filtrada pela data de hoje calculada no servidor (fuso correto). */
  const paraISO = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const hoje = () => paraISO(new Date());
  const primeiroDiaMes = () => { const d = new Date(); d.setDate(1); return paraISO(d); };

  const etiqueta = (texto, cor) => `<span class="etiqueta ${esc(cor)}">${esc(texto)}</span>`;

  const CORES_STATUS = {
    'Disponível': 'verde', 'Em manutenção': 'ambar', 'Inativo': 'cinza',
    'Aberta': 'azul', 'Em execução': 'ambar', 'Aguardando peça': 'vermelha', 'Finalizada': 'verde',
    'Preventiva': 'verde', 'Corretiva': 'ambar', 'Emergencial': 'vermelha',
    'Baixa': 'cinza', 'Média': 'azul', 'Alta': 'ambar', 'Crítica': 'vermelha',
    'Em uso': 'verde', 'Estoque': 'azul', 'Descartado': 'cinza'
  };
  const status = (v) => v ? etiqueta(v, CORES_STATUS[v] || 'cinza') : '—';

  /* ------------------------------------------ listas usadas nos formulários */
  const cache = {};
  async function opcoes(recurso, rotulo = 'identificacao') {
    if (!cache[recurso]) cache[recurso] = await get(`/api/${recurso}`);
    return cache[recurso].map(i => ({ valor: i.id, texto: i[rotulo] || i.nome || i.descricao }));
  }
  const limparCache = (recurso) => { if (recurso) delete cache[recurso]; else Object.keys(cache).forEach(k => delete cache[k]); };

  const GRUPOS = ['Motor', 'Suspensão', 'Freios', 'Elétrica', 'Hidráulica', 'Pneus',
    'Transmissão', 'Arrefecimento', 'Outros'];
  const POSICOES = ['Dianteiro Esquerdo', 'Dianteiro Direito',
    'Traseiro Esquerdo Externo', 'Traseiro Esquerdo Interno',
    'Traseiro Direito Externo', 'Traseiro Direito Interno',
    'Eixo 3 Esquerdo', 'Eixo 3 Direito', 'Estepe'];

  /* -------------------------------------------------------------- gráficos */
  Chart.defaults.font.family = "Inter, system-ui, sans-serif";
  Chart.defaults.font.size = 11.5;
  Chart.defaults.color = '#5F7080';
  const PALETA = ['#0F3D56', '#F5A800', '#16795D', '#C4451D', '#17587B',
    '#8A5D00', '#5F7080', '#7FA9C2', '#B9CDD9'];

  const registro = {};
  function grafico(id, config) {
    const el = document.getElementById(id);
    if (!el) return null;
    if (registro[id]) registro[id].destroy();
    registro[id] = new Chart(el, config);
    return registro[id];
  }

  /* ---------------------------------------------------------------- alertas */
  async function carregarContadorAlertas() {
    try {
      const lista = await get('/api/painel/alertas');
      const criticos = lista.filter(a => a.nivel === 'critico').length;
      const el = document.getElementById('contadorAlertas');
      if (el && lista.length) {
        el.textContent = lista.length;
        el.style.background = criticos ? 'var(--alerta)' : 'var(--hi-vis)';
        el.style.color = criticos ? '#fff' : 'var(--aco)';
        el.classList.remove('d-none');
      }
      return lista;
    } catch (e) { return []; }
  }

  /* ---------------------------------------------------------------- imprimir */
  /* Abre uma janela só com o conteúdo do elemento informado (normalmente uma
     tabela de relatório/ranking), formatado para impressão, e já chama o
     diálogo de impressão do navegador. Usado pelos botões "Imprimir" das
     telas de Relatórios e Rankings. */
  function imprimir(idOuElemento, titulo) {
    const el = typeof idOuElemento === 'string' ? document.getElementById(idOuElemento) : idOuElemento;
    if (!el) return aviso('Não encontrei o conteúdo para imprimir.');

    const inicioEl = document.getElementById('filtroInicio') || document.getElementById('rInicio');
    const fimEl = document.getElementById('filtroFim') || document.getElementById('rFim');
    const periodo = (inicioEl && fimEl && inicioEl.value && fimEl.value)
      ? `Período de ${data(inicioEl.value)} a ${data(fimEl.value)} · ` : '';
    const geradoEm = new Date().toLocaleString('pt-BR');

    const janela = window.open('', '_blank', 'width=1000,height=720');
    if (!janela) return aviso('Seu navegador bloqueou a janela de impressão. Libere pop-ups para este site.');

    janela.document.write(`<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">
      <title>${esc(titulo)} · SGMF Pro</title>
      <style>
        * { box-sizing: border-box; }
        body { font-family: Arial, Helvetica, sans-serif; color: #182530; padding: 26px 30px; }
        h1 { font-size: 19px; margin: 0 0 2px; color: #0F3D56; }
        .sub { font-size: 12px; color: #666; margin-bottom: 18px; }
        table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
        th, td { border: 1px solid #D3DBE2; padding: 6px 9px; text-align: left; }
        th { background: #0F3D56; color: #fff; text-transform: uppercase; font-size: 10.5px; letter-spacing: .02em; }
        tr:nth-child(even) td { background: #F5F7F9; }
        .num, .text-end { text-align: right; }
        .etiqueta { display: inline-block; padding: 1px 7px; border-radius: 3px; font-size: 10.5px; }
        .prefixo, .placa { font-weight: 600; }
        .rodape-impressao { margin-top: 16px; font-size: 10.5px; color: #888; }
        @media print { @page { margin: 14mm; } }
      </style>
      </head><body>
      <h1>SGMF Pro · ${esc(titulo)}</h1>
      <div class="sub">${periodo}Gerado em ${geradoEm}</div>
      ${el.outerHTML}
      <div class="rodape-impressao">Sistema de Gestão de Manutenção de Frotas</div>
      </body></html>`);
    janela.document.close();
    janela.onload = () => { janela.focus(); janela.print(); };
  }

  /* ------------------------------------------------------------- permissão */
  const perfil = () => window.SGMF_PERFIL || 'operador';
  const nivelNaTela = (tela) => {
    if (perfil() === 'admin') return 'editar';
    const mapa = window.SGMF_PERMISSOES || {};
    return mapa[tela] || 'nenhum';
  };
  const podeVer = (tela) => nivelNaTela(tela) !== 'nenhum';
  const podeEditar = (tela) => nivelNaTela(tela) === 'editar';
  /* Compatível com o uso antigo (sem tela): olha o perfil global.
     Passando `tela`, verifica o nível específico daquela tela. */
  const somenteLeitura = (tela) => tela ? !podeEditar(tela) : perfil() === 'consulta';

  /* ------------------------------------------------------- trocar a senha */
  async function trocarSenha() {
    const atual = document.getElementById('senhaAtual').value;
    const nova = document.getElementById('senhaNova').value;
    const confirma = document.getElementById('senhaConfirma').value;

    if (!atual || !nova) return aviso('Preencha a senha atual e a nova senha.');
    if (nova.length < 6) return aviso('A nova senha precisa de pelo menos 6 caracteres.');
    if (nova !== confirma) return aviso('As duas senhas novas não são iguais.');

    try {
      await post('/api/trocar-senha', { atual, nova });
      bootstrap.Modal.getInstance(document.getElementById('modalMinhaConta')).hide();
      sucesso('Senha alterada');
      ['senhaAtual', 'senhaNova', 'senhaConfirma'].forEach(id => document.getElementById(id).value = '');
    } catch (e) { falha(e.message); }
  }

  document.addEventListener('DOMContentLoaded', () => {
    carregarContadorAlertas();

    const abrir = document.getElementById('abrirMinhaConta');
    if (abrir) abrir.onclick = () =>
      bootstrap.Modal.getOrCreateInstance(document.getElementById('modalMinhaConta')).show();

    const salvar = document.getElementById('salvarSenha');
    if (salvar) salvar.onclick = trocarSenha;

    const confirma = document.getElementById('senhaConfirma');
    if (confirma) confirma.addEventListener('keydown', e => { if (e.key === 'Enter') trocarSenha(); });

    if (somenteLeitura()) {
      const novo = document.getElementById('botaoNovo');
      if (novo) novo.remove();
    }
  });

  return {
    api, get, post, put, del, toast, sucesso, falha, aviso, confirmar,
    esc, escSeTexto, escObjeto,
    moeda, numero, data, hoje, primeiroDiaMes, etiqueta, status,
    opcoes, limparCache, grafico, PALETA, GRUPOS, POSICOES, carregarContadorAlertas,
    perfil, somenteLeitura, podeVer, podeEditar, nivelNaTela, imprimir
  };
})();
