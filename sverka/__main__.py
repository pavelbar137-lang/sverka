"""Командная строка: python -m sverka <слева.csv> <справа.csv> --kluch ... --sravnit ...

Код выхода: 0 — расхождений нет, 1 — есть, 2 — выгрузку нельзя сверять.
Так проверку можно ставить в планировщик и реагировать на код, а не на текст.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.request
from decimal import Decimal

from .core import Itog, OshibkaVygruzki, Para, prochitat, sverit

PREDEL_TELEGRAM = 4000


def _rub(d: Decimal) -> str:
    return f"{d:,.2f}".replace(",", " ").replace(".", ",") + " ₽"


def _num(d: Decimal) -> str:
    s = f"{d.normalize():f}"
    return s.replace(".", ",")


def _opisanie(row: dict[str, str], pokazat: list[str]) -> str:
    return ", ".join(row[k] for k in pokazat if row.get(k)) or "строка"


def otchet(itog: Itog, pokazat: list[str], nazvanie: str, sleva: str, sprava: str) -> str:
    pokazat = pokazat or itog.kluch_sleva
    if itog.chisto:
        return f"{nazvanie}: расхождений нет ({itog.vsego_sleva} строк сверено с {sprava})."
    stroki = [f"{nazvanie}: найдено расхождений {len(itog.rashozhdeniya) + len(itog.net_sprava) + len(itog.net_sleva)}"]
    if itog.dengi:
        stroki.append(f"Разница в деньгах: {_rub(itog.dengi)}")
    for r in itog.rashozhdeniya:
        line = f"• {_opisanie(r.stroka, pokazat)}: {r.kolonka} {_num(r.sleva)}, в «{sprava}» {_num(r.sprava)}"
        if r.dengi:
            line += f" ({_rub(r.dengi)})"
        stroki.append(line)
    for row in itog.net_sprava:
        stroki.append(f"• {_opisanie(row, pokazat)}: нет в «{sprava}»")
    for row in itog.net_sleva:
        stroki.append(f"• {_opisanie(row, itog.kluch_sprava + [k for k in pokazat if k not in itog.kluch_sprava])}: есть в «{sprava}», нет в «{sleva}»")
    for k in itog.dubli_sprava:
        stroki.append(f"• в «{sprava}» ключ {' / '.join(k)} встречается дважды, сверка по нему ненадёжна")
    for k in itog.dubli_sleva:
        stroki.append(f"• в «{sleva}» ключ {' / '.join(k)} встречается дважды")

    text, ostalos = "", 0
    for i, line in enumerate(stroki):
        if len(text) + len(line) + 40 > PREDEL_TELEGRAM:
            ostalos = len(stroki) - i
            break
        text += line + "\n"
    if ostalos:
        text += f"…и ещё {ostalos} строк, полный список в CSV\n"
    return text.rstrip()


def v_csv(itog: Itog, path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["что", "ключ", "колонка", "слева", "справа", "деньги"])
        for r in itog.rashozhdeniya:
            w.writerow(["разница", " / ".join(r.kluch), r.kolonka, _num(r.sleva), _num(r.sprava), _num(r.dengi) if r.dengi else ""])
        for row in itog.net_sprava:
            w.writerow(["нет справа", json.dumps(row, ensure_ascii=False), "", "", "", ""])
        for row in itog.net_sleva:
            w.writerow(["нет слева", json.dumps(row, ensure_ascii=False), "", "", "", ""])
        for k in itog.dubli_sprava:
            w.writerow(["дубль справа", " / ".join(k), "", "", "", ""])
        for k in itog.dubli_sleva:
            w.writerow(["дубль слева", " / ".join(k), "", "", "", ""])


def v_telegram(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        raise OshibkaVygruzki("для --telegram нужны TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID")
    body = json.dumps({"chat_id": chat, "text": text}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        if not json.load(resp).get("ok"):
            raise OshibkaVygruzki("Telegram не принял сообщение")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sverka", description="Сверка двух выгрузок")
    ap.add_argument("sleva", help="факты: отгрузки, наряды, остатки в CRM")
    ap.add_argument("sprava", help="с чем сверяем: прайс, нормы, склад")
    ap.add_argument("--kluch", action="append", required=True, help="колонка ключа, «Имя» или «Слева=Справа»")
    ap.add_argument("--sravnit", action="append", required=True, help="числовая колонка для сравнения")
    ap.add_argument("--dopusk", default="0", help="допустимая разница, по умолчанию 0")
    ap.add_argument("--spravochnik", action="store_true", help="справа справочник: повторы слева нормальны")
    ap.add_argument("--kolichestvo", help="колонка слева, на которую умножить разницу (тонны, часы)")
    ap.add_argument("--pokazat", default="", help="колонки слева для текста отчёта, через запятую")
    ap.add_argument("--nazvanie", default="Сверка")
    ap.add_argument("--csv", help="полный список расхождений в файл")
    ap.add_argument("--telegram", action="store_true", help="отправить отчёт, если есть расхождения")
    a = ap.parse_args(argv)

    try:
        itog = sverit(
            prochitat(a.sleva),
            prochitat(a.sprava),
            [Para.iz_stroki(s) for s in a.kluch],
            [Para.iz_stroki(s) for s in a.sravnit],
            dopusk=Decimal(a.dopusk.replace(",", ".")),
            spravochnik=a.spravochnik,
            kolichestvo=a.kolichestvo,
        )
        pokazat = [s.strip() for s in a.pokazat.split(",") if s.strip()]
        text = otchet(itog, pokazat, a.nazvanie, os.path.basename(a.sleva), os.path.basename(a.sprava))
        print(text)
        if a.csv:
            v_csv(itog, a.csv)
        if a.telegram and not itog.chisto:
            v_telegram(text)
    except OshibkaVygruzki as e:
        print(f"сверка невозможна: {e}", file=sys.stderr)
        return 2
    return 0 if itog.chisto else 1


if __name__ == "__main__":
    sys.exit(main())
