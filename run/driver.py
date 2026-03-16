from beamngpy.sensors import Damage, RoadsSensor, Electrics
import const

class DriverRecorder:
    def __init__(self, 
                 simulation, 
                 fsm, 
                 tick,
                 ai=True):
        self.simulation = simulation
        self.fsm = fsm
        self.tick = tick
        self.vehicle = simulation.vehicle_controller.driver
        self.wait(ai=ai)
    
    def wait(self, ai=True):
        self.tick.waited_action()
        #Write a else case for this for manual control in the future
        self.simulation.vehicle_controller.switch_to_driver()
        if ai:
            self.normal_behavior()
        print("Driver connected.") 
        self.electrics = Electrics()
        self.vehicle.sensors.attach("electrics", self.electrics)  
        self.damage = Damage()
        self.vehicle.sensors.attach("damage", self.damage)
        self.roads_sensor = RoadsSensor("roads_sensor", self.simulation.beamng, self.vehicle, is_send_immediately=True) 
        self.run()
        #if not ai:
    
    def normal_behavior(self):
        if self.simulation.current_time != "noon":
            self.vehicle.set_lights(headlights=1)
        self.vehicle.ai.set_aggression(0.2)
        self.vehicle.ai.drive_in_lane(True)
        self.vehicle.ai.set_speed(15.65, mode="limit")
        self.vehicle.ai.set_mode("traffic")

    def run(self):
        ref_frame = 0
        while not self.tick.shutdown.is_set():
            self.driver_poll()
            frame = self.tick.wait_next(ref_frame)
            if frame is None:
                break
            ref_frame = frame


    def driver_poll(self):
        self.vehicle.sensors.poll()
        velocity = tuple(v * 2.237 for v in self.vehicle.state['vel']) # Convert m/s to mph
        steering = self.electrics['steering']
        braking = self.electrics['brake']
        damage = self.damage['damage']
        road_data = self.roads_sensor.poll()
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