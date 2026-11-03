# E-Ink Views

Rendert SVG-Vorlagen in Home Assistant zu 1-Bit-PNGs für E-Ink-Displays, auf Wunsch mit eigener Rot-Ebene für dreifarbige Displays. Du legst **mehrere Ansichten** an, und Home-Assistant-Bedingungen entscheiden, welche ausgespielt wird: nach Jahreszeit, Uhrzeit oder Zustand von Entitäten. Das Display holt nur noch ein Bild über eine URL.

## Einrichtung

1. Repository in HACS als benutzerdefiniertes Repository (Kategorie Integration) hinzufügen und installieren, Home Assistant neu starten.
2. Unter **Einstellungen → Geräte & Dienste** die Integration „E-Ink Views“ hinzufügen. Pro Display ein Eintrag mit eigenem Ordner.
3. Beim ersten Start werden Beispielansichten nach `/config/eink_views/` kopiert. Bestehende Dateien werden nie überschrieben. Die Beispiele verwenden Entitäten eines bestimmten Haushalts und müssen angepasst werden.
4. Die Bild-URL steht unter **Konfigurieren** am Eintrag.

## Ansichten

`views.yaml` listet die Ansichten. **Die erste, deren Bedingungen zutreffen, wird ausgespielt**, die Reihenfolge ist also die Priorität. Unter `when` stehen normale Home-Assistant-Bedingungen. Die letzte Ansicht sollte ohne Bedingung bleiben.

```yaml
views:
  - name: abend
    when:
      - condition: time
        after: "20:00:00"
        before: "06:00:00"
  - name: pollen
    when:
      - condition: template
        value_template: "{{ now().month in [3, 4, 5, 6, 7, 8] }}"
  - name: standard
```

Jede Ansicht ist eine Datei `<name>.svg.j2`: SVG mit Home-Assistant-Templates (`states()`, `state_attr()` usw.). Gemeinsame Bausteine liegen in `_macros.svg.j2`, das vor jede Ansicht gesetzt wird. Verfügbar sind außerdem `view`, `width`, `height` und `rendered_at`.

Änderungen an den Dateien gelten sofort, ein Neuladen ist nicht nötig.

**Vorschau:** Mit `&view=name` an der Bild-URL siehst du jede Ansicht unabhängig von ihren Bedingungen.

**Schriften:** `TRMNL12`, `TRMNL16` und `TRMNL21` sind Pixelschriften und nur in ihrer Größe und ganzzahligen Vielfachen scharf. Für andere Größen nimmt das Makro `text` die Schrift `Inter`.

## Verhalten bei Fehlern

- Eine fehlerhafte Ansicht wird übersprungen, die nächste passende wird verwendet.
- Passt nichts oder ist `views.yaml` kaputt, kommt das zuletzt erfolgreiche Bild. Gibt es noch keines, antwortet der Endpunkt mit 503.
- Der Sensor **Aktive Ansicht** zeigt, welche Ansicht gerade greift, und nennt im Attribut `last_error` den letzten Fehler.

## Display (ESPHome)

```yaml
http_request:

image:
  - platform: online_image
    id: dashboard_image
    url: !secret eink_image_url
    format: PNG
    type: BINARY
    update_interval: never
```

Das Bild kommt erst beim nächsten Aufwachen auf dem Display an. Der Takt des Geräts bestimmt also, wie schnell eine neue Ansicht sichtbar wird.

### Mehrere Displays

Jeder Eintrag der Integration ist ein Display mit eigenem Ordner, eigener `views.yaml`, eigener Größe, eigener URL und eigenem Sensor **Aktive Ansicht**. Für ein zweites Display die Integration ein weiteres Mal hinzufügen und einen anderen Ordner wählen.

Damit nicht für jedes Display ein eigener Ordner im Config-Verzeichnis landet, darf der Ordner eine Ebene tiefer liegen, z. B. `eink_views/flur` und `eink_views/schreibtisch`. Eine `_macros.svg.j2` direkt in `eink_views/` gilt dann für alle Displays darunter. Die eigene `_macros.svg.j2` eines Displays wird danach geladen und kann geteilte Makros überschreiben.

```
config/eink_views/
├── _macros.svg.j2        geteilt
├── flur/                 views.yaml, eigene Makros, Ansichten
└── schreibtisch/
```

Ein bestehender Eintrag zieht über **Neu konfigurieren** in einen anderen Ordner um. Die Dateien verschiebst du selbst; Eintrag, Schlüssel und Bild-URL bleiben gleich, das Display muss also nicht neu geflasht werden.

### Schwarz, Weiß und Rot

Rot gezeichnete Flächen und Schrift (`fill="#f00"`) werden auf Wunsch als eigene Ebene ausgegeben. Der Parameter `layer` an der Bild-URL wählt sie:

| `layer` | Inhalt |
|---|---|
| `all` (Standard) | alles Dunkle, Rot zählt als Schwarz: für Schwarz-Weiß-Displays |
| `black` | Schwarz ohne Rot |
| `red` | nur Rot |

Ein Dreifarb-Display lädt erst `black`, dann `red`. Die rote Ebene stammt dabei aus demselben Rendervorgang wie die schwarze, wenn sie innerhalb von 60 Sekunden abgerufen wird. Beide Ebenen sind 1-Bit-PNGs, in denen Schwarz für „einfärben“ steht. Mit ESPHome reicht ein Bildpuffer: die schwarze Ebene laden und zeichnen, dieselbe `online_image` per `online_image.set_url` auf die rote Ebene umstellen und deren schwarze Pixel mit `draw_pixel_at(x, y, rot)` darüberlegen. Erst danach das Display aktualisieren (`auto_clear_enabled: false`).

## Sicherheit

Der Endpunkt verlangt keine Home-Assistant-Anmeldung, sondern einen eigenen Schlüssel in der URL. Er öffnet nur dieses Bild und gibt keinen Zugriff auf Home Assistant. Über unverschlüsseltes HTTP ist er aber mitlesbar, und die URL steht im Klartext in der Firmware des Geräts. Personenbezogene Daten gehören daher nur bewusst in eine Ansicht. Unter **Konfigurieren** lässt sich ein neuer Schlüssel erzeugen.

## Lizenzen

Der Code steht unter der MIT-Lizenz. Die Schriften in `fonts/` sind unverändert und stehen unter der SIL Open Font License 1.1 (siehe `OFL.txt` im jeweiligen Ordner): TRMNL von Heavyweight Digital Type Foundry, Inter von The Inter Project Authors.

Die Idee, Dashboards ohne Browser mit resvg zu rendern, und die Schriftauswahl stammen von [hass-eink-dashboard](https://github.com/cryptomilk/hass-eink-dashboard).
