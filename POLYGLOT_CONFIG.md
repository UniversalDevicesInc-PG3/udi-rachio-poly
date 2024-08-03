## Configuration
* REQUIRED: Key:'api_key' Value: See [Rachio API Key](https://rachio.readme.io/reference/authentication) for instructions on how to obtain Rachio API Key.
* OPTIONAL: Key:'nodeAdditionInterval' Value: On discovery, nodes will be added at this interval (in seconds).

* Make sure to [Configure Webooks](https://github.com/UniversalDevicesInc/udi_python_interface/blob/master/Webhooks.md)
  * This feature is only available on eisy and polisy using PG3x.
  * PG3 remote access must be configured and active. To configure this, login to https://my.isy.io, and under your ISY, use: Select tools | Maintenance | PG3 remote access.
  * Make sure Remote access is active.
  * If events are not sent to your nodeserver, make sure you are running the latest version, and proceed with a reconfiguration of remote access.
  * Please note that configuring remote access will reboot your eisy/polisy.

Additional notes available on the [github page](https://github.com/UniversalDevicesInc-PG3/udi-rachio-poly/blob/master/README.md)
