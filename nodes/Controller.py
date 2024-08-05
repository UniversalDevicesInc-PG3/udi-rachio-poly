
from udi_interface import Node,LOGGER,Custom
from nodes import VERSION,RachioController
import json, time, random, pprint
from datetime import datetime
import http.client
from threading import Timer #Added version 2.2.0 for node addition queue
from rachiopy import Rachio

# {'id': 5, 'name': 'DEVICE_STATUS_EVENT', 'type': 'WEBHOOK'}, 
# {'id': 6, 'name': 'RAIN_DELAY_EVENT', 'type': 'WEBHOOK'}, 
# {'id': 7, 'name': 'WEATHER_INTELLIGENCE_EVENT', 'type': 'WEBHOOK'}, 
# {'id': 8, 'name': 'WATER_BUDGET', 'type': 'WEBHOOK'}, 
# {'id': 9, 'name': 'SCHEDULE_STATUS_EVENT', 'type': 'WEBHOOK'}, 
# {'id': 10, 'name': 'ZONE_STATUS_EVENT', 'type': 'WEBHOOK'}, 
# {'id': 11, 'name': 'RAIN_SENSOR_DETECTION_EVENT', 'type': 'WEBHOOK'}, 
# {'id': 12, 'name': 'ZONE_DELTA', 'type': 'WEBHOOK'}, 
# {'id': 14, 'name': 'DELTA', 'type': 'WEBHOOK'}

