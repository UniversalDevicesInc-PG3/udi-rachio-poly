
from udi_interface import Node,LOGGER

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
