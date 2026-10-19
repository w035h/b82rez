"""Thuisbatterij Analyse: analyseert P1- en zonnepaneelhistorie en
simuleert de businesscase van een thuisbatterij. Ondersteunt meerdere
meters per richting (bijv. tarief 1 + tarief 2), automatisch gedetecteerd
via de config flow."""

from __future__ import annotations

import asyncio
import importlib
import logging
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.typing import ConfigType

from .const import (
    DOMAIN,
    CONF_ENTITIES_IMPORT,
    CONF_ENTITIES_EXPORT,
    CONF_ENTITIES_SOLAR,
    CONF_ENTITY_IMPORT,
    CONF_ENTITY_EXPORT,
    CONF_ENTITY_SOLAR,
    CONF_PRICE_IMPORT,
    CONF_PRICE_EXPORT,
    CONF_BATTERY_COST_KWH,
    CONF_BATTERY_COST_FIXED,
    CONF_BATTERY_EFFICIENCY,
    CONF_BATTERY_MAX_POWER_KW,
    CONF_MAX_CAPACITY,
    EVENT_UPDATED,
    ATTR_RESULT,
    DEFAULT_MAX_CAPACITY,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "button"]

SERVICE_START = "start"

MAX_HISTORY_DAYS = 365
MIN_ANALYSIS_DAYS = 14
MARGINAL_KWH_THRESHOLD = 25.0
# Aanbevolen maat: de grootste capaciteit waarvan de terugverdientijd
# maximaal 15% boven de best haalbare terugverdientijd ligt.
PAYBACK_TOLERANCE = 1.15


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [v for v in value if v]


def _get_groups(data: dict) -> dict[str, list[str]]:
    """Lees de entity-groepen uit de configuratie (nieuw: lijsten,
    oud: enkele entity per richting)."""
    groups = {
        "import": _as_list(data.get(CONF_ENTITIES_IMPORT))
        or _as_list(data.get(CONF_ENTITY_IMPORT)),
        "export": _as_list(data.get(CONF_ENTITIES_EXPORT))
        or _as_list(data.get(CONF_ENTITY_EXPORT)),
        "solar": _as_list(data.get(CONF_ENTITIES_SOLAR))
        or _as_list(data.get(CONF_ENTITY_SOLAR)),
    }
    return {k: v for k, v in groups.items() if v}


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration (nothing needed at yaml level)."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migreer oude config entries naar het nieuwe formaat.

    v1 (losse entity-velden) -> v2 (lijsten per richting, multi-tarief).
    Oude keys worden omgezet naar lijsten en daarna verwijderd, zodat
    de code overal met de nieuwe keys kan werken.
    """
    if entry.version > 2:
        # Nieuwer dan we ondersteunen: niet downgraden
        return False

    if entry.version == 1:
        old = {**entry.data, **(entry.options or {})}
        new = dict(old)

        legacy_map = {
            CONF_ENTITY_IMPORT: CONF_ENTITIES_IMPORT,
            CONF_ENTITY_EXPORT: CONF_ENTITIES_EXPORT,
            CONF_ENTITY_SOLAR: CONF_ENTITIES_SOLAR,
        }
        for old_key, new_key in legacy_map.items():
            if old_key in new and new_key not in new:
                value = new.pop(old_key)
                if value:
                    new[new_key] = [value] if isinstance(value, str) else list(value)
                else:
                    new[new_key] = []
            else:
                new.pop(old_key, None)

        new.setdefault(CONF_ENTITIES_IMPORT, [])
        new.setdefault(CONF_ENTITIES_EXPORT, [])
        new.setdefault(CONF_ENTITIES_SOLAR, [])

        hass.config_entries.async_update_entry(entry, data=new, version=2)
        _LOGGER.info(
            "Config entry gemigreerd van versie 1 naar 2 (multi-tarief formaat)"
        )

    return True


async def async_start_analysis(hass: HomeAssistant, entry_id: str | None = None) -> dict:
    """Draai de analyse voor één config entry (of de eerste beschikbare).

    Wordt zowel door de service batterij_analyse.start als door de
    Start-analyse-knop gebruikt.
    """
    if entry_id and entry_id in hass.data[DOMAIN]:
        target = hass.data[DOMAIN][entry_id]
    else:
        target = next(iter(hass.data[DOMAIN].values()), None)
    if target is None:
        raise HomeAssistantError("Thuisbatterij Analyse is nog niet geconfigureerd.")

    lock: asyncio.Lock = target["lock"]
    if lock.locked():
        raise HomeAssistantError(
            "Er draait al een Thuisbatterij Analyse voor deze configuratie; "
            "wacht tot die klaar is."
        )
    async with lock:
        result = await async_run_analysis(hass, target["entry"])
    target[ATTR_RESULT] = result
    _LOGGER.info(
        "Thuisbatterij Analyse klaar: aanbevolen %.1f kWh, netto besparing €%.0f/jaar",
        result["recommended_kwh"],
        result["yearly_savings"],
    )
    hass.bus.async_fire(EVENT_UPDATED, {"entry_id": target["entry"].entry_id})
    return result


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry."""
    hass.data[DOMAIN][entry.entry_id] = {
        "entry": entry,
        ATTR_RESULT: None,
        "lock": asyncio.Lock(),
    }
    # Voorkom blokkerende import in de event loop: laad het platform
    # vooraf in een executor-thread (aanbevolen door HA-richtlijnen).
    for platform in PLATFORMS:
        await hass.async_add_executor_job(
            importlib.import_module,
            f"{__package__}.{platform}",
        )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def async_handle_start(call: ServiceCall) -> None:
        """Run the analysis for the (optionally given) config entry."""
        await async_start_analysis(hass, call.data.get("entry_id"))

    hass.services.async_register(DOMAIN, SERVICE_START, async_handle_start)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_START)
    return unload_ok


