# 🔋 Thuisbatterij Analyse – Home Assistant custom integration

Deze integration haalt de historie van je **P1-meter (DSMR)** en je **omvormer/zonnepanelen** op uit de Home Assistant database (recorder long-term statistics) en simuleert jaarlijks wat een thuisbatterij van 0,5 t/m 20 kWh zou hebben bespaard. Je krijgt sensoren voor de aanbevolen capaciteit, jaarlijkse besparing, autarkie en terugverdientijd, plus een automatisch rapport met advies over je zonnepaneel-installatie.

Vanaf **v3.0.0** ondersteunt de integratie **meerdere meters per richting** (bijv. tarief 1 + tarief 2) en worden je P1-meters **automatisch gedetecteerd en voorgeselecteerd** in de configuratieflow.

## Installatie

### Via HACS

1. HACS → Integraties → (menu) → **Custom repositories** → voeg `https://github.com/w035h/b82rez` toe met categorie **Integration**.
2. Installeer **Thuisbatterij Analyse** en herstart Home Assistant.
3. Ga naar **Instellingen → Apparaten & Diensten → Integratie toevoegen** en zoek op **"Thuisbatterij Analyse"**.

> **Voor HACS-updates:** maak bij een nieuwe versie een GitHub-release met een tag die exact gelijk is aan de `version` in `manifest.json` (bijv. `v3.0.0` ↔ `"version": "3.0.0"`). Zonder bijpassende release-tag geeft HACS een versiefout.

### Handmatig

1. Kopieer de map `custom_components/batterij_analyse/` uit deze repo naar de map `custom_components/` in je Home Assistant configuratiemap.
2. Herstart Home Assistant.
3. Ga naar **Instellingen → Apparaten & Diensten → Integratie toevoegen** en zoek op **"Thuisbatterij Analyse"**.

## Configuratie

Bij het toevoegen scant de integratie je installatie en **selecteert automatisch** alle kWh-totaaltellers die het herkent als verbruik, teruglevering of zonne-opwek. Controleer de selectie en pas indien nodig aan.

| Veld | Wat invullen | Voorbeeld |
|---|---|---|
| `entities_import` | Verbruik uit het net — **meerdere meters mogelijk** (bijv. tarief 1 + tarief 2) | `sensor.p1_verbruik_tarief_1`, `sensor.p1_verbruik_tarief_2` |
| `entities_export` | Teruglevering aan het net — meerdere meters mogelijk | `sensor.p1_teruglever_tarief_1`, `sensor.p1_teruglever_tarief_2` |
| `entities_solar` | Omvormer-productie totaal (optioneel) | `sensor.goodwe_pv_generation_total` |
| `price_import` | Jouw stroomprijs (€/kWh) | `0.30` |
| `price_export` | Teruglevertarief (€/kWh) | `0.00` |
| `battery_cost_kwh` | Batterijkosten per kWh geïnstalleerd (€/kWh) | `450` |
| `battery_cost_fixed` | Vaste installatiekosten (€) | `1500` |
| `battery_efficiency` | Round-trip rendement (%) | `90` |
| `battery_max_power_kw` | Max. laad/ontlaadvermogen (kW) | `3.0` |
| `max_capacity` | Maximaal te simuleren capaciteit (kWh) | `20` |

> **Tips:**
> - Vink bij split-tariefmeters **alle tarieven** aan; anders is het gesimuleerde verbruik te laag.
> - Kies **kWh-totaaltellers** (state_class: total_increasing, device_class: energy), geen vermogenssensoren (W), "vandaag"-sensoren of maandelijks resettende utility_meter-helpers.
> - Gebruik consistent **één** P1-bron voor import én export (niet twee gateways door elkaar).

## Gebruik

Roep de service **`batterij_analyse.start`** aan (Hulpmiddelen voor ontwikkelaars → Acties, of via een automatisering). De analyse leest max. 365 dagen uurhistorie en vult daarna de sensoren:

- `sensor.aanbevolen_batterijcapaciteit` – aanbevolen maat (kWh), met `max_useful_kwh` en `panel_advice` als attributen
- `sensor.jaarlijkse_besparing_batterij` – netto jaarlijkse besparing (€), met `report_markdown` als attribuut
- `sensor.jaarlijks_bespaarde_energie` – vermeden afname (kWh/jaar)
- `sensor.autarkie_met_batterij` – autarkie (%)
- `sensor.terugverdientijd_batterij` – terugverdientijd (jaren)

### Dashboard-config (Lovelace)

```yaml
type: vertical-stack
cards:
  - type: markdown
    title: Thuisbatterij Analyse
    content: >
      {{ state_attr('sensor.jaarlijkse_besparing_batterij', 'report_markdown') }}
  - type: horizontal-stack
    cards:
      - type: gauge
        name: Aanbevolen maat
        entity: sensor.aanbevolen_batterijcapaciteit
        min: 0
        max: 20
        severity:
          green: 5
          yellow: 10
          red: 15
      - type: gauge
        name: Autarkie
        entity: sensor.autarkie_met_batterij
        min: 0
        max: 100
  - type: entities
    title: Businesscase
    entities:
      - sensor.jaarlijkse_besparing_batterij
      - sensor.jaarlijks_bespaarde_energie
      - sensor.terugverdientijd_batterij
      - sensor.aanbevolen_batterijcapaciteit
```

### Automatisering (wekelijkse herberekening)

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
mode: single
```

## Hoe de analyse werkt (v3)

1. **Data:** cumulatieve kWh-meterstanden uit de recorder long-term statistics (max. 365 dagen). Het verbruik per uur wordt berekend uit het verschil tussen opeenvolgende standen; teruglopende standen (sensorresets/overflows, zoals een apparaatsensor die naar duizenden kWh springt) worden genegeerd en gerapporteerd als datakwaliteit-waarschuwing in het rapport. Meerdere meters per richting (bijv. tarief 1 + 2) worden per uur bij elkaar opgeteld.
2. **Automatische detectie:** bij de configuratie worden alle kWh-totaaltellers gescand en op naam geclassificeerd (verbruik, teruglevering, opwek) en voorgeselecteerd.
3. **Simulatie:** voor elke capaciteit van 0,5 t/m het opgegeven maximum (stap 0,5 kWh) wordt uur voor uur nagebootst: de batterij laadt uit teruglevering (beperkt door vermogen en capaciteit, met éénrichtingsrendement √η) en ontlaadt tegen verbruik uit het net.
4. **Businesscase:** netto besparing = vermeden afname × stroomprijs − geladen kWh × teruglevertarief (gemiste terugleververgoeding). Terugverdientijd = investering / netto jaarbesparing.
5. **Aanbeveling:** de maat met de kortste terugverdientijd, plus de *maximale zinvolle capaciteit* (de grens waar een extra 0,5 kWh nog ≥ 25 kWh/jaar oplevert — daarboven koop je maat die je niet benut).
6. **Seizoensanalyse:** winter- vs. zomersplit van verbruik, teruglevering en opwek, zodat je ziet in welk seizoen de batterij zijn rendement haalt.
7. **Paneeladvies:** op basis van de verhouding opwek/verbruik/teruglevering wordt aangegeven of uitbreiden van de panelen zinvol is of dat de batterij de teruglevering juist opvangt, inclusief de tip om verbruik (wasmachine, droger, airco) naar zonnige uren te schuiven.

### Beperkingen

- Vast tarief (geen dynamische uurprijzen) in de berekening.
- Uurkundige resolutie; pieken korter dan een uur worden gladgestreken.
- De batterij laadt alleen uit **eigen teruglevering** (geen net-opladen).
- Zonder gekoppelde productie-meters blijft het paneeladvies beperkt.
