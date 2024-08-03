#!/usr/bin/env python3
"""
This is a NodeServer for Rachio irrigation controllers originaly by fahrer16 (Brian Feeney)
and now developed by JimBo.Automates
Based on template for Polyglot v2 written in Python2/3 by Einstein.42 (James Milne) milne.james@gmail.com
"""

# TODO: Move to init when nodes are reorganized
VERSION="5.0.0"

from udi_interface import Interface,Node,LOGGER,Custom
import sys
import json, time
from datetime import datetime
import http.client
import re
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
                                LOGGER.debug(f'webhook update returned: {__updateWS}')
                                LOGGER.info('Updated webhook %s, %s/%s API requests remaining until %s', str(_websocket['id']), str(_updateWS[0]['x-ratelimit-remaining']), str(_updateWS[0]['x-ratelimit-limit']),str(_updateWS[0]['x-ratelimit-reset']))
                                _websocketFound = True
                                _wsId = _websocket['id']
                            except Exception as ex:
                                LOGGER.error('Error updating webhook %s url to "%s": %s', str(_websocket['id']), str(_url), str(ex))
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
                                    LOGGER.debug(f'webhook update returned: {__updateWS}')
                                    LOGGER.debug('Updated webhook %s, %s/%s API requests remaining until %s', str(_websocket['id']), str(_updateWS[0]['x-ratelimit-remaining']), str(_updateWS[0]['x-ratelimit-limit']),str(_updateWS[0]['x-ratelimit-reset']))
                                    _websocketFound = True
                                    _wsId = _websocket['id']
                                except Exception as ex:
                                    LOGGER.error('Error updating webhook %s events: %s', str(_websocket['id']), str(ex))
                                
                    elif  _websocket['externalId'] == 'polyglot' and _websocketFound: #This is an additional polyglot-created webhook
                        LOGGER.info('Polyglot webhook %s found but polyglot already has a webhook defined (%s).  Deleting this webhook', str(_websocket['id']), str(_wsId))
                        _deleteWs = self.r_api.notification.delete(_websocket['id'])
                        LOGGER.debug(f'webhook delete returned: {__deleteWS}')
                        LOGGER.debug('Deleted webhook %s, %s/%s API requests remaining until %s', str(_websocket['id']), str(_deleteWS[0]['x-ratelimit-remaining']), str(_deleteWS[0]['x-ratelimit-limit']),str(_deleteWS[0]['x-ratelimit-reset']))
            
            if not _websocketFound:
                #No Polyglot webhooks were found, create one:
                LOGGER.info('No Polyglot webhooks were found for device %s, creating a new webhook for Polyglot', str(WS_deviceID))
                try:
                    _createWS = self.r_api.notification.add(WS_deviceID, 'polyglot', _url, _eventTypes)
                    _resp = str(_createWS[1])
                    LOGGER.debug('Created webhook for device %s. "%s". %s/%s API requests remaining until %s', str(WS_deviceID), str(_resp), str(_createWS[0]['x-ratelimit-remaining']), str(_createWS[0]['x-ratelimit-limit']),str(_createWS[0]['x-ratelimit-reset']))
                except Exception as ex:
                    LOGGER.error('Error creating webhook for device %s: %s', str(WS_deviceID), str(ex))
        except Exception as ex:
            LOGGER.error('Error configuring webhooks for device %s: %s', str(WS_deviceID), exc_info=True)

    
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


