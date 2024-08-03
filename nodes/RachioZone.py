
'''
Parent is the RachioController, but we also need access to the 
Controller class as that's where the r_api exists.
'''

from udi_interface import Node,LOGGER

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
