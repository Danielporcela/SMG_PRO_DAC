import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AuditoriaEstoqueOSStaticTests(unittest.TestCase):
    def test_servico_e_rotas_de_regularizacao_existem(self):
        servico = ROOT / "services" / "auditoria_estoque.py"
        rota = ROOT / "routes" / "auditoria_estoque.py"
        self.assertTrue(servico.exists(), "Falta o serviço de auditoria de estoque")
        self.assertTrue(rota.exists(), "Falta a rota de auditoria de estoque")
        fonte = rota.read_text(encoding="utf-8")
        self.assertIn("/api/auditoria_estoque_os", fonte)
        self.assertIn("regularizar", fonte)

    def test_aba_foi_retirada_do_menu(self):
        pagina = (ROOT / "routes" / "paginas.py").read_text(encoding="utf-8")
        menu = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
        self.assertIn("auditoria_estoque_os", pagina)
        self.assertNotIn("auditoria_estoque_os", menu)

    def test_painel_expoe_contador_de_pendencias(self):
        indicadores = (ROOT / "services" / "indicadores.py").read_text(encoding="utf-8")
        self.assertIn('"os_estoque_pendentes"', indicadores)


if __name__ == "__main__":
    unittest.main()