# ---------------------------------------------------------------------------
# Data ophalen
# ---------------------------------------------------------------------------


def _resolve_statistic_ids(hass: HomeAssistant, entity_ids: list[str]) -> tuple[dict[str, str], list[str]]:
    """Los entity-id's op naar recorder-statistic-id's.

    Home Assistant kan statistieken opslaan onder een afwijkende ID
    (bijv. 'sensor.xxx_2' na een meterreset). We zoeken daarom eerst op
    de exacte ID, daarna op de prefix (sensor.xxx_2, sensor.xxx_3, ...).

    Retourneert: (entity_id -> statistic_id, niet-gevonden entity's)
    """
    from homeassistant.components.recorder.statistics import list_statistic_ids

    wanted = [e for e in entity_ids if e]
    if not wanted:
        return {}, []

    all_stats = list_statistic_ids(hass) or []

    # Normaliseer naar een verzameling van statistic-id's
    known_ids = {
        item["statistic_id"] if isinstance(item, dict) else item
        for item in all_stats
    }

    resolved: dict[str, str] = {}
    missing: list[str] = []
    for eid in wanted:
        if eid in known_ids:
            resolved[eid] = eid
            continue
        candidates = sorted(k for k in known_ids if k.startswith(f"{eid}_"))
        if candidates:
            resolved[eid] = candidates[-1]
        else:
            missing.append(eid)
    return resolved, missing


