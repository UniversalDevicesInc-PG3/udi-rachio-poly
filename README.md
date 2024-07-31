# Rachio-polyglot
This is the Rachio Node Server for the ISY Polyglot V3 interface.  
(c) fahrer16 aka Brian Feeney.  
MIT license. 

The Rachio water controller uses a cloud-based API that is documented here: https://rachio.readme.io/docs/getting-started.
This node server currently implements the Person, Device, and Zone leaves of the Rachio api.


# Installation Instructions:
1. Backup ISY (just in case)
1. Make sure to [Configure Webooks](https://github.com/UniversalDevicesInc/udi_python_interface/blob/master/Webhooks.md)
  * This feature is only available on eisy and polisy using PG3x.
  * PG3 remote access must be configured and active. To configure this, login to https://my.isy.io, and under you ISY, use: Select tools | Maintenance | PG3 remote access.
  * Make sure Remote access is active.
  * If events are not sent to your nodeserver, make sure you are running the latest version, and proceed with a reconfiguration of remote access.
  * Please note that configuring remote access will reboot your eisy/polisy.
1. Install from Polyglot Store
1. Set [Configuration](POLYGLOT_CONFIG.md)

Any Rachio units associated with the specified API key should now show up in the ISY, hit "Query" if the status fields are empty.  

## Polyglot Custom Configuration Parameters
* REQUIRED: Key:'api_key' Value: See "https://rachio.readme.io/v1.0/docs" for instructions on how to obtain Rachio API Key.
* REQUIRED: Key: 'host' Value: External address for polyglot server (External static IP or Dynamic DNS host name).  Not required or used for polyglot cloud.
* OPTIONAL: Key: 'port' Value: External port (integer) for polyglot server.  Note: This port must be opened through firewall and forwarded to the internal polyglot server.  Defaults to '3001' if no entry given but opening port is not optional (required for Rachio websockets).  ot required or used for polyglot cloud.
* OPTIONAL: Key:'nodeAdditionInterval' Value: On discovery, nodes will be added at this interval (in seconds).
 
## Version History:
* 2.0.0: Rewritten for Polyglot v2.
* 2.1.0: Updated to have each Rachio Device be a primary node
* 2.2.0: Added node addition queue with a default interval of 1 second and removed forced Driver reporting to improve performance in large installs.
* 2.2.1: Corrected "bool" definition in editor profile
* 2.3.0: Simplified driver update logic
* 2.3.1: Corrected bugs relating to setting Rain Delay and Starting Zone
* 2.3.2: Bug fix for zone start log message
* 2.3.3: Bug fixes for schedule durations and season adjustment commands
* 2.4.0: Updated to accommodate changes in Rachio Cloud API.  Added websocket support and caching to minimize API calls.  Removed drivers for "time until next schedule run" because required info was removed from Rachio API.
* 2.4.1: Corrected bug where error is generated if 'port' configuration parameter not defined.  Added closure of server.json file.
* 2.4.2: Corrected bug on setting controller active zone when watering.  Removed http server response to invalid requests.
* 3.0.0: First pass at incorporation of polyglot cloud capability
* 3.0.1: Updated reference to rachiopy project to force usage of older version
* 3.0.2: Removed init on start command per pull request due to compatability with UD Mobile App
