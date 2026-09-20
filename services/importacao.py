"""Importação de cadastros a partir de planilhas Excel.

A ideia é carregar a frota, os motoristas, as oficinas e o estoque inicial sem
digitar item por item. O fluxo é sempre o mesmo:

1. o usuário baixa o modelo da planilha (já com os cabeçalhos certos);
2. envia a planilha preenchida e o sistema mostra uma prévia com os erros;
3. só depois de conferir é que os dados são gravados.

Nada é gravado pela metade: se a gravação falhar, a transação é desfeita.
"""
import io
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from extensions import db
from models import Abastecimento, Fornecedor, Motorista, Peca, Veiculo
from services.calculos import movimentar_estoque
from services.crud import ErroNegocio
from services.tempo import ler_data

# Cada modelo declara suas colunas: (cabeçalho, campo, tipo, obrigatório, exemplo)
MODELOS = {
    "veiculos": {
        "titulo": "Veículos",
        "modelo": Veiculo,
        "chave": "placa",
        "colunas": [
            ("Prefixo", "prefixo", "texto", True, "FR-101"),
            ("Placa", "placa", "placa", True, "ABC1D23"),
            ("Marca", "marca", "texto", False, "Mercedes-Benz"),
            ("Modelo", "modelo", "texto", False, "OF-1721"),
            ("Ano", "ano", "inteiro", False, 2019),
            ("Tipo", "tipo", "texto", False, "Ônibus"),
            ("Combustível", "combustivel", "texto", False, "Diesel S10"),
            ("Centro de custo", "centro_custo", "texto", False, "Transporte escolar"),
            ("Setor", "setor", "texto", False, "Operação"),
            ("Hodômetro", "hodometro", "numero", False, 120000),
            ("Km última troca de óleo", "km_ultima_troca_oleo", "numero", False, 118000),
            ("Intervalo de troca (km)", "intervalo_troca_oleo", "numero", False, 10000),
            ("Última preventiva", "data_ultima_preventiva", "data", False, "2026-05-20"),
            ("Intervalo preventiva (dias)", "intervalo_preventiva_dias", "inteiro", False, 90),
            ("Orçamento mensal", "orcamento_mensal", "numero", False, 5000),
        ],
    },
    "motoristas": {
        "titulo": "Motoristas",
        "modelo": Motorista,
        "chave": None,
        "colunas": [
            ("Nome", "nome", "texto", True, "João da Silva"),
            ("Matrícula", "matricula", "texto", False, "1234"),
            ("CNH", "cnh", "texto", False, "01234567890"),
            ("Categoria", "categoria_cnh", "texto", False, "D"),
            ("Validade da CNH", "validade_cnh", "data", False, "2028-03-15"),
            ("Telefone", "telefone", "texto", False, "(00) 90000-0000"),
            ("Setor", "setor", "texto", False, "Operação"),
        ],
    },
    "fornecedores": {
        "titulo": "Oficinas, postos e fornecedores",
        "modelo": Fornecedor,
        "chave": None,
        "colunas": [
            ("Nome", "nome", "texto", True, "Oficina Central"),
            ("Tipo", "tipo", "texto", False, "Oficina"),
            ("CNPJ", "cnpj", "texto", False, "00.000.000/0001-00"),
            ("Telefone", "telefone", "texto", False, "(00) 0000-0000"),
            ("Contato", "contato", "texto", False, "Carlos"),
            ("Cidade", "cidade", "texto", False, "Sua Cidade"),
        ],
    },
    "pecas": {
        "titulo": "Estoque de peças",
        "modelo": Peca,
        "chave": "codigo",
        "colunas": [
            ("Código", "codigo", "texto", True, "FIL-001"),
            ("Descrição", "descricao", "texto", True, "Filtro de óleo motor"),
            ("Grupo", "grupo", "texto", False, "Motor"),
            ("Unidade", "unidade", "texto", False, "UN"),
            ("Saldo inicial", "quantidade_inicial", "numero", False, 20),
            ("Custo unitário", "custo_unitario", "numero", False, 48.90),
            ("Estoque mínimo", "estoque_minimo", "numero", False, 5),
            ("Localização", "localizacao", "texto", False, "Prateleira A1"),
        ],
    },
}

LIMITE_LINHAS = 5000