def _fetch_hourly_kwh(hass: HomeAssistant, groups: dict[str, list[str]]):
    """Haal uurlijkse kWh uit de recorder long-term statistics.

    De statistics-tabel bevat CUMULATIEVE meterstanden (sum) per uur.
    Het verbruik per uur is het verschil tussen opeenvolgende standen.
    Binnen een groep (bijv. tarief 1 + tarief 2) worden de uurverschillen
    van alle entity's bij elkaar opgeteld.

    Retourneert: (lijst met per uur (ts, import, export, solar),
    tijdstip eerste uur, tijdstip laatste uur, kwaliteitsdict)
    """
    from datetime import datetime, timedelta, timezone

    from homeassistant.components.recorder import get_instance
    from homeassistant.components.recorder.db_schema import Statistics, StatisticsMeta
    from sqlalchemy import func, select

    # 1) Alle entity-id's van alle groepen verzamelen en oplossen
    all_ents = sorted({e for ents in groups.values() for e in ents})
    resolved, missing_ents = _resolve_statistic_ids(hass, all_ents)
    _LOGGER.debug(
        "Statistic-id resolutie: %s (niet gevonden: %s)", resolved, missing_ents
    )
    if not resolved:
        return [], None, None, {
            "warnings": [],
            "missing_entities": missing_ents,
            "error": (
                "Geen statistieken gevonden voor: " + ", ".join(missing_ents)
                + ". Open Developer Tools -> Statistics om te controleren of deze "
                "entity's daar voorkomen. Alleen kWh-totaaltellers "
                "(state_class: total_increasing of total) bouwen historie op."
            ),
        }

    ids = list(resolved.values())
    available_ids: list[str] = []

    instance = get_instance(hass)
    session = instance.get_session()
    try:
        meta_rows = session.execute(
            select(StatisticsMeta.id, StatisticsMeta.statistic_id).where(
                StatisticsMeta.statistic_id.in_(ids)
            )
        ).all()
        id_to_name = {row[0]: row[1] for row in meta_rows}
        _LOGGER.debug(
            "Statistics-meta gevonden voor %d van %d statistic-id's",
            len(id_to_name), len(ids),
        )
        if not id_to_name:
            return [], None, None, {
                "warnings": [],
                "missing_entities": missing_ents,
                "error": "Geen statistics-meta gevonden voor de gekozen entity's.",
            }
        stat_rows = session.execute(
            select(
                Statistics.metadata_id,
                Statistics.start,
                Statistics.sum,
            ).where(Statistics.metadata_id.in_(id_to_name))
            .order_by(Statistics.start)
        ).all()
        _LOGGER.debug(
            "%d statistics-rijen opgehaald voor %d meters",
            len(stat_rows), len(id_to_name),
        )
        if not stat_rows:
            # Zelf-diagnose: welke statistic-id's hebben wél uurstatistieken?
            cutoff_dt = datetime.now(timezone.utc) - timedelta(days=30)
            avail_rows = session.execute(
                select(StatisticsMeta.statistic_id)
                .join(Statistics, Statistics.metadata_id == StatisticsMeta.id)
                .where(StatisticsMeta.has_sum.is_(True))
                .where(Statistics.start > cutoff_dt)
                .group_by(StatisticsMeta.statistic_id)
                .order_by(func.count(Statistics.id).desc())
                .limit(20)
            ).all()
            available_ids = [row[0] for row in avail_rows]
            _LOGGER.debug(
                "Geen statistics-rijen voor %s; statistic-id's met data (laatste 30 dagen): %s",
                ids, available_ids,
            )
    finally:
        session.close()

    # 2) Cumulatieve standen per statistic-id, op tijdstip
    raw: dict[str, dict[float, float]] = {name: {} for name in ids}
    for meta_id, start_dt, sum_val in stat_rows:
        name = id_to_name.get(meta_id)
        if name is None or sum_val is None:
            continue
        try:
            ts = start_dt.timestamp()
        except (AttributeError, ValueError, OSError):
            continue
        raw[name][ts] = float(sum_val)

    all_ts = sorted({ts for name in ids for ts in raw[name]})
    if not all_ts:
        return [], None, None, {
            "warnings": [],
            "missing_entities": missing_ents,
            "error": (
                "De gekozen entity's hebben nog geen uurstatistieken opgebouwd "
                "(0 rijen in de statistics-tabel voor: "
                + ", ".join(ids)
                + "). Statistic-id's die WEL uurstatistieken hebben (laatste 30 dagen): "
                + (", ".join(available_ids) if available_ids else "geen enkele")
                + ". Mogelijke oorzaken: unit- of state_class-wijziging (controleer "
                "Developer Tools -> Statistics op een waarschuwing en gebruik 'Fix'), "
                "een recorder-exclude, of meters zonder opgebouwde historie. Kies in "
                "de integratie-instellingen meters uit de lijst met data."
            ),
        }
    last_ts = all_ts[-1]

    # Beperk tot de meest recente 365 dagen
    cutoff = last_ts - MAX_HISTORY_DAYS * 86400
    all_ts = [ts for ts in all_ts if ts >= cutoff]
    first_ts = all_ts[0]

    # 3) Per entity uurverschillen berekenen (met reset-detectie)
    warnings = []
    if missing_ents:
        warnings.append(
            "Geen statistieken voor (genegeerd): " + ", ".join(missing_ents)
        )
    deltas: dict[str, dict[float, float]] = {}
    for eid, sid in resolved.items():
        series = raw.get(sid, {})
        prev_sum = None
        prev_ts = None
        d = {}
        resets = 0
        missing = 0
        for ts in all_ts:
            s = series.get(ts)
            if s is None:
                missing += 1
                continue
            if prev_sum is not None:
                delta = s - prev_sum
                if delta < 0:
                    # Meterreset of vervuilde sensorstand
                    resets += 1
                    delta = 0.0
                d[ts] = max(0.0, delta)
            prev_sum = s
            prev_ts = ts
        deltas[eid] = d
        if resets > 5:
            warnings.append(
                f"Entity {eid}: {resets} x een teruglopende meterstand gevonden "
                "(sensorreset of vervuilde data). Deze uren zijn genegeerd — "
                "controleer deze sensor, bijv. op een overflow."
            )
        if missing > len(all_ts) * 0.3:
            warnings.append(
                f"Entity {eid}: {100 - int(100*missing/len(all_ts))}% van de uren "
                "heeft data; de rest is leeg. Overweeg een consistente meterbron."
            )
    if len(all_ts) < MIN_ANALYSIS_DAYS * 24:
        warnings.append(
            f"Minder dan {MIN_ANALYSIS_DAYS} dagen historie; het advies is nu "
            "onbetrouwbaar omdat seizoensverschillen ontbreken."
        )

    # 4) Groepssommen per uur (tarieven bij elkaar optellen)
    hours = []
    for ts in all_ts:
        row = []
        for group in ("import", "export", "solar"):
            total = 0.0
            for e in groups.get(group, []):
                total += deltas.get(e, {}).get(ts, 0.0)
            row.append(total)
        hours.append((ts, row[0], row[1], row[2]))

    quality = {
        "warnings": warnings,
        "hours_found": len(all_ts),
        "missing_entities": missing_ents,
        "groups": {k: v for k, v in groups.items()},
    }
    return hours, first_ts, last_ts, quality


