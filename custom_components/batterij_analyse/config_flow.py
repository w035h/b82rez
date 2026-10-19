"""Config flow for Thuisbatterij Analyse."""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

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

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ENTITY_IMPORT): str,
        vol.Required(CONF_ENTITY_EXPORT): str,
        vol.Optional(CONF_ENTITY_SOLAR): str,
        vol.Required(CONF_PRICE_IMPORT, default=DEFAULT_PRICE_IMPORT): float,
        vol.Required(CONF_PRICE_EXPORT, default=DEFAULT_PRICE_EXPORT): float,
        vol.Required(CONF_BATTERY_COST_KWH, default=DEFAULT_COST_KWH): float,
        vol.Required(CONF_BATTERY_COST_FIXED, default=DEFAULT_COST_FIXED): float,
        vol.Required(CONF_BATTERY_EFFICIENCY, default=DEFAULT_EFFICIENCY): float,
        vol.Required(CONF_BATTERY_MAX_POWER_KW, default=DEFAULT_MAX_POWER): float,
        vol.Required(CONF_MAX_CAPACITY, default=DEFAULT_MAX_CAPACITY): float,
    }
)


class BatterijAnalyseConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for Thuisbatterij Analyse."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            return self.async_create_entry(title="Thuisbatterij Analyse", data=user_input)
        return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return BatterijAnalyseOptionsFlow(config_entry)


class BatterijAnalyseOptionsFlow(config_entries.OptionsFlow):
    """Allow changing the settings later."""

    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        data = self.config_entry.data
        schema = vol.Schema(
            {
                vol.Required(CONF_ENTITY_IMPORT, default=data.get(CONF_ENTITY_IMPORT)): str,
                vol.Required(CONF_ENTITY_EXPORT, default=data.get(CONF_ENTITY_EXPORT)): str,
                vol.Optional(CONF_ENTITY_SOLAR, default=data.get(CONF_ENTITY_SOLAR)): str,
                vol.Required(CONF_PRICE_IMPORT, default=data.get(CONF_PRICE_IMPORT, DEFAULT_PRICE_IMPORT)): float,
                vol.Required(CONF_PRICE_EXPORT, default=data.get(CONF_PRICE_EXPORT, DEFAULT_PRICE_EXPORT)): float,
                vol.Required(CONF_BATTERY_COST_KWH, default=data.get(CONF_BATTERY_COST_KWH, DEFAULT_COST_KWH)): float,
                vol.Required(CONF_BATTERY_COST_FIXED, default=data.get(CONF_BATTERY_COST_FIXED, DEFAULT_COST_FIXED)): float,
                vol.Required(CONF_BATTERY_EFFICIENCY, default=data.get(CONF_BATTERY_EFFICIENCY, DEFAULT_EFFICIENCY)): float,
                vol.Required(CONF_BATTERY_MAX_POWER_KW, default=data.get(CONF_BATTERY_MAX_POWER_KW, DEFAULT_MAX_POWER)): float,
                vol.Required(CONF_MAX_CAPACITY, default=data.get(CONF_MAX_CAPACITY, DEFAULT_MAX_CAPACITY)): float,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)