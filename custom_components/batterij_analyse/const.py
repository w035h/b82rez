"""Constants for the Thuisbatterij Analyse integration."""

DOMAIN = "batterij_analyse"

CONF_ENTITY_IMPORT = "entity_import"
CONF_ENTITY_EXPORT = "entity_export"
CONF_ENTITY_SOLAR = "entity_solar"
CONF_PRICE_IMPORT = "price_import"
CONF_PRICE_EXPORT = "price_export"
CONF_BATTERY_COST_KWH = "battery_cost_kwh"
CONF_BATTERY_COST_FIXED = "battery_cost_fixed"
CONF_BATTERY_EFFICIENCY = "battery_efficiency"
CONF_BATTERY_MAX_POWER_KW = "battery_max_power_kw"
CONF_MAX_CAPACITY = "max_capacity"

DEFAULT_PRICE_IMPORT = 0.30
DEFAULT_PRICE_EXPORT = 0.00
DEFAULT_COST_KWH = 450.0
DEFAULT_COST_FIXED = 1500.0
DEFAULT_EFFICIENCY = 90.0
DEFAULT_MAX_POWER = 3.0
DEFAULT_MAX_CAPACITY = 20.0

EVENT_UPDATED = "batterij_analyse_updated"

ATTR_RESULT = "result"