class RachioController(Node):
    def __init__(self, polyglot, primary, address, name, device, parent):
        super().__init__(polyglot, primary, address, name)
        self.isPrimary = True
        self.primary = primary
        self.poly = polyglot
        self.device = device
        self.device_id = device['id']
        self.lastDeviceUpdateTime = datetime(1970,1,1)
        self.parent = polyglot.getNode(parent)  # This is the Controller class
        
        self.rainDelay_minutes_remaining = 0
        self.currentSchedule = []
        self.lastSchedUpdateTime = datetime(1970,1,1)
        
        self._tries = 0
        self.runTypes = {0: "NONE",
                              1: "AUTOMATIC",
                              2: "MANUAL",
                              3: "OTHER"}
                              
        self.discoverComplete = False

        polyglot.subscribe(polyglot.START, self.start, address)


    def start(self):
        self.update_info(force=True,queryAPI=True)
        self.discoverComplete = self.discover()

    def discover(self, command=None):
        _success = True
        LOGGER.info('Discovering nodes on Rachio Controller %s (%s)', self.name, self.address)
        try:
            _zones = self.device['zones']
            LOGGER.info('%i Rachio zones found on "%s" controller. Adding to ISY', len(_zones), self.name)
            for z in _zones:
                _zone_id = str(z['id'])
                _zone_num = str(z['zoneNumber'])
                _zone_addr = self.address + _zone_num #construct address for this zone (mac address of controller appended with zone number) because ISY limit is 14 characters
                _zone_name = str(z['name'])
                if not self.poly.getNode(_zone_addr):
                    #LOGGER.info('Adding new Rachio Zone to %s Controller, %s(%s)', self.name, _zone_name, _zone_addr)
                    self.parent.addNodeQueue(RachioZone(self.poly, self.address, _zone_addr, _zone_name, z, self.device_id, self, self.parent)) #v2.2.0, updated to add node to queue, rather that adding to ISY immediately
        except Exception as ex:
            _success = False
            LOGGER.error('Error discovering and adding Zones on Rachio Controller %s (%s): %s', self.name, self.address, str(ex))
        
        try:
            _schedules = self.device['scheduleRules']
            LOGGER.info('%i Rachio schedules found on "%s" controller. Adding to ISY', len(_schedules), self.name)
            for s in _schedules:
                _sched_id = str(s['id'])
                _sched_addr = self.address + _sched_id[-2:] #construct address for this schedule (mac address of controller appended with last 2 characters of schedule unique id) because ISY limit is 14 characters
                _sched_name = str(s['name'])
                if not self.poly.getNode(_sched_addr):
                    #LOGGER.info('Adding new Rachio Schedule to %s Controller, %s(%s)', self.name, _sched_name, _sched_addr)
                    self.parent.addNodeQueue(RachioSchedule(self.poly, self.address, _sched_addr, _sched_name, s, self.device_id, self, self.parent)) #v2.2.0, updated to add node to queue, rather that adding to ISY immediately
        except Exception as ex:
            _success = False
            LOGGER.error('Error discovering and adding Schedules on Rachio Controller %s (%s): %s', self.name, self.address, str(ex))

        try:
            _flex_schedules = self.device['flexScheduleRules']
            LOGGER.info('%i Rachio Flex schedules found on "%s" controller. Adding to ISY', len(_flex_schedules), self.name)
            for f in _flex_schedules:
                _flex_sched_id = str(f['id'])
                _flex_sched_addr = self.address + _flex_sched_id[-2:] #construct address for this schedule (mac address of controller appended with last 2 characters of schedule unique id) because ISY limit is 14 characters
                _flex_sched_name = str(f['name'])
                if not self.poly.getNode(_flex_sched_addr):
                    #LOGGER.info('Adding new Rachio Flex Schedule to %s Controller, %s(%s)',self.name, _flex_sched_name, _flex_sched_addr)
                    self.parent.addNodeQueue(RachioFlexSchedule(self.poly, self.address, _flex_sched_addr, _flex_sched_name, f, self.device_id, self, self.parent)) #v2.2.0, updated to add node to queue, rather that adding to ISY immediately
        except Exception as ex:
            _success = False
            LOGGER.error('Error discovering and adding Flex Schedules on Rachio Controller %s (%s): %s', self.name, self.address, str(ex))

        return _success
        
    def getDeviceInfo(self, force=False):
        try:
            #Get latest device info and populate drivers
            _secSinceDeviceUpdate = (datetime.now() - self.lastDeviceUpdateTime).total_seconds()
            if (_secSinceDeviceUpdate > 5 and force and self.discoverComplete) or _secSinceDeviceUpdate > 3600:
                _device = self.parent.r_api.device.get(self.device_id)
                self.device = _device[1]
                self.lastDeviceUpdateTime = datetime.now()
                LOGGER.debug('Obtained Device Info for %s, %s/%s API requests remaining until %s', str(self.device_id), str(_device[0]['x-ratelimit-remaining']), str(_device[0]['x-ratelimit-limit']),str(_device[0]['x-ratelimit-reset']))
                            
        except Exception as ex:
            LOGGER.error('Connection Error on %s Rachio Controller API Request. This could mean an issue with internet connectivity or Rachio servers, normally safe to ignore. %s', self.name, str(ex))
        return self.device
            
    def getCurrentSchedule(self, force=False):
        try:
            _secSinceSchedUpdate = (datetime.now() - self.lastSchedUpdateTime).total_seconds()
            if (_secSinceSchedUpdate > 5 and force and self.discoverComplete) or _secSinceSchedUpdate > 3600:
                _sched = self.parent.r_api.device.current_schedule(self.device_id)
                self.currentSchedule = _sched[1]
                self.lastSchedUpdateTime = datetime.now()
                LOGGER.debug('Obtained Device Schedule for %s, %s/%s API requests remaining until %s', str(self.device_id), str(_sched[0]['x-ratelimit-remaining']), str(_sched[0]['x-ratelimit-limit']),str(_sched[0]['x-ratelimit-reset']))
        except Exception as ex:
            LOGGER.error('Connection Error on %s Rachio Controller current schedule API Request. This could mean an issue with internet connectivity or Rachio servers, normally safe to ignore. %s', self.name, str(ex))
            return False
        return self.currentSchedule

    def update_info(self, force=False, queryAPI=True):
        LOGGER.info("%s %s", self.address, self.name)

        _running = False #initialize variable so that it could be used even if there was not a need to update the running status of the controller
        self.getDeviceInfo(force=queryAPI)
        self.getCurrentSchedule(force=queryAPI)
            
        # ST -> Status (whether Rachio is running a schedule or not)
        try:
            if 'status' in self.currentSchedule:
                _running = (str(self.currentSchedule['status']) == "PROCESSING")
                self.setDriver('ST',(0,100)[_running])
            else:
                self.setDriver('ST',0)
        except Exception as ex:
            LOGGER.error('Error updating current schedule running status on %s Rachio Controller. %s', self.name, str(ex))

        # GV0 -> "Connected"
        try:
            _connected = (self.device['status'] == "ONLINE")
            self.setDriver('GV0',int(_connected))
        except Exception as ex:
            self.setDriver('GV0',0)
            LOGGER.error('Error updating connection status on %s Rachio Controller. %s', self.name, str(ex))

        # GV1 -> "Enabled"
        try:
            self.setDriver('GV1',int(self.device['on']))
        except Exception as ex:
            self.setDriver('GV1',0)
            LOGGER.error('Error updating status on %s Rachio Controller. %s', self.name, str(ex))

        # GV2 -> "Paused"
        try:
            if 'paused' in self.device:
                self.setDriver('GV2', int(self.device['paused']))
            else:
                self.setDriver('GV2', 0)
        except Exception as ex:
            LOGGER.error('Error updating paused status on %s Rachio Controller. %s', self.name, str(ex))

        # GV3 -> "Rain Delay Remaining" in Minutes
        try:
            if 'rainDelayExpirationDate' in self.device: 
                _current_time = int(time.time())
                _rainDelayExpiration = self.device['rainDelayExpirationDate'] / 1000.
                _rainDelay_minutes_remaining = int(max(_rainDelayExpiration - _current_time,0) / 60.)
                self.setDriver('GV3', _rainDelay_minutes_remaining)
                self.rainDelay_minutes_remaining = _rainDelay_minutes_remaining
            else: self.setDriver('GV3', 0)
        except Exception as ex:
            LOGGER.error('Error updating remaining rain delay duration on %s Rachio Controller. %s', self.name, str(ex))
        
        # GV10 -> Active Run Type
        try:
            if 'type' in self.currentSchedule: # True when a schedule is running
                _runType = self.currentSchedule['type']
                _runVal = 3 #default to "OTHER"
                for key in self.runTypes:
                    if self.runTypes[key].lower() == _runType.lower():
                        _runVal = key
                        break
                self.setDriver('GV10', _runVal)
            else: 
                self.setDriver('GV10', 0)
        except Exception as ex:
            LOGGER.error('Error updating active run type on %s Rachio Controller. %s', self.name, str(ex))

        # GV4 -> Active Zone #
        if 'zoneId' in self.currentSchedule:
            try:
                if queryAPI:
                    _active_zoneId = self.currentSchedule['zoneId']
                    _zones = self.device['zones']
                    for z in _zones:
                        _zone_id = str(z['id'])
                        if _zone_id == _active_zoneId:
                            _zone_num = str(z['zoneNumber'])
                            self.setDriver('GV4',_zone_num)
                            break
            except Exception as ex:
                LOGGER.error('Error updating active zone on %s Rachio Controller. %s', self.name, str(ex))
        else: #no schedule running:
            self.setDriver('GV4',0)
        
        # GV5 -> Active Schedule remaining minutes and GV6 -> Active Schedule minutes elapsed
        try:
            if 'startDate' in self.currentSchedule and 'duration' in self.currentSchedule:
                _current_time = int(time.time())
                _start_time = int(self.currentSchedule['startDate'] / 1000)
                _duration = int(self.currentSchedule['duration'])

                _seconds_elapsed = max(_current_time - _start_time,0)
                _minutes_elapsed = round(_seconds_elapsed / 60. ,1)
                
                _seconds_remaining = max(_duration - _seconds_elapsed,0)
                _minutes_remaining = round(_seconds_remaining / 60. ,1)

                self.setDriver('GV5',_minutes_remaining)
                self.setDriver('GV6',_minutes_elapsed)
                #LOGGER.info('%f minutes elapsed and %f minutes remaining on %s Rachio Controller. %s', _minutes_elapsed, _minutes_remaining, self.name)
            else: 
                self.setDriver('GV5',0.0)
                self.setDriver('GV6',0.0)
        except Exception as ex:
            LOGGER.error('Error trying to retrieve active schedule minutes remaining/elapsed on %s Rachio Controller. %s', self.name, str(ex))

        # GV7 -> Cycling (true/false)
        try:
            if 'cycling' in self.currentSchedule:
                self.setDriver('GV7',int(self.currentSchedule['cycling']))
            else: self.setDriver('GV7', 0) #no schedule active
        except Exception as ex:
            LOGGER.error('Error trying to retrieve cycling status on %s Rachio Controller. %s', self.name, str(ex))
        
        # GV8 -> Cycle Count
        try:
            if 'cycleCount' in self.currentSchedule:
                self.setDriver('GV8',self.currentSchedule['cycleCount'])
            else: self.setDriver('GV8',0) #no schedule active
        except Exception as ex:
            LOGGER.error('Error trying to retrieve cycle count on %s Rachio Controller. %s', self.name, str(ex))

        # GV9 -> Total Cycle Count
        try:
            if 'totalCycleCount' in self.currentSchedule:
                self.setDriver('GV9',self.currentSchedule['totalCycleCount'])
            else: self.setDriver('GV9',0) #no schedule active
        except Exception as ex:
            LOGGER.error('Error trying to retrieve total cycle count on %s Rachio Controller. %s', self.name, str(ex))
       
        if force: self.reportDrivers()
        return True
    

    def query(self, command = None):
        LOGGER.info('query command received on %s Rachio Controller.', self.name)
        self.update_info(force=True,queryAPI=True)
        return True

    def enable(self, command): #Enables Rachio (schedules, weather intelligence, water budget, etc...)
        self._tries = 0
        while self._tries < 2: #TODO: the first command to the Rachio server fails frequently for some reason with an SSL WRONG_VERSION_NUMBER error.  This is a temporary workaround to try a couple of times before giving up
            try:
                self.parent.r_api.device.turn_on(self.device_id)
                #self.update_info() Rely on webhook to update on device's change in status
                LOGGER.info('Command received to enable %s Controller',self.name)
                self._tries = 0
                return True
            except Exception as ex:
                LOGGER.error('Error turning on %s. %s', self.name, str(ex))
                self._tries = self._tries + 1
        return False

    def disable(self, command): #Disables Rachio (schedules, weather intelligence, water budget, etc...)
        self._tries = 0
        while self._tries < 2: #TODO: the first command to the Rachio server fails frequently for some reason with an SSL WRONG_VERSION_NUMBER error.  This is a temporary workaround to try a couple of times before giving up
            try:
                self.parent.r_api.device.turn_off(self.device_id)
                #self.update_info() Rely on webhook to update on device's change in status
                LOGGER.info('Command received to disable %s Controller',self.name)
                self._tries = 0
                return True
            except Exception as ex:
                LOGGER.error('Error turning off %s. %s', self.name, str(ex))
                self._tries = self._tries + 1
        return False

    def stopCmd(self, command):
        self._tries = 0
        while self._tries < 2: #TODO: the first command to the Rachio server fails frequently for some reason with an SSL WRONG_VERSION_NUMBER error.  This is a temporary workaround to try a couple of times before giving up
            try:
                self.parent.r_api.device.stop_ater(self.device_id)
                LOGGER.info('Command received to stop watering on %s Controller',self.name)
                #self.update_info() Rely on webhook to update on device's change in status
                self._tries = 0
                return True
            except Exception as ex:
                LOGGER.error('Error stopping watering on %s. %s', self.name, str(ex))
                self._tries = self._tries + 1
        return False
    
    def rainDelay(self, command):
        _minutes = command.get('value')
        if _minutes is None:
            LOGGER.error('Rain Delay requested on %s Rachio Controller but no duration specified', self.name)
            return False
        else:
            LOGGER.info('Received rain Delay command on %s Rachio Controller for %s minutes', self.name, str(_minutes))
            self._tries = 0
            while self._tries < 2: #TODO: the first command to the Rachio server fails frequently for some reason with an SSL WRONG_VERSION_NUMBER error.  This is a temporary workaround to try a couple of times before giving up
                try:
                    _seconds = int(float(_minutes) * 60.)
                    self.parent.r_api.device.rain_delay(self.device_id, _seconds)
                    #self.update_info() Rely on webhook to update on device's change in status
                    self._tries = 0
                    return True
                except Exception as ex:
                    LOGGER.error('Error setting rain delay on %s Rachio Controller (%s)', self.name, str(ex))
                    self._tries = self._tries +1
            return False

    drivers = [{'driver': 'ST', 'value': 0, 'uom': 78}, #Status (On/Off)
               {'driver': 'GV0', 'value': 0, 'uom': 2}, #Connected (True/False)
               {'driver': 'GV1', 'value': 0, 'uom': 2}, #Enabled (True/False)
               {'driver': 'GV2', 'value': 0, 'uom': 2}, #Paused (True/False)
               {'driver': 'GV3', 'value': 0, 'uom': 45}, #Rain Delay Minutes Remaining (Minutes)
               {'driver': 'GV4', 'value': 0, 'uom': 56}, #Active Zone # (Raw Value)
               {'driver': 'GV5', 'value': 0, 'uom': 45}, #Active Schedule Minutes Remaining (Minutes)
               {'driver': 'GV6', 'value': 0, 'uom': 45}, #Active Schedule Minutes Elapsed (Minutes)
               {'driver': 'GV7', 'value': 0, 'uom': 2}, #Cycling (True/False)
               {'driver': 'GV8', 'value': 0, 'uom': 56}, #Cycle Count (Raw Value)
               {'driver': 'GV9', 'value': 0, 'uom': 56}, #Total Cycle Count (Raw Value)
               {'driver': 'GV10', 'value': 0, 'uom': 25} #Current Schedule Type (Enumeration)
               ]

    id = 'rachio_device'
    commands = {'DON': enable, 'DOF': disable, 'QUERY': query, 'STOP': stopCmd, 'RAIN_DELAY': rainDelay}

