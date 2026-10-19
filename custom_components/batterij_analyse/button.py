"""Knop om de Thuisbatterij Analyse direct te starten.

De knop verschijnt als entity in hetzelfde apparaat als de sensoren,
zodat je de analyse naast de sensoren in het dashboard kunt bedienen
zonder de service handmatig aan te roepen.
"""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import async_start_analysis
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    store = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([StartAnalyseKnop(store, entry)])


class StartAnalyseKnop(ButtonEntity):
    """Knop die de volledige analyse opnieuw uitvoert."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:play-circle-outline"
    _attr_name = "Start analyse"

    def __init__(self, store, entry: ConfigEntry):
        self._store = store
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_start"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Thuisbatterij Analyse",
        }

    @property
    def extra_state_attributes(self) -> dict:
        """Toon de laatste resultaat-status op de knop."""
        result = self._store.get("result")
        if result is None:
            return {"status": "Nog niet gedraaid — druk op de knop om te starten."}
        return {
            "period_start": result.get("period_start"),
            "period_end": result.get("period_end"),
            "days_analysed": result.get("days_analysed"),
            "recommended_kwh": result.get("recommended_kwh"),
            "yearly_savings_eur": result.get("yearly_savings"),
        }

    async def async_press(self) -> None:
        """Start de analyse voor dit config entry."""
        _LOGGER.debug("Start-analyse-knop ingedrukt (entry %s)", self._entry.entry_id)
        await async_start_analysis(self.hass, self._entry.entry_id)
