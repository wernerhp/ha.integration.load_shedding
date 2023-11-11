# Load Shedding [![hacs_badge](https://img.shields.io/badge/HACS-Default-41BDF5.svg)](https://github.com/hacs/integration)

A Home Assistant integration to track your load schedding schedule.

<img src="img/preview.png" width="auto" height="auto"/>


>💡This integration uses the Eskom SePush API.  
>🚨Read the [EskomSePush API Licence Agreement](https://esp.info/license-agreement).  
>🔑Get a Free (50 requests per day) API Key from [Eskom Se Push](https://eskomsepush.gumroad.com/l/api).  You can pay for a higher limit.  
>⚠️Do not use more than one API key from the same IP.  Your key will be blocked.

# HACS Install 
1. Go to **HACS Integrations** on your Home Assitant instance
2. Select "+ **Explore & Download Repositories**" and search for "**Load Shedding**"
3. Select **Load Shedding: A Home assistant integration to track your load shedding schedule.** and **Download this repository with HACS**
![image](https://user-images.githubusercontent.com/2578772/167293308-d3ef2131-bc71-431e-a1ff-6e02f02af000.png)
4. Once downloaded, click the **My Integrations** button to configure the integration.  
[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=load_shedding)
5. Setup cards and automations
6. Please [support my work](https://github.com/wernerhp/ha.integration.load_shedding/blob/master/README.md#support)

# Support 
If you find this integration useful, please consider supporting my work by [buying me a coffee](https://www.buymeacoffee.com/wernerhp) or making a donation in the form of Bitcoin.


### Buy me a coffee
<a href="https://www.buymeacoffee.com/wernerhp" target="_blank"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" alt="Buy Me A Coffee" style="height: auto !important;width: auto !important;" ></a>

Sign-up for a free Luno wallet using [this invite link](http://www.luno.com/invite/X48WY) or enter the code **X48WY** in the **Rewards** section and we can both earn **R 25.00 free BTC** after investing our first R 500.

### Bitcoin
`3EGnQKKbF6AijqW9unyBuW8YeEscY5wMSE`  
<img width="200" alt="Bitcoin address: 3EGnQKKbF6AijqW9unyBuW8YeEscY5wMSE" src="img/img_9.png">


# Manual Install
<details>
<summary>Instructions</summary>

1. Download and unzip to your Home Assistant `config/custom_components` folder.
  <details>
  <summary>Screenshot</summary>
  
![image](https://user-images.githubusercontent.com/2578772/164681660-57d56fc4-4713-4be5-9ef1-bf2f7cf96b64.png)
  </details>
  
2. Restart Home Assistant.
3. Go to Settings > Devices & Services > + Add Integration

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=load_shedding)

5. Search for 'Load Shedding' and follow the config flow.
<details>
<summary>Screenshot</summary>
  
<img src="img/img_7.png" width="auto" height="auto"/>
  </details>

6. If you're coming from a previous version of this integration, you may need to delete the `.json` files in `/config/.cache`.
<details>
  <summary>Screenshot</summary>
  
![image](https://user-images.githubusercontent.com/2578772/164681929-e3afc6ea-5821-4ac5-8fa8-eee04c819eb6.png)
  </details>
</details>

# Sensor
The load shedding sensor State will always reflect the current load shedding stage.  
i.e When load shedding is suspended, it will show **No Load Shedding**.  When Stage 2 is active, it will show **Stage 2**.

<details>
  <summary>Screenshot</summary>

| <img src="img/img_5.png" width="auto" height="auto"/> | <img src="img/img_4.png" width="auto" height="auto"/> | 

<img src="img/img_6.png" width="auto" height="auto"/>

  </details>

# Cards

## Mushroom Chips
- [Mushroom](https://github.com/piitaya/lovelace-mushroom)

- [Code](examples/dashboards/mushroom_chips.yaml)  

<img src="img/mushroom_chips.png" width="auto" height="auto"/>


## Status Alert
- [Markdown Card](https://www.home-assistant.io/dashboards/markdown/)

- [Code](examples/dashboards/status_alert.yaml)  

<img src="img/status_alert.png" width="auto" height="auto"/>

## Calendar

- [Atomic Calendar Revive](https://github.com/totaldebug/atomic-calendar-revive)

- [Code](examples/dashboards/calendar.yaml)

<img src="img/calendar.png" width="auto" height="auto"/>

## ESP Status Bar
Thanks to @ribeirompl for this [contribution](https://github.com/wernerhp/ha.integration.load_shedding/issues/72#issuecomment-1712458448)

- [Lovelace HTML Jinja2 Template card](https://github.com/PiotrMachowski/Home-Assistant-Lovelace-HTML-Jinja2-Template-card)

- [Code](examples/dashboards/esp_status_bar.yaml)  

<img src="img/esp_status_bar.png" width="auto" height="auto"/>

# Automation Ideas
These are just some automations I've got set up.  They are not perfect and will require some tweaking on your end.    
Replace `sensor.load_shedding_south_africa_stage`, `sensor.load_shedding_milnerton_14` and other `entity_id` with your own.

## Load Shedding Stage
Announce Load Shedding stage changes on speakers and push notifications.
- [Load Shedding (Stage)](examples/automations/load_shedding_stage.yaml)

## Load Shedding Start/End
Do stuff when load shedding starts, e.g. update your slack status, turn off lights, etc.
- [Load Shedding (Start/End)](examples/automations/load_shedding_start_end.yaml)

### Slack Status

Setup a [REST Command](https://www.home-assistant.io/integrations/rest_command/) and two automations to set your Slack status when Load Shedding starts and ends.
<details>
<summary>Example</summary>

`secrets.yaml`
```yaml
slack_token: Bearer xoxp-XXXXXXXXXX-XXXXXXXXXXXX-XXXXXXXXXXXXX-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```  
`configuration.yaml`
```yaml
rest_command: 
    slack_status:
      url: https://slack.com/api/users.profile.set
      method: POST
      headers:
        authorization: !secret slack_token
        accept: "application/json, text/html"
      payload: '{"profile":{"status_text": "{{ status }}","status_emoji": "{{ emoji }}"}}'
      content_type: "application/json; charset=utf-8"
      verify_ssl: true
```

</details>


## Load Shedding Warning (15 min)
15 minutes warning on speaker and telegram before load shedding starts.
- [Load Shedding (Warning)](examples/automations/load_shedding_warning.yaml)

## Load Shedding Warning (2 hr)
2 hour warning on smart speaker
- [Load Shedding (Warning) (2hr)](examples/automations/load_shedding_warning_2hr.yaml)

## Load Shedding Reload
Reload the integration every night.  This is a workaround for Issue #70/#71
- [Load Shedding Reload](examples/automations/load_shedding_reload.yaml)
