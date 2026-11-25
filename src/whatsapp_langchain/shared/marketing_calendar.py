"""Calendário comercial (Brasil) para o agente de marketing.

Datas calculadas por código, não pelo modelo: LLMs erram datas móveis (Dia
das Mães, Black Friday, Carnaval) e não sabem "que dia é hoje". O agente
recebe a data exata e a antecedência recomendada para começar a campanha.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class CommercialDate:
    day: date
    name: str
    # Dias antes da data para começar a aquecer a campanha
    prep_days: int
    # Por que importa para uma loja de calçados femininos
    note: str


def easter(year: int) -> date:
    """Domingo de Páscoa (algoritmo de Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month, day = divmod(h + l_ - 7 * m + 114, 31)
    return date(year, month, day + 1)


def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """N-ésimo dia da semana do mês (weekday: 0=segunda ... 6=domingo)."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def black_friday(year: int) -> date:
    """Sexta-feira depois da 4ª quinta de novembro (Thanksgiving)."""
    return nth_weekday(year, 11, 3, 4) + timedelta(days=1)


def dates_for_year(year: int) -> list[CommercialDate]:
    carnival = easter(year) - timedelta(days=47)  # terça de Carnaval
    return [
        CommercialDate(
            date(year, 1, 10),
            "Liquidação de verão",
            7,
            "Janeiro é mês de liquidação: girar estoque da coleção primavera-verão.",
        ),
        CommercialDate(
            carnival,
            "Carnaval",
            14,
            "Sandálias confortáveis e douradas; também é época de viagem.",
        ),
        CommercialDate(
            date(year, 3, 8),
            "Dia Internacional da Mulher",
            7,
            "Público 100% feminino: conteúdo de autoestima e presente para si mesma.",
        ),
        CommercialDate(
            date(year, 3, 15),
            "Dia do Consumidor",
            7,
            "Data de ofertas no varejo; boa para ação na loja física.",
        ),
        CommercialDate(
            easter(year),
            "Páscoa",
            10,
            "Feriado prolongado: looks para encontros de família.",
        ),
        CommercialDate(
            nth_weekday(year, 5, 6, 2),
            "Dia das Mães",
            21,
            "Principal data do ano para calçado feminino: presente para mães e avós.",
        ),
        CommercialDate(
            date(year, 6, 12),
            "Dia dos Namorados",
            14,
            "Look para o jantar; presente que as clientes pedem para ganhar.",
        ),
        CommercialDate(
            date(year, 7, 10),
            "Liquidação de inverno",
            7,
            "Julho é mês de liquidação da coleção outono-inverno (botas, fechados).",
        ),
        CommercialDate(
            date(year, 9, 15),
            "Dia do Cliente",
            7,
            "Ação de relacionamento: agradecer clientes fiéis, chamar para a loja.",
        ),
        CommercialDate(
            date(year, 9, 22),
            "Início da primavera",
            10,
            "Lançamento da coleção primavera-verão: sandálias, cores claras.",
        ),
        CommercialDate(
            black_friday(year),
            "Black Friday",
            21,
            "Maior data de varejo do 2º semestre: lista de espera e aquecimento.",
        ),
        CommercialDate(
            date(year, 12, 12),
            "Aniversário de Belo Horizonte",
            5,
            "Data local: conteúdo de orgulho mineiro, valoriza a loja do Barro Preto.",
        ),
        CommercialDate(
            date(year, 12, 25),
            "Natal",
            30,
            "Presentes; vale-presente; horário especial da loja física.",
        ),
        CommercialDate(
            date(year, 12, 31),
            "Réveillon",
            14,
            "Sandálias douradas, prateadas e brancas para a virada.",
        ),
    ]


def upcoming_dates(today: date, horizon_days: int = 75) -> list[CommercialDate]:
    """Datas comerciais de hoje até `horizon_days` à frente, em ordem."""
    end = today + timedelta(days=horizon_days)
    found = [
        d
        for year in (today.year, today.year + 1)
        for d in dates_for_year(year)
        if today <= d.day <= end
    ]
    return sorted(found, key=lambda d: d.day)
