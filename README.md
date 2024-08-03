# Rachio-polyglot
This is the Rachio Node Server for the ISY Polyglot V3 interface.  
(c) fahrer16 aka Brian Feeney.  
MIT license. 

The Rachio water controller uses a cloud-based API that is documented here: https://rachio.readme.io/docs/getting-started.
This node server currently implements the Person, Device, and Zone leaves of the Rachio api.


# Installation Instructions:
1. Backup ISY (just in case)
1. Install from Polyglot Store
1. Set [Configuration](POLYGLOT_CONFIG.md) params

## Polyglot Custom Configuration Parameters
See [Configuration](POLYGLOT_CONFIG.md)

## TODO
* Parse change json to determine updates instead of query
  * Currently it just sees what device changed, and requeries that device which probably annoy's the rachio servers.
* Stop querying status of all devices on longPoll.

## Version History:
IMPORTANT: You must enable PG3 remote access as detailed in [Configuration](POLYGLOT_CONFIG.md)
* 5.0.0: With original Authors permissing, taken over by JimBo.Automates
  * First release of Standard Perpetual License for $20
  * Use Portal Webhooks instead of needing to open up a local port
  * General code cleanup and reorganization
* 4.0.0-4.0.4: Updated for Polyglot v3 by Bob Paauwe @bpaauwe
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