def gerar_modelo(tipo):
    """Monta o arquivo .xlsx que o usuário baixa para preencher."""
    config = _config(tipo)
    wb = Workbook()
    ws = wb.active
    ws.title = config["titulo"][:31]

    cabecalhos = [c[0] for c in config["colunas"]]
    ws.append(cabecalhos)
    ws.append([c[4] for c in config["colunas"]])   # linha de exemplo

    fundo = PatternFill("solid", fgColor="0F3D56")
    for indice, coluna in enumerate(config["colunas"], start=1):
        celula = ws.cell(row=1, column=indice)
        celula.font = Font(bold=True, color="FFFFFF")
        celula.fill = fundo
        celula.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        if coluna[3]:
            celula.value = f"{coluna[0]} *"
        ws.column_dimensions[get_column_letter(indice)].width = max(len(coluna[0]) + 6, 14)
    for celula in ws[2]:
        celula.font = Font(italic=True, color="8A8A8A")
    ws.freeze_panes = "A2"

    ws.append([])
    ws.append(["Colunas com * são obrigatórias. Apague a linha de exemplo antes de enviar."])
    ws.cell(row=ws.max_row, column=1).font = Font(italic=True, size=9, color="666666")

    saida = io.BytesIO()
    wb.save(saida)
    saida.seek(0)
    return saida


def _config(tipo):
    if tipo not in MODELOS:
        raise ErroNegocio("Tipo de importação desconhecido.")
    return MODELOS[tipo]


def _converter(valor, tipo, cabecalho):
    """Converte valores mantendo tipos nativos do Excel (especialmente datas)."""
    if valor is None or (isinstance(valor, str) and valor.strip() == ""):
        return None
    if tipo == "data":
        try:
            # openpyxl devolve datetime/date quando a célula é uma data real.
            return ler_data(valor, cabecalho)
        except (ValueError, TypeError, ErroNegocio):
            raise ValueError(f"'{cabecalho}' com valor inválido: {valor}")

    texto = str(valor).strip()
    try:
        if tipo == "inteiro":
            return int(float(texto.replace(".", "").replace(",", ".")))
        if tipo == "numero":
            return float(texto.replace(" ", "").replace(".", "").replace(",", ".")) \
                if texto.count(",") == 1 else float(texto.replace(" ", ""))
        if tipo == "placa":
            return texto.upper().replace("-", "").replace(" ", "")
    except (ValueError, TypeError, ErroNegocio):
        raise ValueError(f"'{cabecalho}' com valor inválido: {texto}")
    return texto