'''
Parent is the RachioController, but we also need access to the 
Controller class as that's where the r_api exists.
'''
class RachioZone(Node):
    def __init__(self, polyglog, primary, address, name, zone, device_id, device, controller):
        super().__init__(polyglot, primary, address, name)
        self.device_id = device_id
        self.device = device  # RachioController class
        self.controller = controller
        self.zone = zone
        self.zone_id = zone['id']
        self.name = name
        self.address = address
        self.rainDelayExpiration = 0
        self.currentSchedule = []
        self._tries = 0
        self.parent = polyglot.getNode(primary) # RachioController class

        polyglot.subscribe(polyglot.START, self.start, address)

    def start(self):
        self.update_info(force=True,queryAPI=True)

    def discover(self, command=None):
        # No discovery needed (no nodes are subordinate to Zones)
        pass

    def update_info(self, force=False, queryAPI=True):
        LOGGER.info("%s %s", self.address, self.name)
        _running = False #initialize variable so that it could be used even if there was not a need to update the running status of the zone
        #Updating info for zone %s with id %s, force=%s',self.address, str(self.zone_id), str(force))
        try:
            _deviceInfo = self.device.getDeviceInfo(force=queryAPI)
            for z in _deviceInfo['zones']:
                _zone_id = str(z['id'])
                if _zone_id == self.zone_id:
                    self.zone = z
                    break
            
            self.currentSchedule = self.device.getCurrentSchedule(force=queryAPI)

        except Exception as ex:
            LOGGER.error(' Error retrieving zone info for "%s"', self.name, str(ex))
            return False
            
        # ST -> Status (whether Rachio zone is running a schedule or not)
        try:
            if 'status' in self.currentSchedule and 'zoneId' in self.currentSchedule:
                _running = (str(self.currentSchedule['status']) == "PROCESSING") and (self.currentSchedule['zoneId'] == self.zone_id)
                self.setDriver('ST',(0,100)[_running])
            else:
                self.setDriver('ST',0)
        except Exception as ex:
            LOGGER.error('Error updating current schedule running status on %s Rachio Zone. %s', self.name, str(ex))

        # GV0 -> "Enabled"
        try:
            self.setDriver('GV0',int(self.zone['enabled']))
        except Exception as ex:
            self.setDriver('GV0',0)
            LOGGER.error('Error updating enable status on %s Rachio Zone. %s', self.name, str(ex))

        # GV1 -> "Zone Number"
        try:
            self.setDriver('GV1', self.zone['zoneNumber'])
        except Exception as ex:
            LOGGER.error('Error updating zone number on %s Rachio Zone. %s', self.name, str(ex))

        # GV2 -> Available Water
        # TODO: Not 100% sure what this is or if the units are correct, need to see if Rachio has any additional info
        try:
            self.setDriver('GV2', self.zone['availableWater'])
        except Exception as ex:
            LOGGER.error('Error updating available water on %s Rachio Zone. %s', self.name, str(ex))

        # GV3 -> root zone depth
        # TODO: Not 100% sure what this is or if the units are correct, need to see if Rachio has any additional info
        try:
            self.setDriver('GV3', self.zone['rootZoneDepth'])
        except Exception as ex:
            LOGGER.error('Error updating root zone depth on %s Rachio Zone. %s', self.name, str(ex))

        # GV4 -> allowed depletion
        # TODO: Not 100% sure what this is or if the units are correct, need to see if Rachio has any additional info
        try:
            self.setDriver('GV4', self.zone['managementAllowedDepletion'])
        except Exception as ex:
            LOGGER.error('Error updating allowed depletion on %s Rachio Zone. %s', self.name, str(ex))

        # GV5 -> efficiency
        try:
            self.setDriver('GV5', int(self.zone['efficiency'] * 100.))
        except Exception as ex:
            LOGGER.error('Error updating efficiency on %s Rachio Zone. %s', self.name, str(ex))

        # GV6 -> square feet
        # TODO: This is in square feet, but there's no unit available in the ISY for square feet.  Update if UDI makes it available
        try:
            self.setDriver('GV6', self.zone['yardAreaSquareFeet'])
        except Exception as ex:
            LOGGER.error('Error updating square footage on %s Rachio Zone. %s', self.name, str(ex))

        # GV7 -> irrigation amount
        # TODO: Not 100% sure what this is or if the units are correct, need to see if Rachio has any additional info
        try:
            if 'irrigationAmount' in self.zone:
                self.setDriver('GV7', self.zone['irrigationAmount'])
            else:
                self.setDriver('GV7', 0)
        except Exception as ex:
            LOGGER.error('Error updating irrigation amount on %s Rachio Zone. %s', self.name, str(ex))

        # GV8 -> depth of water
        # TODO: Not 100% sure what this is or if the units are correct, need to see if Rachio has any additional info
        try:
            self.setDriver('GV8', self.zone['depthOfWater'])
        except Exception as ex:
            LOGGER.error('Error updating depth of water on %s Rachio Zone. %s', self.name, str(ex))

        # GV9 -> runtime
        # TODO: Not 100% sure what this is or if the units are correct, need to see if Rachio has any additional info
        try:
            self.setDriver('GV9', self.zone['runtime'])
        except Exception as ex:
            LOGGER.error('Error updating runtime on %s Rachio Zone. %s', self.name, str(ex))

        # GV10 -> inches per hour
        try:
            self.setDriver('GV10', self.zone['customNozzle']['inchesPerHour'])
        except Exception as ex:
            LOGGER.error('Error updating inches per hour on %s Rachio Zone. %s', self.name, str(ex))
        
        if force: self.reportDrivers()
        return True

    def query(self, command = None):
        LOGGER.info('query command received on %s Rachio Zone', self.name)
        self.update_info(force=True,queryAPI=True)
        return True

    def startCmd(self, command):
        _minutes = command.get('value')
        if _minutes is None:
            LOGGER.error('Zone %s requested to start but no duration specified', self.name)
            return False
        else:
            self._tries = 0
            while self._tries < 2: #TODO: the first command to the Rachio server fails frequently for some reason with an SSL WRONG_VERSION_NUMBER error.  This is a temporary workaround to try a couple of times before giving up
                try:
                    if _minutes == 0:
                        LOGGER.error('Zone %s requested to start but duration specified was zero', self.name)
                        return False
                    _seconds = int(float(_minutes) * 60.)
                    self.controller.r_api.zone.start(self.zone_id, _seconds)
                    LOGGER.info('Command received to start watering zone %s for %s minutes',self.name, str(_minutes))
                    #self.update_info() Rely on webhook to update on device's change in status
                    self._tries = 0
                    return True
                except Exception as ex:
                    LOGGER.error('Error starting watering on zone %s. %s', self.name, str(ex))
                    self._tries = self._tries + 1
            return False

    drivers = [{'driver': 'ST', 'value': 0, 'uom': 78}, #Running (On/Off)
               {'driver': 'GV0', 'value': 0, 'uom': 2}, #Enabled (True/False)
               {'driver': 'GV1', 'value': 0, 'uom': 56}, #Zone Number (Raw Value)
               {'driver': 'GV2', 'value': 0, 'uom': 105}, #Available Water (Inches)
               {'driver': 'GV3', 'value': 0, 'uom': 105}, #Root Zone Depth (Inches)
               {'driver': 'GV4', 'value': 0, 'uom': 105}, #Allowed Depletion (Inches)
               {'driver': 'GV5', 'value': 0, 'uom': 51}, #Efficiency (Percent)
               {'driver': 'GV6', 'value': 0, 'uom': 18}, #Zone Area (*Square* Feet)
               {'driver': 'GV7', 'value': 0, 'uom': 105}, #Irrigation Amount (Inches)
               {'driver': 'GV8', 'value': 0, 'uom': 105}, #Depth of Water (Inches)
               {'driver': 'GV9', 'value': 0, 'uom': 45}, #Runtime (Minutes)
               {'driver': 'GV10', 'value': 0, 'uom': 24} #Inches per Hour
               ]

    id = 'rachio_zone'
    commands = {'QUERY': query, 'START': startCmd}

