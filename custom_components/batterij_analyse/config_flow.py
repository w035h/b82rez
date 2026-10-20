"""Config flow for Thuisbatterij Analyse, met automatische P1-detectie."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    CONF_ENTITIES_IMPORT,
    CONF_ENTITIES_EXPORT,
    CONF_ENTITIES_SOLAR,
    CONF_PRICE_IMPORT,
    CONF_PRICE_EXPORT,
    CONF_BATTERY_COST_KWH,
    CONF_BATTERY_COST_FIXED,
    CONF_BATTERY_EFFICIENCY,
    CONF_BATTERY_MAX_POWER_KW,
    CONF_MAX_CAPACITY,
    DEFAULT_PRICE_IMPORT,
    DEFAULT_PRICE_EXPORT,
    DEFAULT_COST_KWH,
    DEFAULT_COST_FIXED,
    DEFAULT_EFFICIENCY,
    DEFAULT_MAX_POWER,
    DEFAULT_MAX_CAPACITY,
)

_LOGGER = logging.getLogger(__name__)

# Zoekwoorden om P1-meters automatisch te classificeren (kleine letters,
# matchen op de volledige entity_id).
KEYWORDS_SOLAR = (
    "pv_generation", "solar", "zonne", "opgewekt", "opwek", "production", "yield",
)
KEYWORDS_EXPORT = (
    "produced", "teruglever", "export", "feed_in", "feedin", "2_8", "levering",
)
KEYWORDS_IMPORT = (
    "consumed", "verbruik", "import", "afname", "1_8",
)


def _discover_energy_entities(hass: HomeAssistant):
    """Vind automatisch kWh-totaaltellers en classificeer ze.

    Retourneert (imports, exports, solar): gesorteerde lijsten entity-id's.
    Fouten worden gelogd maar nooit gegooid (voorkomt 500 in de flow).
    """
    imports: list[str] = []
    exports: list[str] = []
    solar: list[str] = []
    try:
        for state in hass.states.async_all("sensor"):
            attrs = state.attributes
            if attrs.get("device_class") != "energy":
                continue
            if attrs.get("state_class") not in ("total_increasing", "total"):
                continue
            eid = state.entity_id.lower()
            if any(k in eid for k in KEYWORDS_SOLAR):
                solar.append(state.entity_id)
            elif any(k in eid for k in KEYWORDS_EXPORT):
                exports.append(state.entity_id)
            elif any(k in eid for k in KEYWORDS_IMPORT):
                imports.append(state.entity_id)
    except Exception:  # noqa: BLE001 - nooit de flow laten crashen
        _LOGGER.exception("Fout bij automatisch detecteren van P1-meters")
    return sorted(imports), sorted(exports), sorted(solar)


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [v for v in value if v]


def _build_schema(hass: HomeAssistant, defaults: dict | None = None) -> vol.Schema:
    """Bouw het formulier-schema met automatisch gedetecteerde defaults."""
    d = defaults or {}
    det_imp, det_exp, det_sol = _discover_energy_entities(hass)

    def _default(key: str, detected: list[str]):
        stored = _as_list(d.get(key))
        return stored if stored else detected

    energy_multi = selector.EntitySelector(
        selector.EntitySelectorConfig(domain="sensor", device_class="energy", multiple=True)
    )

    return vol.Schema(
        {
            vol.Required(
                CONF_ENTITIES_IMPORT,
                default=_default(CONF_ENTITIES_IMPORT, det_imp),
            ): energy_multi,
            vol.Required(
                CONF_ENTITIES_EXPORT,
                default=_default(CONF_ENTITIES_EXPORT, det_exp),
            ): energy_multi,
            vol.Optional(
                CONF_ENTITIES_SOLAR,
                default=_default(CONF_ENTITIES_SOLAR, det_sol),
            ): energy_multi,
            vol.Required(
                CONF_PRICE_IMPORT,
                default=d.get(CONF_PRICE_IMPORT, DEFAULT_PRICE_IMPORT),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0.0, max=2.0, step=0.01)
            ),
            vol.Required(
                CONF_PRICE_EXPORT,
                default=d.get(CONF_PRICE_EXPORT, DEFAULT_PRICE_EXPORT),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0.0, max=2.0, step=0.01)
            ),
            vol.Required(
                CONF_BATTERY_COST_KWH,
                default=d.get(CONF_BATTERY_COST_KWH, DEFAULT_COST_KWH),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0.0, max=5000.0, step=10.0)
            ),
            vol.Required(
                CONF_BATTERY_COST_FIXED,
                default=d.get(CONF_BATTERY_COST_FIXED, DEFAULT_COST_FIXED),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0.0, max=50000.0, step=50.0)
            ),
            vol.Required(
                CONF_BATTERY_EFFICIENCY,
                default=d.get(CONF_BATTERY_EFFICIENCY, DEFAULT_EFFICIENCY),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=50.0, max=99.0, step=1.0)
            ),
            vol.Required(
                CONF_BATTERY_MAX_POWER_KW,
                default=d.get(CONF_BATTERY_MAX_POWER_KW, DEFAULT_MAX_POWER),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0.5, max=22.0, step=0.5)
            ),
            vol.Required(
                CONF_MAX_CAPACITY,
                default=d.get(CONF_MAX_CAPACITY, DEFAULT_MAX_CAPACITY),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1.0, max=100.0, step=1.0)
            ),
        }
    )


def _validate(user_input: dict | None) -> dict:
    """Valideer de invoer; retourneert een errors-dict (leeg = geldig)."""
    errors: dict = {}
    imp = _as_list((user_input or {}).get(CONF_ENTITIES_IMPORT))
    exp = _as_list((user_input or {}).get(CONF_ENTITIES_EXPORT))
    if not imp:
        errors[CONF_ENTITIES_IMPORT] = "required_import"
    elif not exp:
        errors[CONF_ENTITIES_EXPORT] = "required_export"
    elif set(imp) & set(exp):
        errors[CONF_ENTITIES_EXPORT] = "overlap"
    return errors


class BatterijAnalyseConfigFlow(config_entries.ConfigFlow, domain="batterij_analyse"):
    """Handle the config flow for Thuisbatterij Analyse."""

    VERSION = 2

    async def async_step_user(self, user_input=None):
        """Stap 1: entity's (automatisch voorgesteld) en parameters kiezen."""
        errors = {}
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                return self.async_create_entry(title="Thuisbatterij Analyse", data=user_input)
        try:
            schema = _build_schema(self.hass, user_input if errors else None)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Fout bij bouwen van config-flow schema")
            schema = vol.Schema({})
            errors["base"] = "schema_error"
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return BatterijAnalyseOptionsFlow()


class BatterijAnalyseOptionsFlow(config_entries.OptionsFlow):
    """Allow changing the settings later.

    Home Assistant (>= 2024.12) zet de gekoppelde config entry automatisch
    als de read-only property `self.config_entry`. Deze mag dus NIET meer
    handmatig in __init__ worden toegewezen (dat crasht op HA >= 2025.12).
    """

    async def async_step_init(self, user_input=None):
        """Opties aanpassen."""
        errors = {}
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                return self.async_create_entry(title="", data=user_input)
        try:
            schema = _build_schema(
                self.hass,
                {**self.config_entry.data, **(self.config_entry.options or {})},
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Fout bij bouwen van options-flow schema")
            schema = vol.Schema({})
            errors["base"] = "schema_error"
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )
