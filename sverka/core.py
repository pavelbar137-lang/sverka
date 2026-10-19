"""Сверка двух выгрузок: факт против справочника или две системы между собой.

Выгрузки из 1С, МойСклада и Excel приходят в разных кодировках, с точкой с
запятой вместо запятой и числами вида «1 234,50». Всё это разбирается здесь,
чтобы сравнение шло по значениям, а не по тому, как их напечатала программа.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path


class OshibkaVygruzki(Exception):
    """Выгрузку нельзя сверять: нет колонки, пустой файл, кривое число."""


def prochitat(path: str | Path) -> list[dict[str, str]]:
    """Читает CSV в любой из кодировок, которые реально отдают 1С и Excel."""
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp1251"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise OshibkaVygruzki(f"{path}: не UTF-8 и не Windows-1251")
    if not text.strip():
        raise OshibkaVygruzki(f"{path}: файл пустой")
    pervaya = text.splitlines()[0]
    razdelitel = max(";,\t", key=pervaya.count)
    reader = csv.DictReader(io.StringIO(text), delimiter=razdelitel)
    rows = []
    for row in reader:
        rows.append({(k or "").strip(): (v or "").strip() for k, v in row.items()})
    return rows


def chislo(value: str) -> Decimal:
    """«1 234,50», «1234.5», «-3» -> Decimal. Пустое значение считается нулём."""
    s = value.replace(" ", "").replace(" ", "").replace(",", ".")
    if s in ("", "-"):
        return Decimal(0)
    try:
        return Decimal(s)
    except InvalidOperation:
        raise OshibkaVygruzki(f"не число: {value!r}") from None


@dataclass
class Para:
    """Колонка слева и соответствующая ей колонка справа."""

    sleva: str
    sprava: str

    @classmethod
    def iz_stroki(cls, s: str) -> "Para":
        if "=" in s:
            a, b = s.split("=", 1)
            return cls(a.strip(), b.strip())
        return cls(s.strip(), s.strip())


@dataclass
class Rashozhdenie:
    kluch: tuple[str, ...]
    kolonka: str
    sleva: Decimal
    sprava: Decimal
    stroka: dict[str, str]
    dengi: Decimal | None = None


@dataclass
class Itog:
    vsego_sleva: int = 0
    vsego_sprava: int = 0
    net_sprava: list[dict[str, str]] = field(default_factory=list)
    net_sleva: list[dict[str, str]] = field(default_factory=list)
    dubli_sleva: list[tuple[str, ...]] = field(default_factory=list)
    dubli_sprava: list[tuple[str, ...]] = field(default_factory=list)
    rashozhdeniya: list[Rashozhdenie] = field(default_factory=list)
    kluch_sleva: list[str] = field(default_factory=list)
    kluch_sprava: list[str] = field(default_factory=list)

    @property
    def chisto(self) -> bool:
        return not (
            self.net_sprava
            or self.net_sleva
            or self.dubli_sleva
            or self.dubli_sprava
            or self.rashozhdeniya
        )

    @property
    def dengi(self) -> Decimal:
        return sum((r.dengi for r in self.rashozhdeniya if r.dengi), Decimal(0))


def _kluch(row: dict[str, str], kolonki: list[str]) -> tuple[str, ...]:
    return tuple(" ".join(row[k].split()).casefold() for k in kolonki)


def _proverit_kolonki(rows: list[dict[str, str]], nuzhny: list[str], gde: str) -> None:
    if not rows:
        raise OshibkaVygruzki(f"{gde}: нет ни одной строки")
    est = set(rows[0])
    net = [k for k in nuzhny if k not in est]
    if net:
        raise OshibkaVygruzki(
            f"{gde}: нет колонок {', '.join(net)}; есть: {', '.join(sorted(est))}"
        )


def sverit(
    sleva: list[dict[str, str]],
    sprava: list[dict[str, str]],
    kluch: list[Para],
    sravnit: list[Para],
    dopusk: Decimal = Decimal(0),
    spravochnik: bool = False,
    kolichestvo: str | None = None,
) -> Itog:
    """Сверяет строки слева со строками справа по ключу.

    spravochnik=True: справа справочник (прайс, нормы), слева факты (отгрузки,
    наряды). Тогда одинаковые ключи слева нормальны, а строки справочника,
    которые никто не использовал, расхождением не считаются.

    kolichestvo: колонка слева, на которую умножается разница, чтобы видеть
    ошибку в рублях (тонны, часы, штуки).
    """
    kl_l = [p.sleva for p in kluch]
    kl_r = [p.sprava for p in kluch]
    _proverit_kolonki(sleva, kl_l + [p.sleva for p in sravnit] + ([kolichestvo] if kolichestvo else []), "слева")
    _proverit_kolonki(sprava, kl_r + [p.sprava for p in sravnit], "справа")

    itog = Itog(vsego_sleva=len(sleva), vsego_sprava=len(sprava), kluch_sleva=kl_l, kluch_sprava=kl_r)

    index_r: dict[tuple[str, ...], dict[str, str]] = {}
    for row in sprava:
        k = _kluch(row, kl_r)
        if k in index_r:
            itog.dubli_sprava.append(k)
        index_r[k] = row

    vstrecheny: set[tuple[str, ...]] = set()
    vidennye_l: set[tuple[str, ...]] = set()
    for row in sleva:
        k = _kluch(row, kl_l)
        if not spravochnik:
            if k in vidennye_l:
                itog.dubli_sleva.append(k)
            vidennye_l.add(k)
        para = index_r.get(k)
        if para is None:
            itog.net_sprava.append(row)
            continue
        vstrecheny.add(k)
        for p in sravnit:
            a, b = chislo(row[p.sleva]), chislo(para[p.sprava])
            if abs(a - b) > dopusk:
                dengi = (a - b) * chislo(row[kolichestvo]) if kolichestvo else None
                itog.rashozhdeniya.append(Rashozhdenie(k, p.sleva, a, b, row, dengi))

    if not spravochnik:
        itog.net_sleva = [r for r in sprava if _kluch(r, kl_r) not in vstrecheny]
    return itog