def ler_planilha(tipo, arquivo):
    """Lê a planilha e devolve as linhas já conferidas, com os erros apontados."""
    config = _config(tipo)
    try:
        wb = load_workbook(arquivo, data_only=True, read_only=True)
    except Exception:
        raise ErroNegocio("Não consegui abrir a planilha. Envie um arquivo .xlsx.")

    ws = wb.active
    linhas_brutas = list(ws.iter_rows(values_only=True))
    if not linhas_brutas:
        raise ErroNegocio("A planilha está vazia.")

    cabecalho = [str(c).replace("*", "").strip().lower() if c else ""
                 for c in linhas_brutas[0]]
    indices = {}
    faltando = []
    for titulo, campo, tipo_campo, obrigatorio, _ in config["colunas"]:
        chave = titulo.lower()
        if chave in cabecalho:
            indices[campo] = cabecalho.index(chave)
        elif obrigatorio:
            faltando.append(titulo)
    if faltando:
        raise ErroNegocio("A planilha não tem as colunas: " + ", ".join(faltando) +
                          ". Baixe o modelo e use os mesmos cabeçalhos.")

    existentes = set()
    if config["chave"]:
        coluna = getattr(config["modelo"], config["chave"])
        existentes = {str(v[0]).upper() for v in db.session.query(coluna).all() if v[0]}

    vistos = set()
    prontas, problemas = [], []

    for numero, bruta in enumerate(linhas_brutas[1:], start=2):
        if numero - 1 > LIMITE_LINHAS:
            problemas.append({"linha": numero, "erro":
                              f"A planilha passa de {LIMITE_LINHAS} linhas. Divida em partes."})
            break
        if not any(c is not None and str(c).strip() != "" for c in bruta):
            continue

        registro, erros = {}, []
        for titulo, campo, tipo_campo, obrigatorio, _ in config["colunas"]:
            if campo not in indices:
                continue
            posicao = indices[campo]
            valor = bruta[posicao] if posicao < len(bruta) else None
            try:
                convertido = _converter(valor, tipo_campo, titulo)
            except ValueError as e:
                erros.append(str(e))
                continue
            if obrigatorio and convertido in (None, ""):
                erros.append(f"'{titulo}' é obrigatório")
            registro[campo] = convertido

        if config["chave"]:
            chave = str(registro.get(config["chave"]) or "").upper()
            if chave and chave in existentes:
                erros.append(f"já existe no sistema ({chave})")
            elif chave and chave in vistos:
                erros.append(f"repetido na própria planilha ({chave})")
            elif chave:
                vistos.add(chave)

        if tipo == "veiculos" and not erros:
            from services.grupos_consumo import nome_grupo_consumo_legado
            candidato = Veiculo(**registro)
            grupo_consumo = nome_grupo_consumo_legado(candidato)
            if grupo_consumo:
                erros.append(
                    f"{grupo_consumo} é grupo de consumo. Use o menu Grupos de consumo.")

        # As datas saem como texto ISO para atravessar o JSON da prévia e
        # voltarem íntegras na hora de gravar.
        registro = {k: (v.isoformat() if isinstance(v, date) else v)
                    for k, v in registro.items()}

        if erros:
            problemas.append({"linha": numero, "erro": "; ".join(erros),
                              "dados": {k: str(v) for k, v in registro.items() if v is not None}})
        else:
            prontas.append({"linha": numero, "dados": registro})

    return {"tipo": tipo, "titulo": config["titulo"],
            "colunas": [c[0] for c in config["colunas"] if c[1] in indices],
            "campos": [c[1] for c in config["colunas"] if c[1] in indices],
            "prontas": prontas, "problemas": problemas,
            "total": len(prontas) + len(problemas)}


def gravar(tipo, linhas):
    """Grava as linhas aprovadas. Ou entra tudo, ou não entra nada."""
    config = _config(tipo)
    Model = config["modelo"]
    if not linhas:
        raise ErroNegocio("Não há linhas válidas para importar.")

    tipos = {campo: (titulo, tipo_campo)
             for titulo, campo, tipo_campo, _, _ in config["colunas"]}
    gravadas = 0
    try:
        for item in linhas:
            bruto = dict(item.get("dados") or item)
            # Reconverte o que veio da tela: o JSON não guarda datas nem números.
            dados = {}
            for campo, valor in bruto.items():
                if campo not in tipos:
                    continue
                titulo, tipo_campo = tipos[campo]
                dados[campo] = _converter(valor, tipo_campo, titulo)
            saldo = dados.pop("quantidade_inicial", None)
            custo = dados.get("custo_unitario") or 0
            obj = Model(**dados)
            if tipo == "veiculos":
                from services.grupos_consumo import nome_grupo_consumo_legado
                grupo_consumo = nome_grupo_consumo_legado(obj)
                if grupo_consumo:
                    raise ErroNegocio(
                        f"{grupo_consumo} é grupo de consumo. Use o menu Grupos de consumo.")
            db.session.add(obj)
            db.session.flush()
            if tipo == "pecas" and saldo:
                movimentar_estoque(obj.id, "entrada", saldo, custo,
                                   documento="Importação de planilha")
            gravadas += 1
        db.session.commit()
    except ErroNegocio:
        db.session.rollback()
        raise
    except Exception as e:
        db.session.rollback()
        raise ErroNegocio(f"A importação foi cancelada e nada foi gravado "
                          f"({e.__class__.__name__}). Confira a planilha e tente de novo.")
    return gravadas


# -------------------------------------------------------- Abastecimentos
# Importação específica do módulo de combustível. O arquivo do usuário usa
# "VEÍCULO" como prefixo da frota e traz os campos calculados "KM PERC" e
# "KM/L". Esses dois últimos não são confiados: o SGMF recalcula a partir do
# histórico real do veículo, evitando divergências no Dashboard.
COLUNAS_ABASTECIMENTOS = [
    ("VEÍCULO", "veiculo", "texto", True),
    ("DATA", "data", "data", True),
    ("LITROS", "litros", "numero", True),
    ("KM", "km_atual", "numero", True),
]