# ---------------------------------------------------------------------------
# Analyse
# ---------------------------------------------------------------------------


async def async_run_analysis(hass: HomeAssistant, entry: ConfigEntry) -> dict:
    """Volledige analyse: ophalen, simuleren, advies samenstellen."""
    data = {**entry.data, **(entry.options or {})}

    price_import = float(data.get(CONF_PRICE_IMPORT, 0.30))
    price_export = float(data.get(CONF_PRICE_EXPORT, 0.0))
    cost_kwh = float(data.get(CONF_BATTERY_COST_KWH, 450.0))
    cost_fixed = float(data.get(CONF_BATTERY_COST_FIXED, 1500.0))
    efficiency = max(0.5, min(0.99, float(data.get(CONF_BATTERY_EFFICIENCY, 90.0)) / 100.0))
    max_power = float(data.get(CONF_BATTERY_MAX_POWER_KW, 3.0))
    max_capacity = float(data.get(CONF_MAX_CAPACITY, DEFAULT_MAX_CAPACITY))

    groups = _get_groups(data)
    if "import" not in groups or "export" not in groups:
        raise HomeAssistantError(
            "Geen verbruiks- of teruglevermeters geconfigureerd. Open de "
            "integratie-instellingen en vink de P1-meters aan."
        )

    hours, first_ts, last_ts, quality = await hass.async_add_executor_job(
        _fetch_hourly_kwh, hass, groups
    )
    if not hours or first_ts is None:
        detail = quality.get("error") if quality else None
        missing = quality.get("missing_entities") if quality else []
        msg = "Geen uurstatistieken gevonden."
        if missing:
            msg += f" Geen statistieken voor: {', '.join(missing)}."
        msg += (
            " Controleer of de gekozen entity's kWh-totaaltellers zijn "
            "(state_class: total_increasing of total, device_class: energy) en "
            "of ze voorkomen onder Developer Tools -> Statistics. "
            "Vermogenssensoren (W), 'vandaag'-sensoren zonder totale-meter of "
            "net aangemaakte helpers zonder historie bouwen nog geen "
            "uurstatistieken op."
        )
        if detail:
            msg += f" Detail: {detail}"
        raise HomeAssistantError(msg)

    days = max(1.0, (last_ts - first_ts) / 86400)
    scale = 365.0 / days

    total_import = sum(h[1] for h in hours)
    total_export = sum(h[2] for h in hours)
    total_solar = sum(h[3] for h in hours)

    # --- simulatie per capaciteit -----------------------------------------
    one_way_eff = efficiency ** 0.5
    step = 0.5
    results = []
    prev_yearly_saved = 0.0
    cap = step
    while cap <= max_capacity + 1e-6:
        soc = 0.0
        saved = 0.0
        charged = 0.0
        for _ts, imp, exp, _sol in hours:
            # Laden uit eigen teruglevering
            charge = min(exp, max_power, cap - soc)
            if charge > 0:
                soc += charge * one_way_eff
                charged += charge
            # Ontladen tegen verbruik uit het net
            discharge = min(imp, max_power, soc)
            if discharge > 0:
                soc -= discharge / one_way_eff
                saved += discharge
        yearly_saved = saved * scale
        yearly_charged = charged * scale
        autarkie = 100.0 * saved / total_import if total_import else 0.0
        invest = cost_fixed + cost_kwh * cap
        # Netto besparing: vermeden afname minus gemiste terugleververgoeding
        # over de hoeveelheid die uit eigen teruglevering is geladen.
        yearly_savings = yearly_saved * price_import - yearly_charged * price_export
        payback = invest / yearly_savings if yearly_savings > 0 else None
        marginal = yearly_saved - prev_yearly_saved
        results.append(
            {
                "capacity_kwh": round(cap, 1),
                "yearly_saved_kwh": round(yearly_saved, 0),
                "marginal_yearly_kwh": round(marginal, 0),
                "autarkie_pct": round(autarkie, 1),
                "cycles_per_year": round(yearly_charged / cap, 1) if cap > 0 else 0,
                "investment_eur": round(invest, 0),
                "yearly_savings_eur": round(yearly_savings, 0),
                "payback_years": round(payback, 1) if payback else None,
            }
        )
        prev_yearly_saved = yearly_saved
        cap += step

    # --- aanbevelingen ------------------------------------------------------
    # Beste waarde-voor-geld: de grootste capaciteit waarvan de
    # terugverdientijd binnen PAYBACK_TOLERANCE van de best haalbare ligt.
    # Zo kiest de vaste kostencomponent niet structureel de kleinste batterij.
    payback_results = [r for r in results if r["payback_years"] is not None]
    if payback_results:
        best_payback = min(r["payback_years"] for r in payback_results)
        recommended = max(
            (
                r
                for r in payback_results
                if r["payback_years"] <= best_payback * PAYBACK_TOLERANCE
            ),
            key=lambda r: r["capacity_kwh"],
        )
    else:
        # Geen enkele combinatie verdient zich terug (bijv. teruglevertarief
        # hoger dan de stroomprijs): kies dan de kleinste capaciteit.
        recommended = min(results, key=lambda r: r["capacity_kwh"])
    # Maximale zinvolle capaciteit: waar extra kWh nog >= 25 kWh/jaar oplevert
    max_useful = max(
        (r["capacity_kwh"] for r in results if r["marginal_yearly_kwh"] >= MARGINAL_KWH_THRESHOLD),
        default=None,
    )

    # --- seizoensanalyse -----------------------------------------------------
    months: dict[str, dict[str, float]] = {}
    for ts, imp, exp, sol in hours:
        key = datetime.fromtimestamp(ts).strftime("%Y-%m")
        m = months.setdefault(key, {"import": 0.0, "export": 0.0, "solar": 0.0})
        m["import"] += imp
        m["export"] += exp
        m["solar"] += sol
    seasonal = {
        "winter": {"import": 0.0, "export": 0.0, "solar": 0.0},
        "zomer": {"import": 0.0, "export": 0.0, "solar": 0.0},
    }
    for key, m in months.items():
        month = int(key.split("-")[1])
        season = "winter" if month in (11, 12, 1, 2) else ("zomer" if month in (5, 6, 7, 8) else None)
        if season:
            for k in seasonal[season]:
                seasonal[season][k] += m[k]

    # --- advies zonnepanelen ----------------------------------------------
    avg_daily_solar = total_solar / days
    avg_daily_export = total_export / days
    avg_daily_import = total_import / days
    export_ratio = (total_export / total_solar) if total_solar else 0.0

    panel_advice = []
    if total_solar == 0:
        panel_advice.append(
            "Geen productie-entity gekoppeld; advies over de panelen is beperkt. "
            "Koppel je omvormer-entiteit voor een beter advies."
        )
    if avg_daily_import > avg_daily_solar * 1.5:
        panel_advice.append(
            f"Je verbruikt gemiddeld {avg_daily_import:.1f} kWh/dag tegen {avg_daily_solar:.1f} kWh/dag "
            "opwek: uitbreiden van de zonnepanelen is interessanter dan alleen een batterij, "
            "want de meeste opwek verbruik je zelf nog niet."
        )
    if export_ratio > 0.6 and total_solar > 0:
        panel_advice.append(
            f"{export_ratio*100:.0f}% van je opwek lever je terug aan het net. "
            "Uitbreiden van de panelen heeft dan weinig zin zonder (grotere) batterij; "
            "de batterij vangt de teruglevering op. Verbruiksverschuiving naar "
            "zonnige uren (wasmachine, droger, airco) vergroot het rendement extra."
        )
    if avg_daily_export > (recommended["capacity_kwh"] or 0) * 0.8:
        panel_advice.append(
            "Je dagelijkse teruglevering is groot genoeg om de aanbevolen batterij "
            "volledig te laden: er is geen noodzaak om de omvormer/panelen aan te passen."
        )
    if not panel_advice:
        panel_advice.append(
            "Je huidige paneelcapaciteit is in balans met je verbruik; "
            "geen aanpassing nodig om een batterij rendabel te maken."
        )

    # --- rapport (markdown) -----------------------------------------------
    table_rows = "\n".join(
        f"| {r['capacity_kwh']} | {r['yearly_saved_kwh']:.0f} | {r['autarkie_pct']} | "
        f"{r['investment_eur']:.0f} | {r['yearly_savings_eur']:.0f} | "
        f"{r['payback_years'] if r['payback_years'] else '—'} |"
        for r in results
    )
    warning_block = ""
    if quality.get("warnings"):
        warning_block = (
            "## ⚠️ Datakwaliteit\n\n"
            + "\n".join(f"- {w}" for w in quality["warnings"])
            + "\n\n"
        )
    max_useful_txt = f"{max_useful} kWh" if max_useful else "geen extra capaciteit levert nog iets op"
    report = (
        f"# 🔋 Thuisbatterij Analyse\n\n"
        f"**Geanalyseerde periode:** {days:.0f} dagen "
        f"({datetime.fromtimestamp(first_ts).strftime('%d-%m-%Y')} t/m "
        f"{datetime.fromtimestamp(last_ts).strftime('%d-%m-%Y')})\n\n"
        f"{warning_block}"
        f"| Kenmerk | Waarde |\n|---|---|\n"
        f"| Gemiddeld verbruik uit net | {avg_daily_import:.1f} kWh/dag |\n"
        f"| Gemiddelde teruglevering | {avg_daily_export:.1f} kWh/dag |\n"
        f"| Gemiddelde zonne-opwek | {avg_daily_solar:.1f} kWh/dag |\n"
        f"| Zelfgebruik zonder batterij | {100-export_ratio*100:.0f}% |\n\n"
        f"## Aanbeveling\n"
        f"**Aanbevolen capaciteit: {recommended['capacity_kwh']} kWh** "
        f"(grootste maat met een terugverdientijd binnen "
        f"{(PAYBACK_TOLERANCE - 1) * 100:.0f}% van de best haalbare)\n\n"
        f"- Maximale zinvolle capaciteit: **{max_useful_txt}** "
        f"(boven deze maat levert extra kWh minder dan {MARGINAL_KWH_THRESHOLD:.0f} kWh/jaar op)\n"
        f"- Jaarlijks vermeden afname: **{recommended['yearly_saved_kwh']:.0f} kWh**\n"
        f"- Netto jaarlijkse besparing: **€{recommended['yearly_savings_eur']:.0f}** "
        f"(incl. gemiste terugleververgoeding)\n"
        f"- Autarkie daarmee: **{recommended['autarkie_pct']}%**\n"
        f"- Investeringsindicatie: **€{recommended['investment_eur']:.0f}** "
        f"(bij €{cost_kwh:.0f}/kWh + €{cost_fixed:.0f} vast)\n"
        f"- Terugverdientijd: **{recommended['payback_years'] if recommended['payback_years'] else '—'} jaar**\n\n"
        f"## Advies zonnepanelen\n"
        + "\n".join(f"- {line}" for line in panel_advice)
        + "\n\n## Simulatie per capaciteit\n\n"
        f"| Capaciteit (kWh) | Vermeden afname (kWh/jr) | Autarkie % | Investeren (€) | "
        f"Netto besparing (€/jr) | Terugverdient (jr) |\n|---|---|---|---|---|---|\n"
        f"{table_rows}\n\n"
        f"_Aannames: round-trip rendement {efficiency*100:.0f}%, max {max_power:.1f} kW "
        f"laad/ontlaadvermogen, stroomprijs €{price_import:.2f}/kWh en "
        f"teruglevertarief €{price_export:.2f}/kWh. "
        f"De batterij laadt alleen uit eigen teruglevering._"
    )

    return {
        "days_analysed": round(days, 1),
        "period_start": datetime.fromtimestamp(first_ts).isoformat(),
        "period_end": datetime.fromtimestamp(last_ts).isoformat(),
        "avg_daily_import_kwh": round(avg_daily_import, 2),
        "avg_daily_export_kwh": round(avg_daily_export, 2),
        "avg_daily_solar_kwh": round(avg_daily_solar, 2),
        "self_consumption_pct": round(100 - export_ratio * 100, 1) if total_solar else None,
        "recommended_kwh": recommended["capacity_kwh"],
        "max_useful_kwh": max_useful,
        "yearly_saved_kwh": recommended["yearly_saved_kwh"],
        "yearly_savings": recommended["yearly_savings_eur"],
        "autarkie_pct": recommended["autarkie_pct"],
        "payback_years": recommended["payback_years"],
        "investment_eur": recommended["investment_eur"],
        "seasonal": {k: {kk: round(vv, 1) for kk, vv in v.items()} for k, v in seasonal.items()},
        "data_quality": quality,
        "simulation": results,
        "panel_advice": panel_advice,
        "report_markdown": report,
    }
