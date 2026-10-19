"""Sensors for Thuisbatterij Analyse."""

from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CURRENCY_EURO,
    PERCENTAGE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfEnergy,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import ATTR_RESULT, DOMAIN, EVENT_UPDATED

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    store = hass.data[DOMAIN][entry.entry_id]

    entities = [
        AnalyseSensor(
            store,
            entry,
            "recommended_kwh",
            "Aanbevolen batterijcapaciteit",
            UnitOfEnergy.KILO_WATT_HOUR,
            "battery_capacity",
            1,
        ),
        AnalyseSensor(
            store,
            entry,
            "yearly_savings",
            "Jaarlijkse besparing batterij",
            CURRENCY_EURO,
            "savings",
            0,
        ),
        AnalyseSensor(
            store,
            entry,
            "yearly_saved_kwh",
            "Jaarlijks bespaarde energie",
            UnitOfEnergy.KILO_WATT_HOUR,
            "saved_energy",
            0,
        ),
        AnalyseSensor(
            store,
            entry,
            "autarkie_pct",
            "Autarkie met batterij",
            PERCENTAGE,
            "autarky",
            1,
        ),
        AnalyseSensor(
            store,
            entry,
            "payback_years",
            "Terugverdientijd batterij",
            UnitOfTime.YEARS,
            "payback",
            1,
        ),
    ]
    async_add_entities(entities)


class AnalyseSensor(RestoreEntity, SensorEntity):
    """Sensor met de laatste analyseresultaten."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, store, entry: ConfigEntry, key: str, name: str, unit, icon_id: str, precision: int):
        self._store = store
        self._key = key
        self._entry = entry
        self._unit = unit
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_suggested_display_precision = precision
        self._attr_icon = "mdi:battery-charging"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Thuisbatterij Analyse",
        }

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self.hass.bus.async_listen(EVENT_UPDATED, self._on_update)
        )
        self._update_from_store()
        # Herstel de laatste waarde na een herstart, zodat de sensors
        # niet leeg zijn tot de volgende analyse draait.
        last_state = await self.async_get_last_state()
        if (
            last_state is not None
            and self._attr_native_value is None
            and last_state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE)
        ):
            try:
                self._attr_native_value = float(last_state.state)
            except ValueError:
                _LOGGER.debug(
                    "Kon vorige waarde %s van %s niet herstellen",
                    last_state.state,
                    self.entity_id,
                )

    @callback
    def _on_update(self, _event) -> None:
        self._update_from_store()
        self.async_write_ha_state()

    @callback
    def _update_from_store(self) -> None:
        result = self._store.get(ATTR_RESULT)
        if result is None:
            self._attr_native_value = None
            self._attr_extra_state_attributes = {"status": "Druk op de Start analyse-knop of roep batterij_analyse.start aan"}
            return
        self._attr_native_value = result.get(self._key)
        if self._key == "yearly_savings":
            self._attr_extra_state_attributes = {
                "period_start": result.get("period_start"),
                "period_end": result.get("period_end"),
                "days_analysed": result.get("days_analysed"),
                "max_useful_kwh": result.get("max_useful_kwh"),
                "seasonal": result.get("seasonal"),
                "data_quality": result.get("data_quality"),
                "report_markdown": result.get("report_markdown"),
            }
        elif self._key == "recommended_kwh":
            self._attr_extra_state_attributes = {
                "panel_advice": result.get("panel_advice"),
                "max_useful_kwh": result.get("max_useful_kwh"),
                "simulation": result.get("simulation"),
            }

    @property
    def device_class(self):
        if self._unit == UnitOfEnergy.KILO_WATT_HOUR:
            return SensorDeviceClass.ENERGY
        return None

