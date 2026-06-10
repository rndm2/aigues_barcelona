# Aigües de Barcelona per a Home Assistant

Integració personalitzada de Home Assistant per importar dades de consum d’aigua d’Aigües de Barcelona.

[![Afegeix la integració](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start?domain=aigues_barcelona)

## Funcionalitats

- Sensor d’aigua per a cada contracte configurat.
- Estadístiques de llarg termini compatibles amb el panell d’Energia de Home Assistant.
- Importació històrica opcional.
- Servei manual per tornar a importar dades històriques.
- Interval de consulta configurable en segons.

## Requisits

Necessites:

- Usuari DNI/NIE d’Aigües de Barcelona.
- Contrasenya d’Aigües de Barcelona.
- Clau API de 2Captcha.

Aigües de Barcelona protegeix l’inici de sessió amb reCAPTCHA. Aquesta integració fa servir la clau API de 2Captcha durant l’inici de sessió. El token `ofexTokenJwt` retornat es desa a l’entrada de configuració de Home Assistant i es renova quan cal.

## Instal·lació amb HACS

1. Obre HACS.
2. Obre el menú dels tres punts.
3. Tria **Repositoris personalitzats**.
4. Afegeix l’URL d’aquest repositori.
5. Selecciona la categoria **Integració**.
6. Instal·la **Aigües de Barcelona**.
7. Reinicia Home Assistant.
8. Afegeix la integració des de **Configuració → Dispositius i serveis → Afegeix una integració**.

## Instal·lació manual

Copia aquesta carpeta:

```text
custom_components/aigues_barcelona
```

a:

```text
/config/custom_components/aigues_barcelona
```

Després reinicia Home Assistant.

## Configuració

Afegeix la integració des de Home Assistant:

```text
Configuració → Dispositius i serveis → Afegeix una integració → Aigües de Barcelona
```

Introdueix:

- Usuari DNI/NIE.
- Contrasenya d’Aigües de Barcelona.
- Clau API de 2Captcha.

## Opcions

Obre les opcions de la integració per configurar:

- `should_import_history`: importa dades històriques en la propera actualització.
- `history_days`: quants dies històrics s’han d’importar.
- `scan_period`: interval de consulta en segons. Valor per defecte: `3900` segons.

L’interval de consulta per defecte és conservador expressament per no sobrecarregar el servei extern.

## Serveis

### `aigues_barcelona.import_historical_data`

Importa dades històriques sense esborrar les estadístiques existents.

Camps:

- `contract`: opcional quan només hi ha un contracte configurat; obligatori quan n’hi ha més d’un.
- `history_days`: nombre de dies que s’han d’importar. Valor per defecte: `365`.

Exemple:

```yaml
action: aigues_barcelona.import_historical_data
data:
  history_days: 30
```

Amb diversos contractes:

```yaml
action: aigues_barcelona.import_historical_data
data:
  contract: "123456789"
  history_days: 30
```

### `aigues_barcelona.reset_and_refresh_data`

Àlies antic mantingut per compatibilitat.

No esborra les estadístiques. Només importa dades històriques.

## Comportament de la importació històrica

La importació històrica és deliberadament conservadora:

- Importa setmana a setmana.
- Reintenta fins a cinc vegades les setmanes que fallen.
- Omet les estadístiques diàries ja existents per evitar duplicats.
- Després de la importació automàtica a l’arrencada, `should_import_history` torna a `false`.

## Estructura del repositori

```text
custom_components/aigues_barcelona/  # Integració de Home Assistant
brand/                               # Recursos de marca per a HACS/Home Assistant
hacs.json                            # Metadades de HACS
README.md                            # Documentació renderitzada per HACS
LICENSE                              # Llicència GPL-3.0
```

## Notes

Aquesta integració depèn de l’API web privada d’Aigües de Barcelona. Pot deixar de funcionar si el proveïdor canvia el flux d’inici de sessió, el format del token, el tractament de reCAPTCHA o els endpoints de consum.

## Llicència

GPL-3.0.