LIMITE_ABASTECIMENTOS = 5000
LIMITE_SALTO_KM = 2000            # salto de KM acima disso quase sempre é erro de digitação
ABA_LANCAMENTO = "LANCAMENTO"   # nome da aba do dia (comparado sem acento/caixa)


def _sem_acento(texto):
    base = unicodedata.normalize("NFKD", str(texto if texto is not None else ""))
    return "".join(c for c in base if not unicodedata.combining(c)).upper().strip()


def _chave_frota(valor):
    """Número da frota comparável: 1, 1.0, '01' e '01 · ABC1D23' viram '1'."""
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    texto = str(valor).strip().upper()
    if "·" in texto:
        texto = texto.split("·", 1)[0].strip()
    if texto.isdigit():
        return str(int(texto))
    return texto.replace(" ", "")


def _vazio(valor):
    return valor is None or str(valor).strip() == ""


def _limpa_placa(valor):
    """Placa comparável: maiúscula, sem hífen/espaço e SEM os números da frota
    que o cadastro guarda na frente (ex.: '01JBH6B46' e '01-JBH6B46' viram
    'JBH6B46'). Placa de verdade nunca começa com número, então qualquer
    dígito inicial é prefixo da frota."""
    texto = re.sub(r"[^A-Z0-9]", "", str(valor if valor is not None else "").upper())
    return re.sub(r"^\d+", "", texto)


def _separar_frota(bruto):
    """Separa o rótulo da planilha em (nº da frota, placa).

    '01-JBH6B46' -> ('01', 'JBH6B46'); '15RQY7I16' -> ('15', 'RQY7I16');
    '7' -> ('7', ''); 'JBH6B46' -> ('', 'JBH6B46').
    """
    texto = str(bruto if bruto is not None else "").strip().upper()
    if isinstance(bruto, float) and bruto.is_integer():
        texto = str(int(bruto))
    achou = re.match(r"^(\d+)\s*[-–—·]?\s*([A-Z0-9]{5,8})?$", texto)
    if achou:
        return achou.group(1), achou.group(2) or ""
    return "", _limpa_placa(texto) if re.search(r"[A-Z]", texto) else ""


