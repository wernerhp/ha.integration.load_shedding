# Load Shedding

A Home Assistant integration to track your load schedding schedule.

# Manual Install
1. Download and unzip to your Home Assistant `config/custom_components` folder.  
![image](https://user-images.githubusercontent.com/2578772/164681660-57d56fc4-4713-4be5-9ef1-bf2f7cf96b64.png)
3. Restart Home Assistant.
4. Go to Settings > Devices & Services > + Add Integration
5. Search for 'Load Shedding' and follow the config flow.
6. If you're coming from a previous version of this integration, you may need to delete the `.json` files in `/config/.cache`.  
![image](https://user-images.githubusercontent.com/2578772/164681929-e3afc6ea-5821-4ac5-8fa8-eee04c819eb6.png)

# To Do:
1. Add to HACS for HACS install
2. Add time until attribute

# Cards
I created this card with the help of [template-entity-row](https://github.com/thomasloven/lovelace-template-entity-row)  
![image](https://user-images.githubusercontent.com/2578772/164682124-ef4d02c0-a041-4295-860e-429f85f4265f.png)
<details>
  <summary>Code</summary>
  
```yaml
type: entities
entities:
  - entity: sensor.load_shedding_milnerton
  - type: custom:template-entity-row
    icon: mdi:timer-outline
    name: Next Start
    state: >-
      {{ state_attr('sensor.load_shedding_milnerton', 'next_start') |
      as_datetime | as_local }}
  - type: custom:template-entity-row
    icon: mdi:timer-sand
    name: Time Until
    state: >-
      {{ state_attr('sensor.load_shedding_milnerton', 'next_start') |
      as_datetime - now().strftime('%Y-%m-%d %H:%M%z') | as_datetime }}
  - entity: automation.load_shedding_last_rounds
    name: 15min Warning
    icon: mdi:bullhorn-outline
```
  </details>

# Automation Ideas

### Announce Load Shedding stage changes on speakers and push notifications.
<details>
  <summary>Code</summary>
  
```yaml
alias: Load Shedding
description: ''
trigger:
  - platform: template
    value_template: '{{ states.sensor.load_shedding_milnerton.state }}'
condition: []
action:
  - choose:
      - conditions:
          - condition: time
            after: input_datetime.sleep
            before: '23:59:59'
          - condition: time
            after: '00:00:00'
            before: input_datetime.wake
        sequence:
          - wait_for_trigger:
              - platform: time
                at: input_datetime.wake
            continue_on_timeout: false
    default: []
  - service: notify.mobile_app_YOUR_PHONE
    data:
      title: Load Shedding
      message: '{{ states.sensor.load_shedding_milnerton.state }}'
  - service: tts.home_assistant_say
    data:
      entity_id: media_player.assistant_speakers
      cache: true
      message: >-
        {% if is_state("sensor.load_shedding_milnerton", "No Load Shedding") %}
        Load Shedding suspended {% else %} Load Shedding {{
        states.sensor.load_shedding_milnerton.state }} {% endif %}
mode: single
```
  </details>
  
### 15 minutes warning before load shedding starts.
This sends a telegram message, announces on speakers and updates my slack status.
<details>
  <summary>Code</summary>
  
```yaml
alias: Load Shedding (Warning)
description: ''
trigger:
  - platform: template
    value_template: >-
      {{ state_attr('sensor.load_shedding_milnerton', 'next_start') |
      as_datetime - now().strftime('%Y-%m-%d %H:%M%z') | as_datetime ==
      timedelta(minutes=15) }}
condition:
  - condition: time
    after: input_datetime.alarm
    before: input_datetime.sleep
action:
  - service: telegram_bot.send_message
    data:
      message: Load Shedding starts in 15 minutes.
      title: Load Shedding
  - service: media_player.volume_set
    data:
      volume_level: 0.7
    target:
      device_id: SPEAKER_DEVICE_ID
  - service: tts.home_assistant_say
    data:
      entity_id: media_player.assistant_speakers
      message: Load Shedding starts in 15 minutes.
      cache: true
  - delay:
      hours: 0
      minutes: 15
      seconds: 0
      milliseconds: 0
  - service: rest_command.slack_status
    data:
      emoji: ':loadsheddingtransparent:'
      status: >-
        Load Shedding until {{
        (state_attr('sensor.load_shedding_milnerton','next_end') | as_datetime |
        as_local).strftime('%H:%M (%Z)') }}
mode: single
```
</details>

<details>
  <summary>Slack Code</summary>
  
```yaml
slack_status:
  url: https://slack.com/api/users.profile.set
  method: POST
  headers:
    authorization: Bearer !secret slack_token
    accept: "application/json, text/html"
  payload: '{"profile":{"status_text": "{{ status }}","status_emoji": "{{ emoji }}"}}'
  content_type: "application/json; charset=utf-8"
  verify_ssl: true
```
</details>
    
### Dim lights or turn off devices before load shedding and turn them back on afterwards.
