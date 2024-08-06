
from datetime import datetime
from nodes import RachioZone,RachioSchedule,RachioFlexSchedule
from udi_interface import Node,LOGGER
import time

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
            LOGGER.error('Error discovering and adding Zones on Rachio Controller %s (%s): %s',
                         self.name, self.address, str(ex), exc_info=True)
        
        try:
            _schedules = self.device['scheduleRules']
            LOGGER.info('%i Rachio schedules found on "%s" controller. Adding to ISY',
                        len(_schedules), self.name)
            for s in _schedules:
                _sched_id = str(s['id'])
                _sched_addr = self.address + _sched_id[-2:] #construct address for this schedule (mac address of controller appended with last 2 characters of schedule unique id) because ISY limit is 14 characters
                _sched_name = str(s['name'])
                if not self.poly.getNode(_sched_addr):
                    #LOGGER.info('Adding new Rachio Schedule to %s Controller, %s(%s)', self.name, _sched_name, _sched_addr)
                    self.parent.addNodeQueue(RachioSchedule(self.poly, self.address, _sched_addr, _sched_name, s, self.device_id, self, self.parent)) #v2.2.0, updated to add node to queue, rather that adding to ISY immediately
        except Exception as ex:
            _success = False
            LOGGER.error('Error discovering and adding Schedules on Rachio Controller %s (%s): %s',
                         self.name, self.address, str(ex), exc_info=True)

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
            LOGGER.error('Error discovering and adding Flex Schedules on Rachio Controller %s (%s): %s',
                         self.name, self.address, str(ex), exc_info=True)

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
            LOGGER.error('Connection Error on %s Rachio Controller API Request. This could mean an issue with internet connectivity or Rachio servers, normally safe to ignore. %s',
                         self.name, str(ex), exc_info=True)
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
            LOGGER.error('Connection Error on %s Rachio Controller current schedule API Request. This could mean an issue with internet connectivity or Rachio servers, normally safe to ignore. %s',
                         self.name, str(ex), exc_info=True)
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
                self.parent.r_api.device.stop_water(self.device_id)
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