def _data_da_planilha(valor):
    """Aceita data real do Excel, número de série do Excel, dd/mm/aaaa e ISO."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, (int, float)) and not isinstance(valor, bool) and 20000 < valor < 80000:
        return date(1899, 12, 30) + timedelta(days=int(valor))
    texto = str(valor).strip()
    for formato in ("%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            pass
    return ler_data(valor, "DATA")


def _milhar(numero):
    return f"{numero:,.0f}".replace(",", ".")


def _cabecalho_abastecimentos(ws):
    """Acha a linha de títulos (1ª das 10 primeiras com VEÍCULO e DATA)."""
    for numero, linha in enumerate(ws.iter_rows(min_row=1, max_row=10, values_only=True), start=1):
        titulos = [_sem_acento(str(c).replace("*", "")) if c is not None else "" for c in linha]
        if "VEICULO" in titulos and "DATA" in titulos:
            indices = {}
            for pos, titulo in enumerate(titulos):
                if titulo:
                    indices.setdefault(titulo, pos)
            return indices, numero
    return None, None


def _escolher_aba_abastecimentos(wb):
    """Prefere a aba LANÇAMENTO; depois qualquer aba visível com as colunas
    certas; por último uma aba oculta (ex.: a base LANÇAM)."""
    candidatas = []
    for ws in wb.worksheets:
        indices, linha_titulos = _cabecalho_abastecimentos(ws)
        if not indices or not all(t in indices for t in ("VEICULO", "DATA", "LITROS", "KM")):
            continue
        if _sem_acento(ws.title) == ABA_LANCAMENTO:
            prioridade = 0
        elif getattr(ws, "sheet_state", "visible") == "visible":
            prioridade = 1
        else:
            prioridade = 2
        candidatas.append((prioridade, ws, indices, linha_titulos))
    if not candidatas:
        return None
    candidatas.sort(key=lambda c: c[0])
    return candidatas[0][1:]


def ler_abastecimentos(arquivo):
    """Confere a planilha do dia SEM gravar nada e devolve a prévia.

    Regras que evitam sujeira no painel:
    - linha sem LITROS e sem KM = veículo que não abasteceu no dia (não é
      erro; só é listada à parte); a linha TOTAL é ignorada;
    - o nº da frota casa com o prefixo do cadastro mesmo com/sem zero à
      esquerda (1 = 01) ou pela placa;
    - KM menor que o último já lançado para o veículo, ou um salto absurdo
      (mais de LIMITE_SALTO_KM), é recusado — faria o km/L e os gráficos
      saírem errados;
    - veículo já lançado no mesmo dia (no sistema ou na própria planilha)
      é recusado — evita litros em dobro ao reenviar o arquivo.
    """
    try:
        wb = load_workbook(arquivo, data_only=True, read_only=True)
    except Exception:
        raise ErroNegocio("Não consegui abrir a planilha. Envie um arquivo .xlsx ou .xlsm.")

    escolhida = _escolher_aba_abastecimentos(wb)
    if not escolhida:
        raise ErroNegocio("Não encontrei uma aba com as colunas VEÍCULO, DATA, LITROS e KM. "
                          "Use a aba LANÇAMENTO do modelo de lançamento de diesel.")
    ws, indices, linha_titulos = escolhida

    # Cadastro da frota: prefixo exato, prefixo normalizado (1 = 01) e placa.
    veiculos = Veiculo.query.filter(Veiculo.ativo.is_(True)).all()
    por_prefixo, por_prefixo_normal, por_placa = {}, defaultdict(list), {}
    for v in veiculos:
        prefixo = str(v.prefixo or "").strip().upper()
        if prefixo:
            por_prefixo[prefixo] = v
            por_prefixo_normal[_chave_frota(prefixo)].append(v)
        if v.placa:
            por_placa[_limpa_placa(v.placa)] = v

    def localizar(bruto):
        """Aceita '1', '01', '01-JBH6B46', 'JBH6B46'. A placa é a chave mais
        segura; o nº da frota vale quando a placa não vem, e se vier
        divergente do cadastro a linha é recusada (evita lançar no veículo
        errado por causa de um erro de digitação na placa)."""
        texto = str(bruto if bruto is not None else "").strip().upper()
        if texto in por_prefixo:
            return por_prefixo[texto], None
        numero, placa = _separar_frota(bruto)
        v_placa = por_placa.get(placa) if placa else None
        candidatos = por_prefixo_normal.get(_chave_frota(numero), []) if numero else []
        if len(candidatos) > 1:
            return None, f"frota '{numero}' aparece em mais de um prefixo do cadastro"
        v_numero = candidatos[0] if candidatos else None
        if v_placa and v_numero and v_placa is not v_numero:
            return None, (f"frota {numero} e placa {placa} apontam para veículos diferentes "
                          f"no cadastro ({v_numero.rotulo} × {v_placa.rotulo})")
        if v_placa:
            return v_placa, None
        if v_numero:
            if placa and v_numero.placa and _limpa_placa(v_numero.placa) != placa:
                return None, (f"placa {placa} não confere com o cadastro "
                              f"(frota {numero} = {v_numero.placa_exibicao}) — corrija a planilha")
            return v_numero, None
        return None, f"veículo '{texto}' não encontrado no cadastro da frota"

    # ---- 1ª passada: lê e converte cada linha (sem consultar o banco) ------
    linhas, sem_abastecimento, lidas = [], [], 0
    for numero, bruta in enumerate(ws.iter_rows(min_row=linha_titulos + 1, values_only=True),
                                   start=linha_titulos + 1):
        if not any(c is not None and str(c).strip() != "" for c in bruta):
            continue

        def celula(titulo):
            pos = indices[titulo]
            return bruta[pos] if pos < len(bruta) else None

        rotulo = str(celula("VEICULO") if celula("VEICULO") is not None else "").strip()
        if _sem_acento(rotulo).startswith("TOTAL"):
            continue

        lidas += 1
        # Nº da linha de dados: a 1ª linha abaixo dos títulos é a linha 1
        # (frota 01 = linha 1, frota 02 = linha 2...), e não a linha 2 do Excel.
        numero_dado = numero - linha_titulos
        if lidas > LIMITE_ABASTECIMENTOS:
            linhas.append({"linha": numero_dado, "erros": [
                f"A planilha passa de {LIMITE_ABASTECIMENTOS} linhas. Divida em partes."],
                "dados": {"veiculo_nome": rotulo}, "veiculo": None})
            break

        if _vazio(celula("LITROS")) and _vazio(celula("KM")):
            bruto_v = celula("VEICULO")
            sem_abastecimento.append(_chave_frota(bruto_v) if isinstance(bruto_v, (int, float)) else rotulo)
            continue

        veiculo, erro_veiculo = localizar(celula("VEICULO"))
        erros = [erro_veiculo] if erro_veiculo else []
        dados = {"veiculo_id": veiculo.id if veiculo else None,
                 "veiculo_nome": (veiculo.rotulo if veiculo else rotulo)}

        for titulo, campo, tipo_campo, _obrig in COLUNAS_ABASTECIMENTOS[1:]:
            valor = celula(_sem_acento(titulo))
            try:
                if tipo_campo == "data":
                    convertido = None if _vazio(valor) else _data_da_planilha(valor)
                else:
                    convertido = _converter(valor, tipo_campo, titulo)
            except (ValueError, TypeError, ErroNegocio):
                erros.append(f"'{titulo}' com valor inválido: {valor}")
                convertido = None
            if convertido in (None, ""):
                erros.append(f"'{titulo}' é obrigatório")
            dados[campo] = convertido

        if dados.get("litros") is not None and dados["litros"] <= 0:
            erros.append("'LITROS' deve ser maior que zero")
        if dados.get("km_atual") is not None and dados["km_atual"] < 0:
            erros.append("'KM' não pode ser negativo")

        linhas.append({"linha": numero_dado, "erros": erros, "dados": dados, "veiculo": veiculo})

    # ---- 2ª passada: confere com o histórico do sistema (1 consulta só) ----
    validas = [l for l in linhas if not l["erros"] and l["veiculo"]
               and l["dados"].get("data") and l["dados"].get("km_atual") is not None]
    historico, no_dia = defaultdict(list), {}
    if validas:
        ids = {l["veiculo"].id for l in validas}
        ate = max(l["dados"]["data"] for l in validas)
        for vid, data, km, litros in (db.session.query(
                Abastecimento.veiculo_id, Abastecimento.data,
                Abastecimento.km_atual, Abastecimento.litros)
                .filter(Abastecimento.veiculo_id.in_(ids), Abastecimento.data <= ate).all()):
            if data is None:
                continue
            historico[vid].append((data, km or 0))
            no_dia.setdefault((vid, data), ("sistema", km or 0, litros or 0))

    # Em ordem de data, para que uma planilha com vários dias também confira
    # cada dia contra o anterior.
    for l in sorted(validas, key=lambda x: (x["dados"]["data"], x["linha"])):
        d, v = l["dados"], l["veiculo"]
        data, km, chave_dia = d["data"], float(d["km_atual"]), (v.id, d["data"])

        if chave_dia in no_dia:
            origem, km_antes, litros_antes = no_dia[chave_dia]
            if origem == "planilha":
                l["erros"].append("registro repetido na própria planilha" if abs(km_antes - km) < 0.001
                                  else "este veículo aparece mais de uma vez nesta data na planilha")
            elif abs(km_antes - km) < 0.001:
                l["erros"].append("já existe no sistema para este veículo, data e km")
            else:
                l["erros"].append(
                    f"já existe abastecimento deste veículo em {data.strftime('%d/%m/%Y')} no sistema "
                    f"(km {_milhar(km_antes)}, {litros_antes:g} L) — corrija ou exclua o anterior")
            continue

        anteriores = [(k, dt) for dt, k in historico[v.id] if dt <= data]
        if anteriores:
            maior_km, data_do_km = max(anteriores)
            if km < maior_km:
                l["erros"].append(
                    f"KM {_milhar(km)} é menor que o último lançado para este veículo "
                    f"({_milhar(maior_km)} em {data_do_km.strftime('%d/%m/%Y')})")
                continue
            if km - maior_km > LIMITE_SALTO_KM:
                l["erros"].append(
                    f"KM {_milhar(km)} está {_milhar(km - maior_km)} km acima do último lançado "
                    f"({_milhar(maior_km)} em {data_do_km.strftime('%d/%m/%Y')}) — confira o KM digitado")
                continue

        historico[v.id].append((data, km))
        no_dia[chave_dia] = ("planilha", km, d["litros"])

    prontas, problemas = [], []
    for l in linhas:
        d = dict(l["dados"])
        if isinstance(d.get("data"), date):
            d["data"] = d["data"].isoformat()      # ISO para a prévia JSON
        if l["erros"]:
            problemas.append({"linha": l["linha"], "erro": "; ".join(l["erros"]), "dados": d})
        else:
            prontas.append({"linha": l["linha"], "dados": d})

    return {
        "tipo": "abastecimentos",
        "titulo": "Abastecimentos",
        "colunas": ["VEÍCULO", "DATA", "LITROS", "KM", "KM PERC", "KM/L"],
        "campos": ["veiculo_nome", "data", "litros", "km_atual"],
        "prontas": prontas,
        "problemas": problemas,
        "sem_abastecimento": sem_abastecimento,
        "resumo": {
            "aba": ws.title,
            "datas": sorted({p["dados"]["data"] for p in prontas}),
            "litros": round(sum(p["dados"]["litros"] for p in prontas), 1),
            "veiculos": len({p["dados"]["veiculo_id"] for p in prontas}),
        },
        "total": len(prontas) + len(problemas),
    }


def gravar_abastecimentos(linhas):
    if not linhas:
        raise ErroNegocio("Não há abastecimentos válidos para importar.")

    criados = []
    veiculos_afetados = set()
    try:
        # Primeiro grava os lançamentos. Depois recalcula TODO o histórico dos
        # veículos afetados em ordem de km, permitindo importar planilhas
        # históricas sem a regra de "km maior que o último".
        for item in linhas:
            d = dict(item.get("dados") or item)
            veiculo_id = int(d["veiculo_id"])
            obj = Abastecimento(
                veiculo_id=veiculo_id,
                data=ler_data(d.get("data"), "DATA"),
                litros=float(d.get("litros") or 0),
                km_atual=float(d.get("km_atual") or 0),
                combustivel="Diesel S10",
                valor_litro=0,
                valor_total=0,
                tanque_cheio=True,
            )
            db.session.add(obj)
            criados.append(obj)
            veiculos_afetados.add(veiculo_id)

        db.session.flush()

        from services.calculos import recalcular_abastecimento, atualizar_consumo_diario_frota
        for veiculo_id in veiculos_afetados:
            historico = (Abastecimento.query
                         .filter_by(veiculo_id=veiculo_id)
                         .order_by(Abastecimento.km_atual.asc(), Abastecimento.id.asc())
                         .all())
            for obj in historico:
                recalcular_abastecimento(obj)

        atualizar_consumo_diario_frota()
        db.session.flush()
        return len(criados)
    except (ValueError, TypeError, ErroNegocio):
        db.session.rollback()
        raise
    except Exception as e:
        db.session.rollback()
        raise ErroNegocio(f"Não foi possível importar os abastecimentos: {e.__class__.__name__}.")


# Compatibilidade com versões do routes/api.py que ainda usam o nome antigo.
def _normalizar_prefixo_importacao(valor):
    """Transforma 2, 02, 2.0 ou '02 · JBF5F67' em '02'."""
    if valor is None:
        return ""
    texto = str(valor).strip().upper()
    if "·" in texto:
        texto = texto.split("·", 1)[0].strip()
    # Excel pode entregar 2 como 2.0.
    try:
        numero = float(texto.replace(",", "."))
        if numero.is_integer():
            return str(int(numero)).zfill(2)
    except (ValueError, TypeError):
        pass
    digitos = "".join(ch for ch in texto if ch.isdigit())
    if digitos and len(digitos) <= 2 and digitos == texto.replace(" ", ""):
        return digitos.zfill(2)
    return texto


def _mapa_veiculos_por_prefixo():
    veiculos = Veiculo.query.filter(Veiculo.ativo.is_(True)).all()
    return {_normalizar_prefixo_importacao(v.prefixo): v for v in veiculos if v.prefixo}


def importar_abastecimentos_workbook(workbook):
    """Importa diretamente um workbook na API legada /abastecimentos/importar-excel.

    A coluna VEÍCULO da planilha representa o prefixo da frota: 2 -> prefixo 02,
    58 -> prefixo 58 etc. DATA aceita datas nativas do Excel. KM PERC e KM/L são
    calculados pelo SGMF e não precisam estar preenchidos para a importação.
    """
    if hasattr(workbook, "active"):
        wb = workbook
        deve_fechar = False
    else:
        wb = load_workbook(workbook, data_only=True, read_only=True)
        deve_fechar = True

    try:
        nomes = {str(ws.title).strip().upper(): ws for ws in wb.worksheets}
        ws = nomes.get("LANÇAMENTO") or nomes.get("LANCAMENTO") or wb.active
        linhas = list(ws.iter_rows(values_only=True))
        if not linhas:
            raise ErroNegocio("A planilha de abastecimentos está vazia.")

        cab = [str(c).replace("*", "").strip().upper() if c is not None else "" for c in linhas[0]]
        def idx(nome):
            return cab.index(nome) if nome in cab else None

        i_veiculo, i_data, i_litros, i_km = idx("VEÍCULO"), idx("DATA"), idx("LITROS"), idx("KM")
        faltando = [nome for nome, pos in (("VEÍCULO", i_veiculo), ("DATA", i_data),
                                             ("LITROS", i_litros), ("KM", i_km)) if pos is None]
        if faltando:
            raise ErroNegocio("A planilha não tem as colunas: " + ", ".join(faltando) + ".")

        por_prefixo = _mapa_veiculos_por_prefixo()
        importados = duplicados = ignorados = 0
        erros = []

        for numero, row in enumerate(linhas[1:], start=2):
            valores = list(row)
            if not any(v is not None and str(v).strip() for v in valores):
                continue

            bruto_veiculo = valores[i_veiculo] if i_veiculo < len(valores) else None
            texto_veiculo = str(bruto_veiculo).strip().upper() if bruto_veiculo is not None else ""
            # A linha TOTAL da planilha não é lançamento.
            if texto_veiculo == "TOTAL":
                ignorados += 1
                continue

            prefixo = _normalizar_prefixo_importacao(bruto_veiculo)
            veiculo = por_prefixo.get(prefixo)
            if not veiculo:
                erros.append(f"linha {numero}: veículo/prefixo '{texto_veiculo}' não encontrado")
                continue

            try:
                data_val = _converter(valores[i_data] if i_data < len(valores) else None, "data", "DATA")
                litros = _converter(valores[i_litros] if i_litros < len(valores) else None, "numero", "LITROS")
                km = _converter(valores[i_km] if i_km < len(valores) else None, "numero", "KM")
            except ValueError as exc:
                erros.append(f"linha {numero}: {exc}")
                continue

            if not data_val or litros is None or km is None:
                erros.append(f"linha {numero}: DATA, LITROS e KM são obrigatórios")
                continue
            if float(litros) <= 0 or float(km) < 0:
                erros.append(f"linha {numero}: LITROS deve ser maior que zero e KM não pode ser negativo")
                continue

            existente = Abastecimento.query.filter_by(veiculo_id=veiculo.id, data=data_val, km_atual=float(km)).first()
            if existente:
                duplicados += 1
                continue

            obj = Abastecimento(
                veiculo_id=veiculo.id, data=data_val, litros=float(litros), km_atual=float(km),
                combustivel=veiculo.combustivel or "Diesel S10", valor_litro=0, valor_total=0, tanque_cheio=True
            )
            db.session.add(obj)
            db.session.flush()
            importados += 1

        if erros:
            # Não bloqueia linhas válidas, mas devolve os problemas para a interface.
            # Eles são resumidos no retorno e as linhas válidas continuam importadas.
            pass

        if importados:
            afetados = {obj.veiculo_id for obj in Abastecimento.query.order_by(Abastecimento.id.desc()).limit(importados).all()}
            from services.calculos import recalcular_abastecimento
            for vid in afetados:
                historico = (Abastecimento.query.filter_by(veiculo_id=vid)
                             .order_by(Abastecimento.km_atual.asc(), Abastecimento.id.asc()).all())
                for obj in historico:
                    recalcular_abastecimento(obj)
            db.session.flush()

        resumo = {"importados": importados, "duplicados": duplicados, "ignorados": ignorados, "erros": erros}
        return resumo
    finally:
        if deve_fechar:
            wb.close()

