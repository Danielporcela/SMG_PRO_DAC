from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class GruposConsumoEstaticoTest(unittest.TestCase):
    def test_modelos_guardam_grupo_de_consumo_e_ocultacao_legada(self):
        texto = (ROOT / "models.py").read_text(encoding="utf-8")
        self.assertIn("class GrupoConsumo", texto)
        self.assertIn('__tablename__ = "grupos_consumo"', texto)
        self.assertIn("grupo_consumo_id = db.Column", texto)
        self.assertIn("grupo_consumo_legado = db.Column", texto)
        self.assertIn('"grupo_consumo_nome"', texto)

    def test_grupos_padrao_estao_definidos(self):
        texto = (ROOT / "services" / "grupos_consumo.py").read_text(encoding="utf-8")
        for nome in ("Limpeza", "Escritório", "CCO", "Capatazia Centro",
                     "Capatazia Sul", "Solda", "Borracheiro", "Oficina"):
            self.assertIn(nome, texto)

    def test_compatibilidade_cria_estrutura_sem_apagar_historico(self):
        texto = (ROOT / "services" / "compatibilidade_banco.py").read_text(encoding="utf-8")
        self.assertIn("def garantir_grupos_consumo", texto)
        self.assertIn('"grupo_consumo_id": "INTEGER"', texto)
        self.assertIn('"grupo_consumo_legado": "BOOLEAN DEFAULT FALSE"', texto)
        self.assertNotIn("DELETE FROM veiculos", texto)
        self.assertNotIn("DROP TABLE", texto)

    def test_app_registra_modulo_grupos_consumo(self):
        texto = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("bp_grupos_consumo", texto)
        self.assertIn("garantir_grupos_consumo", texto)
        self.assertIn("garantir_grupos_consumo()", texto)

    def test_menu_lateral_e_pagina_estao_presentes(self):
        base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
        pagina = (ROOT / "templates" / "grupos_consumo.html").read_text(encoding="utf-8")
        self.assertIn("Grupos de consumo", base)
        self.assertIn("Retirada por grupo", pagina)
        self.assertIn("grupoConsumo", pagina)
        self.assertIn("pecaConsumo", pagina)
        self.assertIn("quantidadeConsumo", pagina)
        self.assertIn("/api/grupos-consumo/retiradas", pagina)

    def test_api_de_retirada_usa_movimentacao_central_e_grupo(self):
        texto = (ROOT / "routes" / "grupos_consumo.py").read_text(encoding="utf-8")
        self.assertIn("movimentar_estoque", texto)
        self.assertIn("grupo_consumo_id=grupo.id", texto)
        self.assertIn("Estoque insuficiente", (ROOT / "services" / "calculos.py").read_text(encoding="utf-8"))

    def test_veiculos_legados_sao_ocultados_da_frota_sem_exclusao(self):
        api = (ROOT / "routes" / "api.py").read_text(encoding="utf-8")
        servico = (ROOT / "services" / "grupos_consumo.py").read_text(encoding="utf-8")
        self.assertIn("grupo_consumo_legado", api)
        self.assertIn("marcar_veiculos_grupo_consumo_legado", servico)
        self.assertNotIn("db.session.delete(veiculo)", servico)

    def test_setores_legados_nao_entram_em_alertas_da_frota(self):
        texto = (ROOT / "services" / "alertas.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(texto.count("Veiculo.grupo_consumo_legado.isnot(True)"), 2)

    def test_grupos_padrao_nao_podem_ser_renomeados_e_perder_historico(self):
        rota = (ROOT / "routes" / "grupos_consumo.py").read_text(encoding="utf-8")
        servico = (ROOT / "services" / "grupos_consumo.py").read_text(encoding="utf-8")
        self.assertIn("eh_grupo_padrao", servico)
        self.assertIn("não pode ser renomeado", rota)

    def test_meta_e_backup_preservam_grupo_de_consumo(self):
        api = (ROOT / "routes" / "api.py").read_text(encoding="utf-8")
        modelo = (ROOT / "models.py").read_text(encoding="utf-8")
        restauracao = (ROOT / "services" / "restauracao.py").read_text(encoding="utf-8")
        relatorios = (ROOT / "routes" / "relatorios.py").read_text(encoding="utf-8")
        self.assertIn('"grupo_consumo_id": "int"', api)
        self.assertIn("grupo_consumo_id", modelo)
        self.assertIn("GrupoConsumo", restauracao)
        self.assertIn('"grupos_consumo"', relatorios)

    def test_grupos_legados_nao_entram_em_alertas_nem_consumo_da_frota(self):
        alertas = (ROOT / "services" / "alertas.py").read_text(encoding="utf-8")
        indicadores = (ROOT / "services" / "indicadores.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(alertas.count("Veiculo.grupo_consumo_legado.isnot(True)"), 2)
        self.assertIn("MovimentoEstoque.grupo_consumo_id.is_(None)", indicadores)

    def test_importacao_nao_recria_setores_como_veiculos(self):
        texto = (ROOT / "services" / "importacao.py").read_text(encoding="utf-8")
        self.assertIn("nome_grupo_consumo_legado", texto)
        self.assertIn("Grupos de consumo", texto)

    def test_instalacao_nova_semeia_grupos_apos_criar_tabelas(self):
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        preparar = app.index("preparar_banco()")
        segunda = app.index("garantir_grupos_consumo()", preparar)
        self.assertGreater(segunda, preparar)

    def test_sessoes_antigas_usam_padrao_do_perfil_para_nova_tela(self):
        crud = (ROOT / "services" / "crud.py").read_text(encoding="utf-8")
        paginas = (ROOT / "routes" / "paginas.py").read_text(encoding="utf-8")
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("PADRAO_POR_PERFIL", crud)
        self.assertIn("PADRAO_POR_PERFIL", paginas)
        self.assertIn("PADRAO_POR_PERFIL", app)

    def test_metas_antigas_de_setores_sao_tratadas_como_grupo_de_custo(self):
        api = (ROOT / "routes" / "api.py").read_text(encoding="utf-8")
        grupos = (ROOT / "services" / "grupos_consumo.py").read_text(encoding="utf-8")
        indicadores = (ROOT / "services" / "indicadores.py").read_text(encoding="utf-8")
        self.assertIn("def _serializar_orcamento", api)
        self.assertIn("grupo_para_veiculo_legado", api)
        self.assertIn("metas_legadas", grupos)
        self.assertIn("~Orcamento.veiculo.has(Veiculo.grupo_consumo_legado.is_(True))", indicadores)


if __name__ == "__main__":
    unittest.main()