class RachioSchedule(Node):
    def __init__(self, polyglot, primary, address, name, schedule, device_id, device, controller):
        super().__init__(polyglot, primary, address, name)
        self.device_id = device_id
        self.device = device
        self.controller = controller
        self.schedule = schedule
        self.schedule_id = schedule['id']
        self.name = name
        self.address = address
        self.currentSchedule = []
        self.scheduleItems = []
        self._tries = 0
        self.parent = polyglot.getNode(primary)

        polyglot.subscribe(polyglot.START, self.start, address)

    def start(self):
        self.update_info(force=True,queryAPI=True)

    def discover(self, command=None):
        # No discovery needed (no nodes are subordinate to Schedules)
        pass
        
    def update_info(self, force=False, queryAPI=True):
        LOGGER.info("%s %s", self.address, self.name)
        _running = False #initialize variable so that it could be used even if there was not a need to update the running status of the schedule
        try:
            _deviceInfo = self.device.getDeviceInfo(force=queryAPI)
            for s in _deviceInfo['scheduleRules']:
                _sched_id = str(s['id'])
                if _sched_id == self.schedule_id:
                    self.schedule = s
                    break
            
            self.currentSchedule = self.device.getCurrentSchedule(force=queryAPI)

        except Exception as ex:
            LOGGER.error(' Error retrieving schedule info for "%s"', self.name, str(ex))
            return False
                  
        # ST -> Status (whether Rachio schedule is running a schedule or not)
        try:
            if 'scheduleRuleId' in self.currentSchedule:
                _running = (self.currentSchedule['scheduleRuleId'] == self.schedule_id)
                self.setDriver('ST',(0,100)[_running])
            else:
                self.setDriver('ST',0)
        except Exception as ex:
            LOGGER.error('Error updating current schedule running status on %s Rachio Schedule. %s', self.name, str(ex))

        # GV0 -> "Enabled"
        try:
            self.setDriver('GV0',int(self.schedule['enabled']))
        except Exception as ex:
            LOGGER.error('Error updating enable status on %s Rachio Schedule. %s', self.name, str(ex))

        # GV1 -> "rainDelay" status
        try:
            if 'rainDelay' in self.schedule:
                self.setDriver('GV1',int(self.schedule['rainDelay']))
            else:
                self.setDriver('GV1',0)
        except Exception as ex:
            LOGGER.error('Error updating schedule rain delay on %s Rachio Schedule. %s', self.name, str(ex))

        # GV2 -> duration (minutes)
        try:
            _seconds = float(self.schedule['totalDuration'])
            _minutes = int(_seconds / 60.)
            self.setDriver('GV2', _minutes)
        except Exception as ex:
            LOGGER.error('Error updating total duration on %s Rachio Schedule. %s', self.name, str(ex))

        # GV3 -> seasonal adjustment
        try:
            if 'seasonalAdjustment' in self.schedule:
                _seasonalAdjustment = float(self.schedule['seasonalAdjustment']) * 100.
                self.setDriver('GV3', _seasonalAdjustment)
        except Exception as ex:
            LOGGER.error('Error updating seasonal adjustment on %s Rachio Schedule. %s', self.name, str(ex))

        if force: self.reportDrivers()
        return True
        
    def query(self, command = None):
        LOGGER.info('query command received on %s Rachio Schedule.', self.name)
        self.update_info(force=True,queryAPI=True)
        return True

    def startCmd(self, command):
        self._tries = 0
        while self._tries < 2: #TODO: the first command to the Rachio server fails frequently for some reason with an SSL WRONG_VERSION_NUMBER error.  This is a temporary workaround to try a couple of times before giving up
            try:
                self.controller.r_api.schedulerule.start(self.schedule_id)
                LOGGER.info('Command received to start watering schedule %s',self.name)
                #self.update_info() Rely on webhook to update on device's change in status
                self._tries = 0
                return True
            except Exception as ex:
                LOGGER.error('Error starting watering on schedule %s. %s', self.name, str(ex))
                self._tries = self._tries + 1
        return False
    
    def skip(self, command):
        self._tries = 0
        while self._tries < 2: #TODO: the first command to the Rachio server fails frequently for some reason with an SSL WRONG_VERSION_NUMBER error.  This is a temporary workaround to try a couple of times before giving up
            try:
                self.controller.r_api.schedulerule.skip(self.schedule_id)
                LOGGER.info('Command received to skip watering schedule %s',self.name)
                #self.update_info() Rely on webhook to update on device's change in status
                self._tries = 0
                return True
            except Exception as ex:
                LOGGER.error('Error skipping watering on schedule %s. %s', self.name, str(ex))
                self._tries = self._tries = 1
        return False

    def seasonalAdjustment(self, command):
        self._tries = 0
        while self._tries < 2: #TODO: the first command to the Rachio server fails frequently for some reason with an SSL WRONG_VERSION_NUMBER error.  This is a temporary workaround to try a couple of times before giving up
            try:
                _value = float(command.get('value'))
                if _value is not None:
                    _value = _value / 100.
                    self.controller.r_api.schedulerule.seasonal_adjustment(self.schedule_id, _value)
                    LOGGER.info('Command received to change seasonal adjustment on schedule %s to %s',self.name, str(_value))
                    #self.update_info() Rely on webhook to update on device's change in status
                    self._tries = 0
                    return True
                else:
                    LOGGER.error('Command received to change seasonal adjustment on schedule %s but no value supplied',self.name)
                    return False
            except Exception as ex:
                LOGGER.error('Error changing seasonal adjustment on schedule %s. %s', self.name, str(ex))
                self._tries = self._tries + 1
        return False

    drivers = [{'driver': 'ST', 'value': 0, 'uom': 78}, #Running (On/Off)
               {'driver': 'GV0', 'value': 0, 'uom': 2}, #Enabled (True/False)
               {'driver': 'GV1', 'value': 0, 'uom': 2}, #Rain Delay (True/False)
               {'driver': 'GV2', 'value': 0, 'uom': 45}, #Duration (Minutes)
               {'driver': 'GV3', 'value': 0, 'uom': 51} #Seasonal Adjustment (Percent)
               ]

    id = 'rachio_schedule'
    commands = {'QUERY': query, 'START': startCmd, 'SKIP':skip, 'ADJUST':seasonalAdjustment}

