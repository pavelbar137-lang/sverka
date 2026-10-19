import unittest
from decimal import Decimal
from pathlib import Path

from sverka import OshibkaVygruzki, Para, chislo, prochitat, sverit
from sverka.__main__ import main

PRIMERY = Path(__file__).resolve().parent.parent / "primery"


class Chisla(unittest.TestCase):
    def test_formaty_1s_i_excel(self):
        self.assertEqual(chislo("1 234,50"), Decimal("1234.50"))
        self.assertEqual(chislo("1 234,5"), Decimal("1234.5"))
        self.assertEqual(chislo("18.5"), Decimal("18.5"))
        self.assertEqual(chislo(""), Decimal(0))

    def test_ne_chislo(self):
        with self.assertRaises(OshibkaVygruzki):
            chislo("пятьсот")


class Chtenie(unittest.TestCase):
    def test_cp1251_s_tochkoy_s_zapyatoy(self):
        rows = prochitat(PRIMERY / "rascenki" / "otgruzki.csv")
        self.assertEqual(rows[0]["Перевозчик"], "ТрансВолга")
        self.assertEqual(len(rows), 7)

    def test_utf8_s_bom(self):
        rows = prochitat(PRIMERY / "ostatki" / "moysklad.csv")
        self.assertIn("Код", rows[0])


class Rascenki(unittest.TestCase):
    def setUp(self):
        self.itog = sverit(
            prochitat(PRIMERY / "rascenki" / "otgruzki.csv"),
            prochitat(PRIMERY / "rascenki" / "prais.csv"),
            [Para.iz_stroki("Перевозчик"), Para.iz_stroki("Маршрут=Направление")],
            [Para.iz_stroki("Расценка=Цена за тонну")],
            spravochnik=True,
            kolichestvo="Тоннаж",
        )

    def test_nevernye_rascenki(self):
        nomera = [r.stroka["Номер"] for r in self.itog.rashozhdeniya]
        self.assertEqual(nomera, ["ОТ-1185", "ОТ-1188"])

    def test_dengi(self):
        # (680 - 610) * 19,8 + (560 - 520) * 17,2
        self.assertEqual(self.itog.dengi, Decimal("2074.0"))

    def test_marshrut_bez_praisa(self):
        self.assertEqual([r["Номер"] for r in self.itog.net_sprava], ["ОТ-1187"])

    def test_spravochnik_ne_trebuet_vseh_strok(self):
        # «Гранит-Авто, Тольятти - Самара» в прайсе есть, отгрузок по нему не было
        self.assertEqual(self.itog.net_sleva, [])


class Ostatki(unittest.TestCase):
    def setUp(self):
        self.itog = sverit(
            prochitat(PRIMERY / "ostatki" / "crm.csv"),
            prochitat(PRIMERY / "ostatki" / "moysklad.csv"),
            [Para.iz_stroki("Артикул=Код")],
            [Para.iz_stroki("Остаток=Доступно")],
        )

    def test_rashozhdeniya(self):
        self.assertEqual([r.kluch[0] for r in self.itog.rashozhdeniya], ["к-1002", "с-3001"])

    def test_s_dvuh_storon(self):
        self.assertEqual([r["Артикул"] for r in self.itog.net_sprava], ["Ч-2002"])
        self.assertEqual([r["Код"] for r in self.itog.net_sleva], ["С-3002"])

    def test_dopusk(self):
        itog = sverit(
            [{"a": "x", "n": "100"}],
            [{"a": "x", "n": "99,5"}],
            [Para.iz_stroki("a")],
            [Para.iz_stroki("n")],
            dopusk=Decimal("1"),
        )
        self.assertTrue(itog.chisto)


class Proverki(unittest.TestCase):
    def test_dubl_v_spravochnike(self):
        itog = sverit(
            [{"k": "A", "v": "1"}],
            [{"k": "A", "v": "1"}, {"k": "a ", "v": "2"}],
            [Para.iz_stroki("k")],
            [Para.iz_stroki("v")],
            spravochnik=True,
        )
        self.assertEqual(itog.dubli_sprava, [("a",)])

    def test_net_kolonki(self):
        with self.assertRaises(OshibkaVygruzki) as e:
            sverit([{"k": "A"}], [{"k": "A"}], [Para.iz_stroki("k")], [Para.iz_stroki("v")])
        self.assertIn("v", str(e.exception))


class Komandnaya(unittest.TestCase):
    def test_kod_vyhoda(self):
        base = ["--kluch", "Артикул=Код", "--sravnit", "Остаток=Доступно"]
        crm = str(PRIMERY / "ostatki" / "crm.csv")
        sklad = str(PRIMERY / "ostatki" / "moysklad.csv")
        self.assertEqual(main([crm, sklad, *base]), 1)
        self.assertEqual(main([crm, crm, "--kluch", "Артикул", "--sravnit", "Остаток"]), 0)
        self.assertEqual(main([crm, sklad, "--kluch", "Нет", "--sravnit", "Остаток=Доступно"]), 2)


if __name__ == "__main__":
    unittest.main()
