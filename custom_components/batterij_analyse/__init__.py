"""Thuisbatterij Analyse: analyseert P1- en zonnepaneelhistorie en
simuleert de businesscase van een thuisbatterij."""

from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.typing import ConfigType

from .const import (
    DOMAIN,
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

PLATFORMS = ["sensor"]

SERVICE_START = "start"

MAX_HISTORY_DAYS = 365


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration (nothing needed at yaml level)."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry."""
    hass.data[DOMAIN][entry.entry_id] = {
        "entry": entry,
        ATTR_RESULT: None,
    }
    await hass.config_entries.async_forward_platform_setups(entry, PLATFORMS)

    async def async_handle_start(call: ServiceCall) -> None:
        """Run the analysis for the (optionally given) config entry."""
        entry_id = call.data.get("entry_id")
        if entry_id and entry_id in hass.data[DOMAIN]:
            target = hass.data[DOMAIN][entry_id]
        else:
            target = next(iter(hass.data[DOMAIN].values()))
        if target is None:
            raise HomeAssistantError("Thuisbatterij Analyse is nog niet geconfigureerd.")

        result = await async_run_analysis(hass, target["entry"])
        target[ATTR_RESULT] = result
        _LOGGER.info(
            "Thuisbatterij Analyse klaar: aanbevolen %.1f kWh, besparing €%.0f/jaar",
            result["recommended_kwh"],
            result["yearly_savings"],
        )
        hass.bus.async_fire(EVENT_UPDATED, {"entry_id": target["entry"].entry_id})

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


def _fetch_hourly_kwh(hass: HomeAssistant, statistic_ids: list[str]):
    """Haal uurlijkse kWh uit de recorder long-term statistics.

    Retourneert: (dict met per uur een dict {import, export, solar},
    tijdstip eerste uur, tijdstip laatste uur)
    """
    from homeassistant.components.recorder import get_instance
    from homeassistant.components.recorder.db_schema import Statistics, StatisticsMeta
    from sqlalchemy import select

    ids = [s for s in statistic_ids if s]
    if not ids:
        return [], None, None

    instance = get_instance(hass)
    session = instance.get_session()
    try:
        meta_rows = session.execute(
            select(StatisticsMeta.id, StatisticsMeta.statistic_id).where(
                StatisticsMeta.statistic_id.in_(ids)
            )
        ).all()
        id_to_name = {row[0]: row[1] for row in meta_rows}
        if not id_to_name:
            return [], None, None
        stat_rows = session.execute(
            select(
                Statistics.metadata_id,
                Statistics.start,
                Statistics.sum,
            ).where(Statistics.metadata_id.in_(id_to_name))
        ).all()
    finally:
        session.close()

    raw: dict[str, dict[float, float]] = {name: {} for name in ids}
    first_ts = None
    last_ts = None
    for meta_id, start_dt, sum_val in stat_rows:
        name = id_to_name.get(meta_id)
        if name is None or sum_val is None:
            continue
        try:
            ts = start_dt.timestamp()
        except (AttributeError, ValueError, OSError):
            continue
        raw[name][ts] = float(sum_val)
        if first_ts is None or ts < first_ts:
            first_ts = ts
        if last_ts is None or ts > last_ts:
            last_ts = ts

    cutoff = None
    if first_ts is not None and last_ts is not None:
        span_days = (last_ts - first_ts) / 86400
        if span_days > MAX_HISTORY_DAYS:
            cutoff = last_ts - MAX_HISTORY_DAYS * 86400

    all_ts = sorted(
        {
            ts
            for name in ids
            for ts in raw[name]
            if cutoff is None or ts >= cutoff
        }
    )

    hours = []
    for ts in all_ts:
        imp = raw.get(statistic_ids[0], {}).get(ts, 0.0) if statistic_ids[0] else 0.0
        exp = raw.get(statistic_ids[1], {}).get(ts, 0.0) if len(statistic_ids) > 1 and statistic_ids[1] else 0.0
        sol = raw.get(statistic_ids[2], {}).get(ts, 0.0) if len(statistic_ids) > 2 and statistic_ids[2] else 0.0
        hours.append((ts, imp, exp, sol))

    first = all_ts[0] if all_ts else None
    last = all_ts[-1] if all_ts else None
    return hours, first, last


async def async_run_analysis(hass: HomeAssistant, entry: ConfigEntry) -> dict:
    """Volledige analyse: ophalen, simuleren, advies samenstellen."""
    data = {**entry.data, **(entry.options or {})}
    import_ent = data[CONF_ENTITY_IMPORT]
    export_ent = data[CONF_ENTITY_EXPORT]
    solar_ent = data.get(CONF_ENTITY_SOLAR) or None

    price_import = float(data.get(CONF_PRICE_IMPORT, 0.30))
    price_export = float(data.get(CONF_PRICE_EXPORT, 0.0))
    cost_kwh = float(data.get(CONF_BATTERY_COST_KWH, 450.0))
    cost_fixed = float(data.get(CONF_BATTERY_COST_FIXED, 1500.0))
    efficiency = max(0.5, min(0.99, float(data.get(CONF_BATTERY_EFFICIENCY, 90.0)) / 100.0))
    max_power = float(data.get(CONF_BATTERY_MAX_POWER_KW, 3.0))
    max_capacity = float(data.get(CONF_MAX_CAPACITY, DEFAULT_MAX_CAPACITY))

    hours, first_ts, last_ts = await hass.async_add_executor_job(
        _fetch_hourly_kwh, hass, [import_ent, export_ent, solar_ent or ""]
    )
    if not hours or first_ts is None:
        raise HomeAssistantError(
            "Geen uurstatistieken gevonden. Controleer of de gekozen entity's "
            "kWh-meterstanden zijn (state_class: total_increasing)."
        )

    days = max(1.0, (last_ts - first_ts) / 86400)
    scale = 365.0 / days

    total_import = sum(h[1] for h in hours)
    total_export = sum(h[2] for h in hours)
    total_solar = sum(h[3] for h in hours)

    # --- simulatie per capaciteit -----------------------------------------
    one_way_eff = efficiency ** 0.5
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
        # Besparing = vermeden afname tegen de stroomprijs.
        yearly_savings = yearly_saved * price_import
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

    # --- aanbeveling: maat met de kortste terugverdientijd -----------------
    recommended = min(
        results,
        key=lambda r: (
            r["payback_years"] is None,
            r["payback_years"] if r["payback_years"] else 0,
        ),
    )

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
            "de batterij vangt de teruglevering op."
        )
    if avg_daily_export > recommended["capacity_kwh"] * 0.8:
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
    report = (
        f"# 🔋 Thuisbatterij Analyse\n\n"
        f"**Geanalyseerde periode:** {days:.0f} dagen "
        f"({datetime.fromtimestamp(first_ts).strftime('%d-%m-%Y')} t/m "
        f"{datetime.fromtimestamp(last_ts).strftime('%d-%m-%Y')})\n\n"
        f"| Kenmerk | Waarde |\n|---|---|\n"
        f"| Gemiddeld verbruik uit net | {avg_daily_import:.1f} kWh/dag |\n"
        f"| Gemiddelde teruglevering | {avg_daily_export:.1f} kWh/dag |\n"
        f"| Gemiddelde zonne-opwek | {avg_daily_solar:.1f} kWh/dag |\n"
        f"| Zelfgebruik zonder batterij | {100-export_ratio*100:.0f}% |\n\n"
        f"## Aanbeveling\n"
        f"**Aanbevolen capaciteit: {recommended['capacity_kwh']} kWh**\n\n"
        f"- Jaarlijks bespaard: **{recommended['yearly_saved_kwh']:.0f} kWh** "
        f"(≈ €{recommended['yearly_savings_eur']:.0f}/jaar bij €{price_import:.2f}/kWh)\n"
        f"- Autarkie daarmee: **{recommended['autarkie_pct']}%**\n"
        f"- Investeringsindicatie: **€{recommended['investment_eur']:.0f}** "
        f"(bij €{cost_kwh:.0f}/kWh + €{cost_fixed:.0f} vast)\n"
        f"- Terugverdientijd: **{recommended['payback_years'] if recommended['payback_years'] else '—'} jaar**\n\n"
        f"## Advies zonnepanelen\n"
        + "\n".join(f"- {line}" for line in panel_advice)
        + f"\n\n## Simulatie per capaciteit\n\n"
        f"| Capaciteit (kWh) | Bespaard (kWh/jr) | Autarkie % | Investeren (€) | "
        f"Besparing (€/jr) | Terugverdient (jr) |\n|---|---|---|---|---|---|\n"
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
        "yearly_saved_kwh": recommended["yearly_saved_kwh"],
        "yearly_savings": recommended["yearly_savings_eur"],
        "autarkie_pct": recommended["autarkie_pct"],
        "payback_years": recommended["payback_years"],
        "investment_eur": recommended["investment_eur"],
        "simulation": results,
        "panel_advice": panel_advice,
        "report_markdown": report,
    }