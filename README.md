# 🔋 Thuisbatterij Analyse – Home Assistant custom integration

Deze integration haalt de historie van je **P1-meter (DSMR)** en je **omvormer/zonnepanelen** op uit de Home Assistant database (recorder long-term statistics) en simuleert jaarlijks wat een thuisbatterij van 0,5 t/m 20 kWh zou hebben bespaard. Je krijgt sensoren voor de aanbevolen capaciteit, jaarlijkse besparing, autarkie en terugverdientijd, plus een automatisch rapport met advies over je zonnepaneel-installatie.

## Installatie

1. Kopieer de map `custom_components/batterij_analyse/` uit deze repo naar de map `custom_components/` in je Home Assistant configuratiemap (via File editor, Samba, VS Code add-on of SSH).
2. Herstart Home Assistant.
3. Ga naar **Instellingen → Apparaten & Diensten → Integratie toevoegen** en zoek op **"Thuisbatterij Analyse"**.
4. Kies je entity's en vul je tarieven in (zie hieronder).
5. Roep daarna de service **`batterij_analyse.start`** aan (bijv. via Developer Tools → Services).
6. Voeg de dashboard-config hieronder toe aan een Lovelace-dashboard.

> **Belangrijk:** de gekozen energie-entity's moeten *kWh-meterstanden* zijn met `state_class: total_increasing` en `device_class: energy` (zoals DSMR levert). Alleen dan bestaat er uurhistorie in de recorder. Zorg dat de recorder-historie lang genoeg is; bij een nieuwe installatie wordt het advies beter naarmate er meer data is.

## Configuratie

| Veld | Wat invullen | Voorbeeld |
|---|---|---|
| `entity_import` | P1-meterstand **verbruik** uit het net (kWh) | `sensor.energy_import` |
| `entity_export` | P1-meterstand **teruglevering** (kWh) | `sensor.energy_export` |
| `entity_solar` | Omvormer-productie totaal (kWh, optioneel) | `sensor.zonnepanelen_opbrengst_totaal` |
| `price_import` | Jouw stroomprijs (€/kWh) | `0.30` |
| `price_export` | Teruglevertarief (€/kWh) | `0.00` |
| `battery_cost_kwh` | Batterijkosten per kWh geïnstalleerd (€/kWh) | `450` |
| `battery_cost_fixed` | Vaste installatiekosten (€) | `1500` |
| `battery_efficiency` | Round-trip rendement (%) | `90` |
| `battery_max_power_kw` | Max. laad/ontlaadvermogen (kW) | `3.0` |
| `max_capacity` | Maximaal te simuleren capaciteit (kWh) | `20` |

> **Tip:** vind je entity's via Developer Tools → States. Kies een **kWh-totaalteller** (total_increasing), geen vermogenssensor (W) of een Energy-dashboard-helper.

## Sensoren

- `sensor.aanbevolen_batterijcapaciteit` – aanbevolen maat (kWh)
- `sensor.jaarlijkse_besparing_batterij` – jaarlijkse besparing (€), met `report_markdown` als attribuut
- `sensor.jaarlijks_bespaarde_energie` – bespaarde energie (kWh/jaar)
- `sensor.autarkie_met_batterij` – autarkie (%)
- `sensor.terugverdientijd_batterij` – terugverdientijd (jaren)

## Dashboard-config (Lovelace)

```yaml
```

## Automatisering (wekelijkse herberekening)

```yaml
alias: "Batterij-analyse wekelijks"
description: "Herberekent de thuisbatterij-analyse elke zondagnacht"
trigger:
  - platform: time
    at: "03:30:00"
condition:
  - condition: time
    weekday:
      - sun
action:
  - service: batterij_analyse.start
    response_variable: result
mode: single
```

## Hoe de analyse werkt

1. **Data:** uurlijkse kWh uit de recorder long-term statistics van verbruik, teruglevering en (optioneel) opwek — max. 365 dagen terug.
2. **Simulatie:** voor elke capaciteit van 0,5 t/m het opgegeven maximum (stap 0,5 kWh) wordt uur voor uur nagebootst: de batterij laadt uit teruglevering (beperkt door vermogen en capaciteit, met éénrichtingsrendement √η) en ontlaadt tegen verbruik uit het net.
3. **Businesscase:** besparing = vermeden afname × stroomprijs; investering = vaste kosten + prijs per kWh; terugverdientijd = investering / jaarbesparing (geëxtrapoleerd naar een heel jaar).
4. **Aanbeveling:** de maat met de kortste terugverdientijd, met inzicht in de marginale opbrengst per extra kWh.
5. **Paneeladvies:** op basis van de verhouding opwek/verbruik/teruglevering wordt aangegeven of uitbreiden van de panelen zinvol is of dat de batterij de teruglevering juist opvangt.

### Beperkingen

- Vast tarief (geen dynamische uurprijzen) in de berekening.
- Uurkundige resolutie; pieken korter dan een uur worden gladgestreken.
- De batterij laadt alleen uit **eigen teruglevering** (geen net-opladen).
- Zonder gelinkte productie-entity blijft het paneeladvies beperkt.
