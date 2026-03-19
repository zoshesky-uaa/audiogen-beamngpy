from beamngpy.sensors import Damage, RoadsSensor, Electrics
import const
from time import sleep

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
        self.dispatcher.send_sync(self.simulation.vehicle_controller.switch_to_driver)
        if ai:
            self.normal_behavior()
        print("Driver connected.") 
        self.electrics = Electrics()
        self.dispatcher.send_sync(self.driver.sensors.attach, "electrics", self.electrics)
        self.damage = Damage()
        self.dispatcher.send_sync(self.driver.sensors.attach, "damage", self.damage)
        self.roads_sensor = self.dispatcher.send_sync(
            RoadsSensor,
            "roads_sensor",
            self.simulation.beamng,
            self.driver,
            is_send_immediately=True
        )

        # Keep running across warmup reset; wait_next handles on/off transitions.
        while (self.tick.frame_index < const.END_FRAME) and (not self.tick.shutdown.is_set()):
            self.driver_poll()
            sleep(const.TICK_DURATION_SECONDS/3)
    
    def normal_behavior(self):
        if self.simulation.current_time != "noon":
            self.dispatcher.send(self.driver.set_lights, headlights=1)
        self.dispatcher.send(self.driver.ai.set_aggression, 0.2)
        self.dispatcher.send(self.driver.ai.drive_in_lane, True)
        self.dispatcher.send(self.driver.ai.set_speed, 15.65, mode="limit")
        self.dispatcher.send(self.driver.ai.set_mode, "traffic")

    def driver_poll(self):
        def _snapshot_driver_state():
            self.driver.sensors.poll()
            state = self.driver.state if isinstance(self.driver.state, dict) else {}
            velocity = tuple(v * 2.237 for v in state.get('vel', (0.0, 0.0, 0.0)))
            steering = self.electrics.get('steering', 0.0)
            braking = self.electrics.get('brake', 0.0)
            damage = self.damage.get('damage', 0.0)
            road_data = self.roads_sensor.poll()
            return velocity, steering, braking, damage, road_data

        velocity, steering, braking, damage, road_data = self.dispatcher.send_sync(_snapshot_driver_state)
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