class Controller(Node):
    def __init__(self, polyglot, primary, address, name):
        super().__init__(polyglot, primary, address, name)
        self.name = 'Rachio Bridge'
        self.bridge_address = address
        self.random = random.random()
        self.poly = polyglot
        #Queue for nodes to be added in order to prevent a flood of nodes from being created on discovery.  Added version 2.2.0
        self.nodeQueue = {}
        _msg = "Connection timer created for node addition queue"
        self.timer = Timer(1,LOGGER.debug,[_msg])
        self.nodeAdditionInterval = 1
        self.port = 3001
        self.httpHost = ''
        self.device_id = ''
        self.use_ssl = False
        self.wsConnectivityTestRequired = True
        self.nsinfo = None
        self.configure_webhook_st = False
        self.discover_st = None
        self.errors = 0
        self.api_errors = 0

        self.Params      = Custom(polyglot, 'customparams')
        polyglot.subscribe(polyglot.START, self.start, address)
        polyglot.subscribe(polyglot.CUSTOMPARAMS, self.handler_customparams)
        polyglot.subscribe(polyglot.POLL, self.poll)
        polyglot.subscribe(polyglot.WEBHOOK, self.handler_webhook)
        polyglot.subscribe(polyglot.CUSTOMNS, self.handler_customns)
        polyglot.subscribe(polyglot.NSINFO, self.handler_nsinfo)
        polyglot.subscribe(polyglot.ISY, self.handler_isy)
        polyglot.subscribe(polyglot.DISCOVER, self.discover)

        polyglot.ready()
        polyglot.addNode(self, conn_status="ST")

    def start(self):
        LOGGER.info('Starting Rachio Polyglot v3 NodeServer version {}'.format(VERSION))
        self.setDriver('GV0',0)

    def handler_customns(self,key,data):
        LOGGER.info(f'key={key} data={data}')

    def handler_nsinfo(self,params):
        LOGGER.info(f'params={params}')
        self.nsinfo = params
        LOGGER.debug(f'nsinfo={self.nsinfo}')

    def handler_isy(self,params):
        LOGGER.info(f'params={params}')

    def handler_customparams(self, params):
        self.poly.Notices.clear()
        self.Params.load(params)
        # Delete old unused params, must return because we get called when it's deleted.
        if "host" in params:
            self.Params.delete('host')
            return
        if "port" in params:
            self.Params.delete('port')
            return
        #
        # Make sure params exist
        #
        defaults = {
            "api_key": "",
            "nodeAdditionInterval": "1",
        }
        for param in defaults:
            if not param in params:
                self.Params[param] = defaults[param]
                return

        if self.Params['api_key'] == "":
            LOGGER.error('Rachio API key required in order to establish connection.  Enter custom parameter of \'api_key\' in Polyglot configuration.  See "https://rachio.readme.io/v1.0/docs" for instructions on how to obtain Rachio API Key.')
            self.poly.Notices['api'] = 'Rachio API key required in order to establish connection.  See "https://rachio.readme.io/v1.0/docs" for instructions on how to obtain Rachio API Key.'
            return False
        self.api_key = self.Params['api_key']

        try:
            self.nodeAdditionInterval = int(self.Params['nodeAdditionInterval'])
            if self.nodeAdditionInterval < 0 or self.nodeAdditionInterval > 60:
                self.nodeAdditionInterval = 1
                LOGGER.error('Node Addition Interval configured but outside of permissible range of 0 - 60 seconds, defaulting to %s second(s)', str(self.nodeAdditionInterval))
        except Exception as ex:
            self.nodeAdditionInterval = 1
            LOGGER.error('Error checking nodeAdditionalInterval %s: %s',
                         str(self.Params['nodeAdditionInterval']), str(ex), exc_info=True)

        self.discover()

        LOGGER.debug('Rachio "start" routine complete')

    # Available information: headers, query, body
    def handler_webhook(self,data):  
        LOGGER.debug(f"Webhook received: { data }")

        try:
            #self.data_string = self.rfile.read(int(self.headers['Content-Length'])).decode('utf-8')
            _json_data = json.loads(data['body'])
            LOGGER.info('Received webhook notification from Rachio: %s',str(_json_data))

            if 'test' in _json_data:
                if _json_data['test'] == self.random:
                    # It's me
                    LOGGER.info(f"test_webhook: _json_data={_json_data['test']} == {self.random} It's me, sending response")
                    self.poly.webhookResponse("success",200)
                    return True
                else:
                    LOGGER.error(f"test_webhook: _json_data={_json_data['test']} == {self.random} It's NOT me, sending response")
                    self.poly.webhookResponse("failed",200)
                    return False

            if 'deviceId' in _json_data:
                _deviceID = _json_data['deviceId']
                _devCount = 0
                for node in self.poly.nodes():
                    if node.device_id == _deviceID:
                        _devCount += 1
                        # TODO: Should parse the incoming data for change instead of queryAPI?
                        LOGGER.info("Updating %s %s ID=%s", node.address, node.name, node.device_id)
                        node.update_info(force=False,queryAPI=True)

                if _devCount > 0:
                    self.poly.webhookResponse("success",204)
                else:
                    self.poly.webhookResponse("Unknown deviceId",400)
                    LOGGER.warning("Unable to find device %s",_deviceID)
                        
        except Exception as ex:
            self.inc_error(f'{ex} processing webhook request:')
            self.poly.webhookResponse("failed",400)

    def nsinfo_done(self):
        # Make sure we have nsinfo
        cnt = 300
        while self.nsinfo is None and cnt > 0:
            # Warn after a couple seconds
            if cnt < 298:
                msg = f'Unable to test webooks nsinfo={self.nsinfo} not initialized yet cnt={cnt}'
                LOGGER.warning(msg)
                self.poly.Notices['nsinfo'] = msg
            time.sleep(1)
            cnt -= 1
        if self.nsinfo is None:
            self.inc_error('Timed out waiting for nsinfo handler, see Plugin log')
            self.poly.stop()
            return False
        self.poly.Notices.delete('nsinfo')
        return True

    def test_webhook(self):

        if not self.nsinfo_done():
            return False

        host = 'my.isy.io'
        port = 443
        #
        # All good, start the test
        #
        try:
            msg = "Unknown Error"
            if 'uuid' in self.nsinfo and 'profileNum' in self.nsinfo:
                conn = http.client.HTTPSConnection(host, port=port)
                _headers = {'Content-Type': 'application/json'}
                _url = f"/api/eisy/pg3/webhook/response/{self.nsinfo['uuid']}/{self.nsinfo['profileNum']}"
                LOGGER.info('Testing connectivity to %s:%s url:%s', str(host), str(port), _url)

                conn.request('POST', _url, json.dumps({'test': self.random}), headers=_headers )
                _resp = conn.getresponse()
                headers = _resp.getheaders()
                LOGGER.debug(f"Headers: {headers}")
                content_type = _resp.getheader('Content-Type')
                _respContent = _resp.read().decode()
                conn.close()
                if content_type and content_type.startswith('text/html;'):
                    LOGGER.debug('Webhook connectivity test response = %s',str(_respContent))
                    if _respContent == "success":
                        LOGGER.info('Connectivity test to %s:%s succeeded', str(host), str(port))
                        self.poly.Notices.delete('webhook')
                        self.setDriver('GV0',1)
                        return True
                    else:
                        msg = f'Unexpected content: {_respContent}'
                else:
                    msg = f'Unexpected content_type "{content_type}" {_respContent}'
            else:
                msg = f'Missing uuid and/or profileNum in nsinfo'
            self.inc_error(msg)
        except Exception as ex:
            self.inc_error(f'Exception: {ex}')
        self.setDriver('GV0',0)
        self.poly.Notices['api'] = f'Connectivity test to {host}:{port} was not successful. ' + msg + "<br>Please confirm portal webhooks are enabled, See <a href='https://github.com/UniversalDevicesInc/udi_python_interface/blob/master/Webhooks.md#requirements'  target='_blank'>Webooks Requirements</a>"
        return False

    def configure_webhook(self, WS_deviceID):

        if not self.nsinfo_done():
            return False

        # All good unless we have a problem
        res = True

        # Use portal for webhooks
        _url = f"https://my.isy.io/api/eisy/pg3/webhook/response/{self.nsinfo['uuid']}/{self.nsinfo['profileNum']}"
        LOGGER.debug("url=%s",_url)

        #Build event types array:
        _eventTypes = []
        _allEventTypes = []
        try:
            eventTypeResponse = self.r_api.notification.get_webhook_event_type()
            if not self.parseResponse(eventTypeResponse):
                return False
            for type in eventTypeResponse[1]:
                # WATER_BUDGET causes error?
                # {'code': '301', 'error': 'No enum constant WATER_BUDGET for webhook 8'}
                if type['name'] != 'WATER_BUDGET':
                    _eventTypes.append({'id':type['id']})
                    _allEventTypes.append(type)
        except Exception as ex:
            LOGGER.error('Building event types from %s: %s',
                        str(eventTypeResponse), str(ex), exc_info=True)
            res = False
        try:
            _ws = self.r_api.notification.get_device_webhook(WS_deviceID)
            if not self.parseResponse(_ws):
                return False
            LOGGER.debug('Obtained webHook information for %s, %s/%s API requests remaining until %s', str(WS_deviceID), str(_ws[0]['x-ratelimit-remaining']), str(_ws[0]['x-ratelimit-limit']),str(_ws[0]['x-ratelimit-reset']))
            _wsId = None
            for _websocket in _ws[1]:
                LOGGER.debug('check_webhook=%s', pprint.pformat(_websocket, indent=2))
                if 'externalId' in _websocket and 'url' in _websocket and 'id' in _websocket and 'eventTypes' in _websocket:
                    if _websocket['externalId'] == 'polyglot':
                        if _wsId is None: #This is the first polyglot-created webhook
                            _wsId = _websocket['id']
                            updateWebhook = True
                            if _url not in _websocket['url']:
                                #Polyglot webhook but url does not match currently configured host and port
                                LOGGER.info('Webhook %s found but url (%s) is not correct, updating to %s', str(_websocket['id']), str(_websocket['url']), _url)
                            else:
                                LOGGER.info(f"webook url is correct: {_websocket['url']}")
                                #URL is OK, check that all webhook event types are included:
                                _allEventsPresent = True
                                for type in _allEventTypes:
                                    _found = False
                                    for d in _websocket['eventTypes']:
                                        LOGGER.debug(f'd={d} type={type}')
                                        if d['name'] == type['name']:
                                            _found = True
                                            break
                                    if not _found:
                                        LOGGER.debug("Missing webhook: {}".format(type['name']))
                                        _allEventsPresent = False

                                if _allEventsPresent:
                                    # Webshook definition is OK!
                                    LOGGER.info(f"webhook events are correct")
                                    updateWebhook = False
                                else:
                                    #at least one websocket event is missing from the definition on the Rachio servers, updated the webhook:
                                    LOGGER.info('Webhook %s found but webhook event(s) is missing, updating', str(_websocket['id']))

                            if updateWebhook:
                                try:
                                    LOGGER.info("Updating Webhook %s, %s, %s, %s", _websocket['id'], 'polyglot', _url, str(_eventTypes))
                                    self.parseResponse(
                                        self.r_api.notification.update(_websocket['id'], 'polyglot', _url, _eventTypes)
                                    )
                                except Exception as ex:
                                    self.inc_error(f"Updating webhook {_websocket['id']}: {ex}")
                                    res = False
                        else: 
                            # This is an additional polyglot-created webhook
                            LOGGER.info('Polyglot webhook %s found but polyglot already has a webhook defined (%s).  Deleting this webhook', str(_websocket['id']), str(_wsId))
                            if self.parseResponse(self.r_api.notification.delete(_websocket['id'])):
                                LOGGER.debug(f'webhook success!')
                            else:
                                LOGGER.error(f'webhook delete failed!')
            
            if _wsId is None:
                #No Polyglot webhooks were found, create one:
                LOGGER.info('No Polyglot webhooks were found for device %s, creating a new webhook for Polyglot', str(WS_deviceID))
                try:
                    _createWS = self.r_api.notification.add(WS_deviceID, 'polyglot', _url, _eventTypes)
                    _resp = str(_createWS[1])
                    LOGGER.debug('Created webhook for device %s. "%s". %s/%s API requests remaining until %s', str(WS_deviceID), str(_resp), str(_createWS[0]['x-ratelimit-remaining']), str(_createWS[0]['x-ratelimit-limit']),str(_createWS[0]['x-ratelimit-reset']))
                except Exception as ex:
                    self.inc_error(f'Deleting webhook for device {WS_deviceID}: {ex}')
                    res = False
        except Exception as ex:
            self.inc_error(f'Configuring webhook for device {WS_deviceID}: {ex}')
            res = False
        self.configure_webhook_st = res
        return res

    #  ({'date': 'Sun, 04 Aug 2024 16:40:15 GMT', 'content-type': 'application/json;charset=utf-8', 'content-length': '68', 
    # 'connection': 'keep-alive', 'cache-control': 'no-cache, no-store, max-age=0, must-revalidate', 'pragma': 'no-cache', 
    # 'expires': '0', 'x-xss-protection': '1; mode=block', 'x-frame-options': 'DENY', 'x-content-type-options': 'nosniff', 
    # 'x-ratelimit-limit': '1700', 'x-ratelimit-remaining': '814', 'x-ratelimit-reset': '2024-08-05T00:00:00Z', 'status': 412}, 
    # {'code': '301', 'error': 'No enum constant WATER_BUDGET for webhook 8'})
    # TODO: Add error count to controller...
    def parseResponse(self,response):
        LOGGER.debug("response=%s", str(response))
        try:
            LOGGER.info('response: %s/%s API requests remaining until %s', 
                        str(response[0]['x-ratelimit-remaining']),
                        str(response[0]['x-ratelimit-limit']),
                        str(response[0]['x-ratelimit-reset']))
            if (response[0]['status'] == 200):
                LOGGER.info("response success %s", str(response[1]))
                self.poly.Notices.delete('parseResponse')
                return True
            else:
                self.inc_api_error(f'Rachio API Call error {response[1]}')
                return False
        except Exception as ex:
            self.inc_error(f'{ex} Parsing reponse: {response}')

    def poll(self, polltype):
        if 'longPoll' in polltype:
            # If previous discover failed, try again
            if self.discover_st is False:
                if not self.discover():
                    return False
            else:
                # Make sure webooks are passing thru the portal
                self.test_webhook()
            try:
                for node in self.poly.nodes():
                    node.update_info(force=False,queryAPI=False)
            except Exception as ex:
                self.inc_error(f'{ex} Running longPoll')

    def update_info(self, force=False, queryAPI=True):
        #Nothing to update for this node
        LOGGER.info("%s %s", self.address, self.name)
        pass

    def query(self, command = None):
        try:
            for node in self.poly.nodes():
                node.update_info(force=True)
        except Exception as ex:
            self.inc_error(f'{ex} Running query')

    def discoverCMD(self, command=None):
        # This is command called by ISY discover button
        for node in self.poly.nodes():
            node.discover()

    def discover(self, command=None):
        LOGGER.info('Starting discovery on %s api_key=%s', self.name, self.api_key)
        self.discover_st = None

        if not self.test_webhook():
            LOGGER.inc_error('Unable to discover until webooks are working properly')
            self.discover_st = False
            return False

        try:
            self.r_api = Rachio(self.api_key)
            _person_id = self.r_api.person.info()
            LOGGER.debug(f"person={_person_id}")
            self.person_id = _person_id[1]['id']
            self.person = self.r_api.person.get(self.person_id) #returns json containing all info associated with person (devices, zones, schedules, flex schedules, and notifications)
            self.parseResponse(self.person)
        except Exception as ex:
            self.inc_error(f'{ex} Running discover')
            self.discover_st = False
            return False

        try:
            #get devices
            self.devices = self.person[1]['devices']
            LOGGER.info('%i Rachio controllers found. Adding to ISY', len(self.devices))
            for d in self.devices:
                _device_id = str(d['id'])
                _name = str(d['name'])
                _address = str(d['macAddress']).lower()
                if not self.poly.getNode(_address):
                    #LOGGER.info('Adding Rachio Controller: %s(%s)', _name, _address)
                    self.addNodeQueue(RachioController(self.poly, _address, _address, _name, d, self.bridge_address))
                self.configure_webhook(_device_id)

        except Exception as ex:
            self.inc_error(f'{ex} Running discover add devices')
            self.discover_st = False
            return False

        self.discover_st = True
        return True

    def addNodeQueue(self, node):
        #If node is not already in ISY, add the node.  Otherwise, queue it for addition and start the interval timer.  Added version 2.2.0
        try:
            LOGGER.debug('Request received to add node: %s (%s)', node.name, node.address)
            self.nodeQueue[node.address] = node
            self._startNodeAdditionDelayTimer()
        except Exception as ex:
            self.inc_error(f'{ex} Queing node for addition')

    def _startNodeAdditionDelayTimer(self): #Added version 2.2.0
        try:
            if self.timer is not None:
                self.timer.cancel()
            self.timer = Timer(self.nodeAdditionInterval, self._addNodesFromQueue)
            self.timer.start()
            LOGGER.debug("Starting node addition delay timer for %s second(s)", str(self.nodeAdditionInterval))
            return True
        except Exception as ex:
            self.inc_error(f'{ex} Starting node addition delay timer')
            return False

    def _addNodesFromQueue(self): #Added version 2.2.0
        try:
            if len(self.nodeQueue) > 0:
                for _address in self.nodeQueue:
                    LOGGER.debug('Adding %s(%s) from queue', self.name, self.address)
                    self.poly.addNode(self.nodeQueue[_address])
                    del self.nodeQueue[_address]
                    break #only add one node at a time
        
            if len(self.nodeQueue) > 0: #Check for more nodes after addition, if there are more to add, restart the timer
                self._startNodeAdditionDelayTimer()
            else:
                LOGGER.info('No nodes pending addition')
        except Exception as ex:
            self.inc_error(f'{ex} Adding node from queue')

    def delete(self):
        LOGGER.info('Deleting %s', self.name)

    def err_notice(self,name,err_str):
            self.poly.Notices[name] = f"ERROR: {datetime.now().strftime('%m/%d/%Y %H:%M:%S')} See log for: {err_str}"

    def set_error(self,val=None,force=False):
        if val is None:
            val = 0
        self.errors = val
        self.setDriver('ERR',self.errors,force=force)

    def inc_error(self,err_str="error",exc_info=True,val=None):
        if val is None:
            val = 1
        self.set_error(self.errors + val)
        if err_str is not None:
            self.err_notice('ns_error',err_str)
            LOGGER.error(err_str,exc_info=exc_info)

    def dec_error(self,val=None):
        if val is None:
            val = 1
        self.set_error(self.errors - val)

    def set_api_error(self,val=None,exc_info=True,force=False):
        if val is None:
            val = 0
        self.api_errors = val
        self.setDriver('GV1',self.errors,force=force)

    def inc_api_error(self,err_str="api_error",val=None):
        if val is None:
            val = 1
        self.set_api_error(self.api_errors + 1)
        if err_str is not None:
            self.err_notice('api_error',err_str)
            LOGGER.error(err_str,exc_info=exc_info)

    def dec_api_error(self,val=None):
        if val is None:
            val = 1
        self.set_api_error(self.api_errors - val)

    id = 'rachio'
    commands = {'DISCOVER': discoverCMD, 'QUERY': query}
    drivers = [
        {'driver': 'ST',  'value': 1, 'uom': 2, 'name': 'Nodeserver Online'},
        {'driver': 'GV0', 'value': 0, 'uom': 2, 'name': 'Portal Webhook Status'},
        {"driver": "ERR", "value": 0, "uom": 56, "name": "NodeServer Errors"},
        {'driver': 'GV1', 'value': 0, 'uom': 56, 'name': 'Rachio API Errors'}
    ]
