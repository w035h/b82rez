"""Config flow for Thuisbatterij Analyse."""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

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
    DEFAULT_PRICE_IMPORT,
    DEFAULT_PRICE_EXPORT,
    DEFAULT_COST_KWH,
    DEFAULT_COST_FIXED,
    DEFAULT_EFFICIENCY,
    DEFAULT_MAX_POWER,
    DEFAULT_MAX_CAPACITY,
)

ENERGY_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="sensor", device_class="energy")
)


def _build_schema(defaults: dict | None = None) -> vol.Schema:
    """Bouw het formulier-schema, met bestaande waarden als default."""
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_ENTITY_IMPORT,
                description={"suggested_value": d.get(CONF_ENTITY_IMPORT)},
            ): ENERGY_SELECTOR,
            vol.Required(
                CONF_ENTITY_EXPORT,
                description={"suggested_value": d.get(CONF_ENTITY_EXPORT)},
            ): ENERGY_SELECTOR,
            vol.Optional(
                CONF_ENTITY_SOLAR,
                description={"suggested_value": d.get(CONF_ENTITY_SOLAR)},
            ): ENERGY_SELECTOR,
            vol.Required(
                CONF_PRICE_IMPORT,
                default=d.get(CONF_PRICE_IMPORT, DEFAULT_PRICE_IMPORT),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.0, max=2.0, step=0.01, unit_of_measurement="€/kWh"
                )
            ),
            vol.Required(
                CONF_PRICE_EXPORT,
                default=d.get(CONF_PRICE_EXPORT, DEFAULT_PRICE_EXPORT),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.0, max=2.0, step=0.01, unit_of_measurement="€/kWh"
                )
            ),
            vol.Required(
                CONF_BATTERY_COST_KWH,
                default=d.get(CONF_BATTERY_COST_KWH, DEFAULT_COST_KWH),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.0, max=5000.0, step=10.0, unit_of_measurement="€/kWh"
                )
            ),
            vol.Required(
                CONF_BATTERY_COST_FIXED,
                default=d.get(CONF_BATTERY_COST_FIXED, DEFAULT_COST_FIXED),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.0, max=50000.0, step=50.0, unit_of_measurement="€"
                )
            ),
            vol.Required(
                CONF_BATTERY_EFFICIENCY,
                default=d.get(CONF_BATTERY_EFFICIENCY, DEFAULT_EFFICIENCY),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=50.0, max=99.0, step=1.0, unit_of_measurement="%"
                )
            ),
            vol.Required(
                CONF_BATTERY_MAX_POWER_KW,
                default=d.get(CONF_BATTERY_MAX_POWER_KW, DEFAULT_MAX_POWER),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.5, max=22.0, step=0.5, unit_of_measurement="kW"
                )
            ),
            vol.Required(
                CONF_MAX_CAPACITY,
                default=d.get(CONF_MAX_CAPACITY, DEFAULT_MAX_CAPACITY),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1.0, max=100.0, step=1.0, unit_of_measurement="kWh"
                )
            ),
        }
    )


class BatterijAnalyseConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Thuisbatterij Analyse."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Stap 1: entity's en parameters kiezen."""
        errors = {}
        if user_input is not None:
            # Basisvalidatie: import en export mogen niet dezelfde entity zijn
            if user_input.get(CONF_ENTITY_IMPORT) == user_input.get(CONF_ENTITY_EXPORT):
                errors[CONF_ENTITY_EXPORT] = "same_entity"
            elif not errors:
                return self.async_create_entry(title="Thuisbatterij Analyse", data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema(user_input if errors else None),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return BatterijAnalyseOptionsFlow(config_entry)


class BatterijAnalyseOptionsFlow(config_entries.OptionsFlow):
    """Allow changing the settings later."""

    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Opties aanpassen."""
        errors = {}
        if user_input is not None:
            if user_input.get(CONF_ENTITY_IMPORT) == user_input.get(CONF_ENTITY_EXPORT):
                errors[CONF_ENTITY_EXPORT] = "same_entity"
            elif not errors:
                return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=_build_schema(
                {**self.config_entry.data, **(self.config_entry.options or {})}
            ),
            errors=errors,
        )
