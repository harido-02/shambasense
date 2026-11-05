"""English and Kiswahili strings for advice text, the web app and USSD.

Kiswahili wording should be checked by a fluent speaker before release.
"""

from __future__ import annotations

TEXT = {
    "en": {
        "label_high": "Highly recommended",
        "label_rec": "Recommended",
        "label_marginal": "Marginal (higher risk)",
        "season_long_rains": "Long rains",
        "season_short_rains": "Short rains",
        "plant_advice": "Plant once about 20 mm of rain has fallen within 3 days. In most years that happens between {early} and {late} (typically around {median}).",
        "no_onset": "In {pct}% of past seasons the rains never became reliable here; keep seed until the rains settle.",
        "price": "Recent wholesale price: KES {price:.0f}/kg in {where}.",
        "risk": "Chance of losing money this season: about {pct}%.",
        "effect_up": "{label} favours this crop here ({v} t/ha against typical conditions).",
        "effect_down": "{label} holds this crop back here ({v} t/ha against typical conditions).",
        "no_model": "No local yield history for this crop, so it is ranked on suitability only.",
        "out_of_range": "Conditions here are unlike the data the model learned from; treat this estimate with caution.",
        "synthetic": "Demo mode: the model was trained on SYNTHETIC test data. Do not use this advice for real planting.",
        "outside_area": "This point is {km:.0f} km from the nearest study county ({county}); advice is less reliable this far out.",
    },
    "sw": {
        "label_high": "Inapendekezwa sana",
        "label_rec": "Inapendekezwa",
        "label_marginal": "Hatari zaidi",
        "season_long_rains": "Mvua ndefu",
        "season_short_rains": "Mvua fupi",
        "plant_advice": "Panda baada ya mvua ya takriban milimita 20 kunyesha ndani ya siku 3. Kwa miaka mingi hii hutokea kati ya {early} na {late} (kwa kawaida karibu {median}).",
        "no_onset": "Katika {pct}% ya misimu iliyopita mvua haikutulia hapa; hifadhi mbegu hadi mvua itulie.",
        "price": "Bei ya jumla ya hivi karibuni: KES {price:.0f}/kg katika {where}.",
        "risk": "Uwezekano wa kupata hasara msimu huu: takriban {pct}%.",
        "effect_up": "{label} inafaa zao hili hapa ({v} t/ha ukilinganisha na hali ya kawaida).",
        "effect_down": "{label} inapunguza mavuno ya zao hili hapa ({v} t/ha ukilinganisha na hali ya kawaida).",
        "no_model": "Hakuna takwimu za mavuno ya zao hili hapa, kwa hivyo limepangwa kwa ufaafu pekee.",
        "out_of_range": "Hali ya hapa ni tofauti na data ambayo mfumo ulijifunzia; tumia makadirio haya kwa tahadhari.",
        "synthetic": "Majaribio: mfumo umefunzwa kwa data BANDIA. Usitumie ushauri huu kupanda.",
        "outside_area": "Mahali hapa ni km {km:.0f} kutoka kaunti ya utafiti iliyo karibu ({county}); ushauri hauaminiki sana mbali hivi.",
    },
}

MONTHS = {
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "sw": ["Jan", "Feb", "Mac", "Apr", "Mei", "Jun", "Jul", "Ago", "Sep", "Okt", "Nov", "Des"],
}


def t(lang: str, key: str, **kwargs) -> str:
    table = TEXT.get(lang, TEXT["en"])
    return table.get(key, TEXT["en"][key]).format(**kwargs)


def day_month(d, lang: str = "en") -> str:
    return f"{d.day} {MONTHS.get(lang, MONTHS['en'])[d.month - 1]}"
