# Load Shedding

A Home Assistant integration to track your load schedding schedule.

> ℹ️ **_NOTE:_**  This integration makes use of the Eskom SePush API.  An API Key is required, which you can request from [here](https://docs.google.com/forms/d/e/1FAIpQLSeZhAkhDaQX_mLT2xn41TkVjLkOH3Py3YWHi_UqQP4niOY01g/viewform).  Select '< 50' requests and 'data serialization' for the Test

>  **_TODO:_**  Update the REAMDE


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
      {{ (state_attr("sensor.load_shedding_milnerton", "start_time") | as_datetime | as_local).strftime("%H:%M") }}  -  {{ (state_attr("sensor.load_shedding_milnerton", "end_time") | as_datetime | as_local).strftime("%H:%M") }}
    secondary: >-
      {% if states("sensor.load_shedding_milnerton") == "off" %}
      Starts in {{ timedelta(minutes=state_attr("sensor.load_shedding_milnerton", "starts_in")) }}
      {% else %} 
      Ends in {{ timedelta(minutes=state_attr("sensor.load_shedding_milnerton", "ends_in")) }}
      {% endif %}
    entity: sensor.load_shedding_milnerton
```

![img_1.png](img_1.png)

```yaml
type: markdown
entity_ids: 
  - sensor.load_shedding_south_africa_stage
  - sensor.load_shedding_milnerton_14
content: >-
  {% set stage_sensor = "sensor.load_shedding_south_africa_stage" %}
  {% set area_sensor = "sensor.load_shedding_milnerton_14" %}

  {% set start_time = state_attr(stage_sensor, "start_time") %}  
  {% set end_time = state_attr(stage_sensor, "end_time") %}

  {% set area_schedule = state_attr(area_sensor, "forecast") %}
  {% if area_schedule %}
    {% set start_time = area_schedule[0].start_time %}
    {% set end_time = area_schedule[0].end_time %}
    
    {% if is_state(area_sensor, "off") %}
      {% set starts_in = timedelta(minutes=state_attr(area_sensor, "starts_in")) %}
      {% if is_state_attr(stage_sensor, "stage", 0) or starts_in.seconds > 86400  %}
        <ha-alert alert-type="success">{{ states(stage_sensor) }}</ha-alert>
      {% elif not is_state_attr(stage_sensor, "stage", 0) and 0 < starts_in.seconds <= 86400 %}
        <ha-alert alert-type="warning">Load Shedding starts in {{ starts_in.seconds // 3600 }}h{{ (starts_in.seconds // 60) - (starts_in.seconds // 3600 * 60) }}m ({{ as_timestamp(start_time) | timestamp_custom("%H:%M", True) }})</ha-alert>
      {% endif %}
    {% else %}
      {% set ends_in = timedelta(minutes=state_attr(area_sensor, "ends_in")) %}
      {% if is_state_attr(stage_sensor, "stage", 0) or ends_in.seconds > 86400 %}
        <ha-alert alert-type="success">{{ states(stage_sensor) }}</ha-alert>
      {% elif not is_state_attr(stage_sensor, "stage", 0) and 0 < ends_in.seconds <= 86400 %}
        <ha-alert alert-type="error">Load Shedding ends in {{ ends_in.seconds // 3600 }}h{{ (ends_in.seconds // 60) - (ends_in.seconds // 3600 * 60) }}m  ({{ as_timestamp(end_time) | timestamp_custom("%H:%M", True) }})</ha-alert>
      {% endif %}
    {% endif %}
  {% endif %}


  {% set area_forecast = state_attr(area_sensor, "forecast" )%}
  {% if area_forecast %}
  <table width="100%"  border=0>
    <tbody>
    <tr>
      <td width="34px"><ha-icon icon="mdi:calendar"></ha-icon></td>
      <td align="left" colspan=3>Forecast : :  {{ state_attr(area_sensor, "friendly_name") }}</td>
    </tr>
    {% for forecast in area_forecast[:3] %}
    <tr>
      <td></td>
      <td align="left">
      {{ as_timestamp(forecast.start_time) | timestamp_custom("%-d %B", True) }}
      </td>
      <td align="left">
      {{ as_timestamp(forecast.start_time) | timestamp_custom("%H:%M", True) }} - {{ as_timestamp(forecast.end_time) | timestamp_custom("%H:%M", True) }}
      </td>
      <td align="right">Stage {{ forecast.stage }}</td>
    </tr>
    {% endfor %}
    </tbody>
  </table>
  {% endif %}


  {% set area_schedule = state_attr(area_sensor, "schedule" )%}
  {% if area_schedule %}
  <table width="100%"  border=0>
    <tbody>
    <tr>
      <td width="34px"><ha-icon icon="mdi:calendar"></ha-icon></td>
      <td align="left" colspan=3>Schedule : : {{ state_attr(area_sensor, "friendly_name") }}</td>
    </tr>
    {% for slot in area_schedule[:3] %}
    <tr>
      <td></td>
      <td align="left">
      {{ as_timestamp(slot.start_time) | timestamp_custom("%-d %B", True) }}
      </td>
      <td align="left">
      {{ as_timestamp(slot.start_time) | timestamp_custom("%H:%M", True) }} - {{ as_timestamp(slot.end_time) | timestamp_custom("%H:%M", True) }}
      </td>
      <td align="right">Stage {{ slot.stage }}</td>
    </tr>
    {% endfor %}
    </tbody>
  </table>
  {% endif %}
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
condition:
  - condition: template
    value_template: >-
      {{ trigger.from_state.state != 'unavailable' and trigger.to_state.state != 'unavailable' }}
action:
  - choose:
      - conditions:
          - condition: or
            conditions:
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
    enabled: false
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
      {{ timedelta(minutes=(state_attr("sensor.load_shedding_milnerton", "starts_in"))) == timedelta(minutes=15) }}
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
