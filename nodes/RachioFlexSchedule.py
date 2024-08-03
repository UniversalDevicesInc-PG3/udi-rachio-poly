
from udi_interface import Node,LOGGER

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
