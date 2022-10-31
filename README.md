# Load Shedding [![hacs_badge](https://img.shields.io/badge/HACS-Default-41BDF5.svg)](https://github.com/hacs/integration)

A Home Assistant integration to track your load schedding schedule.

![img_8.png](img_8.png)

> ℹ️ **_NOTE:_**  Prior to v1.0.0 this integration made use of [this Python library](https://gitlab.com/wernerhp/load-shedding) which only supports schedules for Eskom Direct customers.  If you can find your schedule on https://loadshedding.eskom.co.za/ then you'll have schedule info available.  
> If you are not an Eskom Direct customer, then a work-around is to find an Eskom Direct schedule which matches yours and use that instead.  There are no immediate plans to add other municipalities, but Merge Requests on [the library](https://gitlab.com/wernerhp/load-shedding) to expand support are welcome.

>  v1.0.0 uses the Eskom SePush API.  Get a Free (50 requests per day) API Key from [Eskom Se Push](https://eskomsepush.gumroad.com/l/api).  You can also pay to get a higher request limit.

# HACS Install 
1. Go to HACS Integrations on your Home Assitant instance
2. Select "+ Explore & Download Repositories" and search for "Load Shedding"
3. Select "Load Shedding" and "Download this repository with HACS"
![image](https://user-images.githubusercontent.com/2578772/167293308-d3ef2131-bc71-431e-a1ff-6e02f02af000.png)
4. Once downloaded, click the "My Integrations" button to configure the integration.  
[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=load_shedding)
5. Setup cards and automations
6. [Support](https://github.com/wernerhp/ha.integration.load_shedding/blob/master/README.md#support)

# Support 
If you find this integration useful, please consider supporting my work by [buying me a coffee](https://www.buymeacoffee.com/wernerhp) or making a donation in the form of Bitcoin.

<a href="https://www.buymeacoffee.com/wernerhp" target="_blank"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" alt="Buy Me A Coffee" style="height: auto !important;width: auto !important;" ></a>

Sign-up for a free Luno wallet using [this invite link](http://www.luno.com/invite/X48WY) or enter the code **X48WY** in the **Rewards** section and we can both earn **R 25.00 free BTC** after investing our first R 500.

**Bitcoin** `3EGnQKKbF6AijqW9unyBuW8YeEscY5wMSE`

![](img_9.png)

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

<details>
  <summary>Screenshot</summary>

| ![img_5.png](img_5.png) | ![img_4.png](img_4.png) | 

![img_6.png](img_6.png)

  </details>

# Cards
I created this card with the help of [template-entity-row](https://github.com/thomasloven/lovelace-template-entity-row)  
<details>
  <summary>Card 1</summary>

[Code](examples/card1.yaml)  
![img.png](img.png)
</details>

<details>
  <summary>Card 2</summary>

[Code](examples/card2.yaml)  
![img_1.png](img_1.png)
</details>

<details>
  <summary>Card 3</summary>

[Code](examples/card3.yaml)  
![img_2.png](img_2.png)  
</details>


# Automation Ideas
These are just some automations I've got set up.  They are not perfect and will require some tweaking on your end.    
Replace `sensor.load_shedding_south_africa_stage`, `sensor.load_shedding_milnerton_14` and other `entity_id` with your own.

### Announce Load Shedding stage changes on speakers and push notifications.
- [Load Shedding (Stage)](examples/automation1.yaml)
  
### 15 minutes warning on speaker and telegram before load shedding starts.
- [Load Shedding (Warning)](examples/automation2.yaml)

### 2 hour warning on speaker
- [Load Shedding (Warning) (2hr)](examples/automation3.yaml)

### Update your Slack status

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
- [Load Shedding (Start)](examples/automation3.yaml)  
- [Load Shedding (End)](examples/automation4.yaml)
</details>