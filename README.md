# Load Shedding

A Home Assistant integration to track your load schedding schedule.

> ℹ️ **_NOTE:_**  This integration makes use of [this Python library](https://gitlab.com/wernerhp/load-shedding) which only supports schedules for Eskom Direct customers.  If you can find your schedule on https://loadshedding.eskom.co.za/ then you'll have schedule info available.  
> If you are not an Eskom Direct customer, then a work-around is to find an Eskom Direct schedule which matches yours and use that instead.  There are no immediate plans to add other municipalities, but Merge Requests on [the library](https://gitlab.com/wernerhp/load-shedding) to expand support are welcome.

![img_3.png](img_3.png)

# HACS
[![hacs_badge](https://img.shields.io/badge/HACS-Default-41BDF5.svg)](https://github.com/hacs/integration)
1. Go to HACS Integrations on your Home Assitant instance
2. Select "+ Explore & Download Repositories" and search for "Load Shedding"
3. Select "Load Shedding" and "Download this repository with HACS"
![image](https://user-images.githubusercontent.com/2578772/167293308-d3ef2131-bc71-431e-a1ff-6e02f02af000.png)
4. Once downloaded, click the "My Integrations" button to configure the integration.  
[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=load_shedding)
5. Setup cards and automations
6. If you find this integration useful, please consider buying me a coffee.

<a href="https://www.buymeacoffee.com/wernerhp" target="_blank"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" alt="Buy Me A Coffee" style="height: auto !important;width: auto !important;" ></a> 

![img_9.png](img_9.png)  
Bitcoin: 3EGnQKKbF6AijqW9unyBuW8YeEscY5wMSE

# Manual Install
<details>
<summary>Expand</summary>

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
  
![img_7.png](img_7.png)
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
> Since the schedules differ depending on the Stage, the correct `start_time`, `end_time`, `starts_in`, `ends_in` and `schedule` times only show once there is an active Stage as it needs to know which stage to query.  When there is No Load Shedding the Stage 1 schedule will be shown.

<details>
  <summary>Screenshot</summary>

| ![img_5.png](img_5.png) | ![img_4.png](img_4.png) | 

![img_6.png](img_6.png)

  </details>

# Cards
I created this card with the help of [template-entity-row](https://github.com/thomasloven/lovelace-template-entity-row)  
<details>
  <summary>Screenshot</summary>

![img.png](img.png)

  </details>
<details>
  <summary>Code</summary>
  
```yaml
type: entities
entities:
  - type: custom:template-entity-row
    icon: mdi:lightning-bolt-outline
    name: Status
    entity: sensor.load_shedding_stage
    active: '{{ not is_state("sensor.load_shedding_stage", "No Load Shedding") }}'
    state: '{{states("sensor.load_shedding_stage")}}'
  - type: custom:template-entity-row
    icon: mdi:timer-outline
    name: Milnerton
    active: '{{ states("sensor.load_shedding_milnerton") == "on" }}'
    state: >-
      {{ (state_attr("sensor.load_shedding_milnerton", "start_time") |
      as_datetime | as_local).strftime("%H:%M") }}  -  {{
      (state_attr("sensor.load_shedding_milnerton", "end_time") | as_datetime |
      as_local).strftime("%H:%M") }}
    secondary: >-
      {% if states("sensor.load_shedding_milnerton") == "off" %}  
      Starts in {{ timedelta(seconds=state_attr("sensor.load_shedding_milnerton", "starts_in")) }}
      {% else %} 
      Ends in {{ timedelta(seconds=state_attr("sensor.load_shedding_milnerton", "ends_in")) }} 
      {% endif %}
    entity: sensor.load_shedding_milnerton
```
  </details>

# Automation Ideas
These are just some automations I've got set up.  They are not perfect and will require some tweaking on your end.  Feel free to contribute your automations ideas and custom panels by posting them on [this Issue thread](https://github.com/wernerhp/ha_integration_load_shedding/issues/5)

### Announce Load Shedding stage changes on speakers and push notifications.
<details>
  <summary>Code</summary>
  
```yaml
alias: Load Shedding (Stage)
description: ''
trigger:
  - platform: state
    entity_id:
      - sensor.load_shedding_stage
    for:
      hours: 0
      minutes: 0
      seconds: 0
condition: []
action:
  - choose:
      - conditions:
          - condition: time
            after: input_datetime.sleep
            weekday:
              - mon
              - tue
              - wed
              - thu
              - fri
              - sat
              - sun
          - condition: time
            before: input_datetime.wake
            weekday:
              - sun
              - sat
              - fri
              - thu
              - wed
              - tue
              - mon
        sequence:
          - wait_for_trigger:
              - platform: time
                at: input_datetime.wake
            continue_on_timeout: false
    default: []
  - service: notify.mobile_app_nokia_8_sirocco
    data:
      title: Load Shedding
      message: '{{ states.sensor.load_shedding_stage.state }}'
  - service: tts.home_assistant_say
    data:
      entity_id: media_player.assistant_speakers
      cache: true
      message: >-
        {% if is_state("sensor.load_shedding_stage", "No Load Shedding") %} Load
        Shedding suspended {% else %} Load Shedding {{
        states.sensor.load_shedding_stage.state }} {% endif %}
mode: single
```
  </details>
  
### 15 minutes warning on speaker and telegram before load shedding starts.
<details>
  <summary>Code</summary>
  
```yaml
alias: Load Shedding (Warning)
description: ''
trigger:
  - platform: template
    value_template: >-
      {{ timedelta(seconds=state_attr("sensor.load_shedding_milnerton", "starts_in")) == timedelta(minutes=15) }}
condition:
  - condition: and
    conditions:
      - condition: time
        after: input_datetime.alarm
        before: input_datetime.sleep
      - condition: not
        conditions:
          - condition: state
            entity_id: sensor.load_shedding_stage
            state: Unknown
          - condition: state
            entity_id: sensor.load_shedding_stage
            state: No Load Shedding
action:
  - service: telegram_bot.send_message
    data:
      message: Load Shedding starts in 15 minutes.
      title: Load Shedding
  - service: media_player.volume_set
    data:
      volume_level: 0.7
    target:
      entity_id: media_player.assistant_speakers
  - service: tts.home_assistant_say
    data:
      entity_id: media_player.assistant_speakers
      message: Load Shedding starts in 15 minutes.
      cache: true
mode: single
```
</details>

    
### Dim lights or turn off devices before load shedding and turn them back on afterwards.

### Update your Slack status

Setup a REST Command and two automations to set your Slack status when Load Shedding starts and ends.

<details>
  <summary>Code</summary>
  
`secrets.yaml`
```yaml
slack_token: Bearer xoxp-XXXXXXXXXX-XXXXXXXXXXXX-XXXXXXXXXXXXX-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```  
  
  [rest_command](https://www.home-assistant.io/integrations/rest_command/)
  
```yaml
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

<details>
  <summary>Code</summary>
  
```yaml
alias: Load Shedding (Start)
description: ''
trigger:
  - platform: state
    entity_id:
      - sensor.load_shedding_milnerton
    to: 'on'
    from: 'off'
condition:
  - condition: not
    conditions:
      - condition: state
        entity_id: sensor.load_shedding_stage
        state: Unknown
      - condition: state
        entity_id: sensor.load_shedding_stage
        state: No Load Shedding
action:
  - service: rest_command.slack_status
    data:
      emoji: ':loadsheddingtransparent:'
      status: >-
        Load Shedding until {{
        (state_attr('sensor.load_shedding_milnerton','end_time') | as_datetime |
        as_local).strftime('%H:%M (%Z)') }}
mode: single
```
</details>

<details>
  <summary>Code</summary>
  
```yaml
alias: Load Shedding (End)
description: ''
trigger:
  - platform: state
    entity_id:
      - sensor.load_shedding_stage
    from: 'on'
    to: 'off'
condition:
  - condition: not
    conditions:
      - condition: state
        entity_id: sensor.load_shedding_stage
        state: Unknown
      - condition: state
        entity_id: sensor.load_shedding_stage
        state: No Load Shedding
action:
  - service: rest_command.slack_status
    data:
      emoji: ':speech_balloon:'
      status: is typing...
mode: single
```
</details>