class RachioFlexSchedule(Node):
    def __init__(self, polyglot, primary, address, name, schedule, device_id, device, controller):
        super().__init__(polyglot, primary, address, name)
        self.device_id = device_id
        self.device = device
        self.controller = controller
        self.schedule = schedule
        self.schedule_id = schedule['id']
        self.name = name
        self.address = address
        self.currentSchedule = []
        self._tries = 0
        self.parent = polyglot.getNode(primary)

        polyglot.subscribe(polyglot.START, self.start, address)

    def start(self):
        self.update_info(force=True,queryAPI=True)

    def discover(self, command=None):
        # No discovery needed (no nodes are subordinate to Flex Schedules)
        pass

    def update_info(self, force=False, queryAPI=True):
        LOGGER.info("%s %s", self.address, self.name)
        _running = False #initialize variable so that it could be used even if there was not a need to update the running status of the schedule
        try:
            _deviceInfo = self.device.getDeviceInfo(force=queryAPI)
            for s in _deviceInfo['flexScheduleRules']:
                _sched_id = str(s['id'])
                if _sched_id == self.schedule_id:
                    self.schedule = s
                    break
            
            self.currentSchedule = self.device.getCurrentSchedule(force=queryAPI)

        except Exception as ex:
            LOGGER.error(' Error retrieving flex schedule info for "%s"', self.name, str(ex))
            return False
        
        # ST -> Status (whether Rachio schedule is running a schedule or not)
        try:
            if 'scheduleRuleId' in self.currentSchedule:
                _running = (self.currentSchedule['scheduleRuleId'] == self.schedule_id)
                self.setDriver('ST',(0,100)[_running])
            else:
                self.setDriver('ST',0)
        except Exception as ex:
            LOGGER.error('Error updating current schedule running status on %s Rachio FlexSchedule. %s', self.name, str(ex))

        # GV0 -> "Enabled"
        try:
            self.setDriver('GV0',int(self.schedule['enabled']))
        except Exception as ex:
            LOGGER.error('Error updating enable status on %s Rachio FlexSchedule. %s', self.name, str(ex))

        # GV2 -> duration (minutes)
        try:
            _seconds = float(self.schedule['totalDuration'])
            _minutes = int(_seconds / 60.)
            self.setDriver('GV2', _minutes)
        except Exception as ex:
            LOGGER.error('Error updating total duration on %s Rachio FlexSchedule. %s', self.name, str(ex))
      
        if force: self.reportDrivers()

    def query(self, command = None):
        LOGGER.info('query command received on %s Rachio Flex Schedule', self.name)
        self.update_info(force=True,queryAPI=True)
        return True

    drivers = [{'driver': 'ST', 'value': 0, 'uom': 78}, #Running (On/Off)
               {'driver': 'GV0', 'value': 0, 'uom': 2}, #Enabled (True/False)
               {'driver': 'GV2', 'value': 0, 'uom': 45} #Duration (Minutes)
               ]

    id = 'rachio_flexschedule'
    commands = {'QUERY': query}
    
if __name__ == "__main__":
    try:
        polyglot = Interface([])
        polyglot.start(VERSION)
        polyglot.updateProfile()
        polyglot.setCustomParamsDoc()
        control = Controller(polyglot, 'controller', 'controller', 'Ranchio')
        polyglot.runForever()
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)

