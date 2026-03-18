from beamngpy.sensors import Damage, RoadsSensor, Electrics
import const

class DriverRecorder:
    def __init__(self,
                 driver,
                 dispatcher, 
                 fsm, 
                 tick,
                 simulation,
                 ai=True):
        self.driver = driver
        self.dispatcher = dispatcher
        self.fsm = fsm
        self.tick = tick
        self.simulation = simulation
        self.run(ai=ai)

    def run(self, ai=True):
        self.tick.waited_action()
        #Write a else case for this for manual control in the future
        self.dispatcher.send(self.simulation.vehicle_controller.switch_to_driver)
        if ai:
            self.normal_behavior()
        print("Driver connected.") 
        self.electrics = Electrics()
        self.dispatcher.send(self.driver.sensors.attach, "electrics", self.electrics)  
        self.damage = Damage()
        self.dispatcher.send(self.driver.sensors.attach,"damage", self.damage)
        self.roads_sensor = self.dispatcher.send_sync(RoadsSensor, "roads_sensor", self.simulation.beamng, self.driver, is_send_immediately=True) 
        self.tick.waited_action_iterate(self.driver_poll)
    
    def normal_behavior(self):
        if self.simulation.current_time != "noon":
            self.dispatcher.send(self.driver.set_lights, headlights=1)
        self.dispatcher.send(self.driver.ai.set_aggression, 0.2)
        self.dispatcher.send(self.driver.ai.drive_in_lane, True)
        self.dispatcher.send(self.driver.ai.set_speed, 15.65, mode="limit")
        self.dispatcher.send(self.driver.ai.set_mode, "traffic")

    def driver_poll(self):
        self.dispatcher.send_sync(self.driver.sensors.poll)
        velocity = tuple(v * 2.237 for v in  self.driver.state['vel']) # Convert m/s to mph
        steering = self.electrics['steering']
        braking = self.electrics['brake']
        damage = self.damage['damage']
        road_data = self.dispatcher.send_sync(self.roads_sensor.poll)
        if not isinstance(road_data, dict):  
            # Sensor not ready yet - skip or use default values  
            lane_center = lane_right = lane_left = lane_halfwidth = 0.0 
            lane_data = (lane_center, lane_right, lane_left, lane_halfwidth) 
        else:  
            # Sensor ready - use dictionary format  
            lane_center = road_data["dist2CL"] * 3.281  
            lane_right = road_data["dist2Right"] * 3.281  
            lane_left = road_data["dist2Left"] * 3.281  
            lane_halfwidth = road_data["halfWidth"] * 3.281  
            lane_data = (lane_center, lane_right, lane_left, lane_halfwidth) # Convert m to ft
        self.fsm.write_driver_csv(velocity, steering, braking, lane_data, damage)