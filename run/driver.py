from beamngpy.sensors import Damage, RoadsSensor, Electrics
import const
from time import sleep, time

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
        self.speed_limit = 0.0

    def run(self, ai=True):
        # Delays until warmup is started
        self.tick.waited_action()
        # Forces simulation to switch current camera (including the audio listener) back to the driver, sort of a hack
        self.dispatcher.send_sync(self.simulation.vehicle_controller.switch_to_driver)
        #Write a else case for this for manual control parameters in the future
        if ai:
            self.normal_behavior()
        print("Driver connected.")   
        
        # Attaches additional sensors to the driver vehicle for data collection per request
        # Trying to catch potential error conditions
        try:
            self.electrics = Electrics()
            self.dispatcher.send_sync(self.driver.sensors.attach, "electrics", self.electrics)
            self.damage = Damage()
            self.dispatcher.send_sync(self.driver.sensors.attach, "damage", self.damage)
            self.roads_sensor = self.dispatcher.send_sync(
                RoadsSensor,
                name="roads_sensor",
                bng=self.simulation.beamng,
                vehicle=self.driver
            )
        except Exception as e:
            raise Exception("Error in driver recorder: " + str(e))
        
        # Starts loop to poll driver sensors every tick
        while not self.tick.shutdown.is_set():
            self.driver_poll()
            sleep(const.TICK_DURATION_SECONDS/2)
    
    def normal_behavior(self):
        # Sets some "normal" conditions for the vehicle
        if self.simulation.current_time != "noon":
            self.dispatcher.send(self.driver.set_lights, headlights=1)
        self.dispatcher.send(self.driver.ai.set_mode, "traffic")
        self.dispatcher.send(self.driver.ai.set_aggression, 0.2)
        self.dispatcher.send(self.driver.ai.drive_in_lane, True)
                

    def driver_poll(self):
        if not self.driver.is_connected():  
            start_time = time()  
            while not self.driver.is_connected():  
                if time() - start_time > 5.0:  # 5 second timeout  
                    print("Reconnection timeout")  
                    return  
                if self.tick.shutdown.is_set():  
                    return  
                try:  
                    self.driver.connect(self.simulation.beamng)  
                    break  
                except Exception: 
                    print("Reconnection attempt failed, retrying...") 
                    sleep(0.1)  
            
        def _snapshot_driver_state(): 
            try:  
                failed = False
                self.driver.sensors.poll('state', 'electrics')
                state = self.driver.state if isinstance(self.driver.state, dict) else {}  
                raw_velocity = state.get('vel', (0.0, 0.0, 0.0))  
                velocity = tuple(v * 2.237 for v in raw_velocity)
                
                steering = self.electrics.get('steering', 0.0)  
                braking = self.electrics.get('brake', 0.0)  
                damage = self.damage.get('damage', 0.0)  

                road_data = self.roads_sensor.poll()  

                if isinstance(road_data, dict) and road_data:
                    latest_time = max(road_data.keys())  
                    latest_reading = road_data[latest_time]  
                    lane_center = latest_reading["dist2CL"] * 3.281  
                    lane_right = latest_reading["dist2Right"] * 3.281    
                    lane_left = latest_reading["dist2Left"] * 3.281  
                    lane_halfwidth = latest_reading["halfWidth"] * 3.281  
                    lane_data = (lane_center, lane_right, lane_left, lane_halfwidth)  
                    speed_limit = road_data['speedLimit'] 
                else:  
                    lane_data = (0.0, 0.0, 0.0, 0.0)
                    speed_limit = 0.0
                    failed = True  
            except BaseException as e:  
                if 'velocity' not in locals():
                    velocity = (0.0, 0.0, 0.0)
                if 'steering' not in locals():
                    steering = 0.0
                if 'braking' not in locals():
                    braking = 0.0
                if 'damage' not in locals():
                    damage = 0.0
                if 'lane_data' not in locals():
                    lane_data = (0.0, 0.0, 0.0, 0.0)
                if 'speed_limit' not in locals():
                    speed_limit = 0.0
                failed = True

            return velocity, steering, braking, damage, lane_data, speed_limit, failed

        velocity, steering, braking, damage, lane_data, speed_limit, failed = self.dispatcher.send_sync(_snapshot_driver_state)

        if not failed:
            if (self.speed_limit != speed_limit) and (speed_limit > 0):
                self.speed_limit = speed_limit
                self.driver.ai.set_speed(speed_limit*2.237, mode="limit")
                print(f"New speed limit: {self.speed_limit} mph")
            # Do something here
            pass