
from udi_interface import Node,LOGGER,Custom
from nodes import VERSION,RachioController
import json, time
import http.client
from threading import Timer #Added version 2.2.0 for node addition queue
from rachiopy import Rachio
import random

WS_EVENT_TYPES = {
        "DEVICE_STATUS": 5,
        "RAIN_DELAY": 6,
        "WEATHER_INTELLIGENCE": 7,
        "WATER_BUDGET": 8,
        "SCHEDULE_STATUS": 9,
        "ZONE_STATUS": 10,
        "RAIN_SENSOR_DETECTION": 11,
        "ZONE_DELTA": 12,
        "DELTA": 14
    }

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
        self.discover_st = None

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

    def start(self):
        LOGGER.info('Starting Rachio Polyglot v3 NodeServer version {}'.format(VERSION))
        self.setDriver('GV0',0)

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
                    LOGGER.info("It's me, sending response")
                    self.poly.webhookResponse("success",200)
                    return True
                else:
                    LOGGER.error("It's not me? %s",_json_data)
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
                    #self.send_response(204) #v2.4.2: Removed http server response to invalid requests
                    #self.end_headers()
                else:
                    LOGGER.warning("Unable to find device %s",_deviceID)
                        
        except Exception as ex:
            LOGGER.error('Error processing webhook request: %s', str(ex), exc_info=True)
            #self.send_error(404) #v2.4.2: Removed http server response to invalid requests

    def test_webhook(self):
        host = 'my.isy.io'
        port = 443
        # Make sure we have nsinfo
        cnt = 300
        while self.nsinfo is None and cnt > 0:
            # Warn after a couple seconds
            if cnt < 298:
                msg = f'Unable to test webooks nsinfo={self.nsinfo} not initialized yet cnt={cnt}'
                LOGGER.warning(msg)
                self.poly.Notices['api'] = msg
            time.sleep(1)
            cnt -= 1
        if self.nsinfo is None:
            msg = "Timed out waiting for nsinfo handler, see Plugin log"
            LOGGER.error(msg)
            self.poly.Notices['api'] = msg
            self.poly.stop()
            return False
        self.poly.Notices.delete('api')
        #
        # All good, start the test
        #
        try:
            if 'uuid' in self.nsinfo and 'profileNum' in self.nsinfo:
                conn = http.client.HTTPSConnection(host, port=port)
                msg = "Unknown Error"
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
            LOGGER.error(msg)
        except Exception as ex:
            msg = f'Exception: {ex}'
            LOGGER.error(msg,exc_info=True)
        self.setDriver('GV0',0)
        self.poly.Notices['api'] = f'Connectivity test to {host}:{port} was not successful. ' + msg + "<br>Please confirm portal webhooks are enabled, See <a href='https://github.com/UniversalDevicesInc/udi_python_interface/blob/master/Webhooks.md#requirements'  target='_blank'>Webooks Requirements</a>"
        return False

    def configure_webhook(self, WS_deviceID):

        # Use portal for webhooks
        _url = f"https://my.isy.io/api/eisy/pg3/webhook/noresponse/{self.nsinfo['uuid']}/{self.nsinfo['profileNum']}"
        LOGGER.debug("url=%s",_url)

        #Build event types array:
        _eventTypes = []
        for key, value in WS_EVENT_TYPES.items():
            _eventTypes.append({'id':str(value)})
        
        try:
            _ws = self.r_api.notification.get_device_webhook(WS_deviceID)
            LOGGER.debug('Obtained webHook information for %s, %s/%s API requests remaining until %s', str(WS_deviceID), str(_ws[0]['x-ratelimit-remaining']), str(_ws[0]['x-ratelimit-limit']),str(_ws[0]['x-ratelimit-reset']))
            _websocketFound = False
            _wsId = ''
            for _websocket in _ws[1]:
                if 'externalId' in _websocket and 'url' in _websocket and 'id' in _websocket and 'eventTypes' in _websocket:
                    if _websocket['externalId'] == 'polyglot' and not _websocketFound: #This is the first polyglot-created webhook
                        if _url not in _websocket['url']:
                            #Polyglot webhook but url does not match currently configured host and port
                            LOGGER.info('Webhook %s found but url (%s) is not correct, updating to %s', str(_websocket['id']), str(_websocket['url']), _url)
                            try:
                                _updateWS = self.r_api.notification.update(_websocket['id'], 'polyglot', _url, _eventTypes)
                                LOGGER.debug(f'webhook update returned: {_updateWS}')
                                LOGGER.info('Updated webhook %s, %s/%s API requests remaining until %s', str(_websocket['id']), str(_updateWS[0]['x-ratelimit-remaining']), str(_updateWS[0]['x-ratelimit-limit']),str(_updateWS[0]['x-ratelimit-reset']))
                                _websocketFound = True
                                _wsId = _websocket['id']
                            except Exception as ex:
                                LOGGER.error('Error updating webhook %s url to "%s": %s', str(_websocket['id']),
                                             str(_url), str(ex), exc_info=True)
                        else:
                            LOGGER.info(f"webook url is correct: {_websocket['url']}")
                            #URL is OK, check that all webhook event types are included:
                            _allEventsPresent = True
                            for key, value in WS_EVENT_TYPES.items():
                                _found = False
                                for d in _websocket['eventTypes']:
                                    if d['name'] == key:
                                        _found = True
                                        break
                                # WATER_BUDGET is never returned
                                if not _found and key != 'WATER_BUDGET':
                                    LOGGER.debug("Missing webhook: {}".format(key))
                                    _allEventsPresent = False
                            
                            if _allEventsPresent:
                                LOGGER.info(f"webook events are correct")
                                # Webshook definition is OK!
                                _websocketFound = True
                                _wsId = _websocket['id']
                            else:
                                #at least one websocket event is missing from the definition on the Rachio servers, updated the webhook:
                                LOGGER.info('Webhook %s found but webhook event is missing, updating', str(_websocket['id']))
                                try:
                                    _updateWS = self.r_api.notification.update(_websocket['id'], 'polyglot', _url, _eventTypes)
                                    LOGGER.debug(f'webhook update returned: {_updateWS}')
                                    LOGGER.debug('Updated webhook %s, %s/%s API requests remaining until %s', str(_websocket['id']), str(_updateWS[0]['x-ratelimit-remaining']), str(_updateWS[0]['x-ratelimit-limit']),str(_updateWS[0]['x-ratelimit-reset']))
                                    _websocketFound = True
                                    _wsId = _websocket['id']
                                except Exception as ex:
                                    LOGGER.error('Error updating webhook %s events: %s', str(_websocket['id']),
                                                 str(ex), exc_info=True)
                                
                    elif  _websocket['externalId'] == 'polyglot' and _websocketFound: #This is an additional polyglot-created webhook
                        LOGGER.info('Polyglot webhook %s found but polyglot already has a webhook defined (%s).  Deleting this webhook', str(_websocket['id']), str(_wsId))
                        _deleteWs = self.r_api.notification.delete(_websocket['id'])
                        LOGGER.debug(f'webhook delete returned: {_deleteWS}')
                        LOGGER.debug('Deleted webhook %s, %s/%s API requests remaining until %s', str(_websocket['id']), str(_deleteWS[0]['x-ratelimit-remaining']), str(_deleteWS[0]['x-ratelimit-limit']),str(_deleteWS[0]['x-ratelimit-reset']))
            
            if not _websocketFound:
                #No Polyglot webhooks were found, create one:
                LOGGER.info('No Polyglot webhooks were found for device %s, creating a new webhook for Polyglot', str(WS_deviceID))
                try:
                    _createWS = self.r_api.notification.add(WS_deviceID, 'polyglot', _url, _eventTypes)
                    _resp = str(_createWS[1])
                    LOGGER.debug('Created webhook for device %s. "%s". %s/%s API requests remaining until %s', str(WS_deviceID), str(_resp), str(_createWS[0]['x-ratelimit-remaining']), str(_createWS[0]['x-ratelimit-limit']),str(_createWS[0]['x-ratelimit-reset']))
                except Exception as ex:
                    LOGGER.error('Error creating webhook for device %s: %s', 
                                 str(WS_deviceID), str(ex), exc_info=True)
        except Exception as ex:
            LOGGER.error('Error configuring webhooks for device %s: %s', 
                         str(WS_deviceID), str(ex), exc_info=True)

    
    def poll(self, polltype):
        if 'longPoll' in polltype:
            # If previous discover failed, try again
            if self.discover_st is False:
                if not self.discover():
                    return False
            else:
                # Make sure webooks are still working
                self.test_webhook()
            try:
                for node in self.poly.nodes():
                    node.update_info(force=False,queryAPI=False)
            except Exception as ex:
                LOGGER.error('Error running longPoll on %s: %s', self.name, str(ex))

    def update_info(self, force=False, queryAPI=True):
        #Nothing to update for this node
        LOGGER.info("%s %s", self.address, self.name)
        pass

    def query(self, command = None):
        try:
            for node in self.poly.nodes():
                node.update_info(force=True)
        except Exception as ex:
            LOGGER.error('Error running query on %s: %s', self.name, str(ex))

    def discoverCMD(self, command=None):
        # This is command called by ISY discover button
        for node in self.poly.nodes():
            node.discover()

    def discover(self, command=None):
        LOGGER.info('Starting discovery on %s api_key=%s', self.name, self.api_key)
        self.discover_st = None
        #
        # Make sure webhook is working
        #
        if not self.test_webhook():
            LOGGER.error("Unable to discover, Portal websocket test failed")
            self.discover_st = False
            return False

        try:
            self.r_api = Rachio(self.api_key)
            _person_id = self.r_api.person.info()
            LOGGER.debug(f"person={_person_id}")
            self.person_id = _person_id[1]['id']
            self.person = self.r_api.person.get(self.person_id) #returns json containing all info associated with person (devices, zones, schedules, flex schedules, and notifications)
            LOGGER.debug('Obtained Person ID (%s), %s/%s API requests remaining until %s', str(self.person_id), str(_person_id[0]['x-ratelimit-remaining']), str(_person_id[0]['x-ratelimit-limit']),str(_person_id[0]['x-ratelimit-reset']))
        except Exception as ex:
            try:
                LOGGER.error('Connection Error on RachioControl discovery, may be temporary. %s. %s/%s API requests remaining until %s', str(ex), str(_person_id[0]['x-ratelimit-remaining']), str(_person_id[0]['x-ratelimit-limit']),str(_person_id[0]['x-ratelimit-reset']),exc_info=True)
            except:
                LOGGER.error('Connection Error on RachioControl discovery, may be temporary. %s',exc_info=True)
            self.discover_st = False
            return False

        try:
            #get devices
            _devices = self.person[1]['devices']
            LOGGER.info('%i Rachio controllers found. Adding to ISY', len(_devices))
            for d in _devices:
                _device_id = str(d['id'])
                _name = str(d['name'])
                _address = str(d['macAddress']).lower()
                if not self.poly.getNode(_address):
                    #LOGGER.info('Adding Rachio Controller: %s(%s)', _name, _address)
                    self.addNodeQueue(RachioController(self.poly, _address, _address, _name, d, self.bridge_address))
                self.configure_webhook(_device_id)

        except Exception as ex:
            LOGGER.error('Error during Rachio device discovery: %s', str(ex))
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
            LOGGER.error('Error queuing node for addition: %s'. str(ex))

    def _startNodeAdditionDelayTimer(self): #Added version 2.2.0
        try:
            if self.timer is not None:
                self.timer.cancel()
            self.timer = Timer(self.nodeAdditionInterval, self._addNodesFromQueue)
            self.timer.start()
            LOGGER.debug("Starting node addition delay timer for %s second(s)", str(self.nodeAdditionInterval))
            return True
        except Exception as ex:
            LOGGER.error('Error starting node addition delay timer: %s', str(ex))
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
            LOGGER.error('Error encountered adding node from queue: %s', str(ex))


    def delete(self):
        LOGGER.info('Deleting %s', self.name)

    id = 'rachio'
    commands = {'DISCOVER': discoverCMD, 'QUERY': query}
    drivers = [
        {'driver': 'ST',  'value': 0, 'uom': 2, 'name': 'Nodeserver Online'},
        {'driver': 'GV0', 'value': 0, 'uom': 2, 'name': 'Portal Webhook Status'}
    ]
