from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class HistoricoMovimentoUsuarioEstaticoTest(unittest.TestCase):
    def test_modelo_movimento_guarda_responsavel(self):
        texto = (ROOT / "models.py").read_text(encoding="utf-8")
        inicio = texto.index("class MovimentoEstoque")
        trecho = texto[inicio:inicio + 2200]
        self.assertIn('usuario_id = db.Column(db.Integer)', trecho)
        self.assertIn('usuario_nome = db.Column(db.String(120))', trecho)
        self.assertIn('"usuario_nome": self.usuario_nome', trecho)

    def test_servico_captura_usuario_da_sessao(self):
        texto = (ROOT / "services" / "calculos.py").read_text(encoding="utf-8")
        self.assertIn("has_request_context", texto)
        self.assertIn('session.get("usuario_id")', texto)
        self.assertIn('session.get("usuario_nome")', texto)
        self.assertIn("usuario_id=usuario_id", texto)
        self.assertIn("usuario_nome=usuario_nome", texto)

    def test_compatibilidade_adiciona_colunas_sem_apagar_dados(self):
        texto = (ROOT / "services" / "compatibilidade_banco.py").read_text(encoding="utf-8")
        self.assertIn("def garantir_usuario_movimentos_estoque", texto)
        self.assertIn('"usuario_id": "INTEGER"', texto)
        self.assertIn('"usuario_nome": "VARCHAR(120)"', texto)
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("garantir_usuario_movimentos_estoque", app)
        self.assertIn("garantir_usuario_movimentos_estoque()", app)

    def test_tela_tem_botao_e_modal_de_historico_por_peca(self):
        texto = (ROOT / "templates" / "estoque.html").read_text(encoding="utf-8")
        self.assertIn('data-historico="${v}"', texto)
        self.assertIn("campo: 'id', rotulo: 'Histórico'", texto)
        self.assertIn('id="modalHistoricoPeca"', texto)
        self.assertIn("/api/movimentos?peca_id=", texto)
        self.assertIn("Responsável", texto)
        self.assertIn("usuario_nome", texto)


if __name__ == "__main__":
    unittest.main()
