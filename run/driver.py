import const
from time import sleep, time
import numpy as np
class DriverRecorder:
    def __init__(self,
                 fsm, 
                 tick,
                 simulation,
                 ai=True):
        self.driver = simulation.vehicle_controller.driver
        self.dispatcher = simulation.dispatcher
        self.fsm = fsm
        self.tick = tick
        self.simulation = simulation
        self.previous_velocity = (0.0, 0.0, 0.0)
        self.previous_time = None
        self.run(ai=ai)
        #self.speed_limit = 0.0


    def run(self, ai=True):
        # Delays until warmup is started
        self.tick.waited_action()
        # Forces simulation to switch current camera (including the audio listener) back to the driver, sort of a hack
        self.dispatcher.send_sync(self.simulation.vehicle_controller.switch_to_driver)
        #Write a else case for this for manual control parameters in the future
        if ai:
            self.normal_behavior()
        print("Driver connected.")   
        
        # Starts loop to poll driver sensors every tick
        self.previous_time = time()
        while not self.tick.shutdown.is_set():
            #self.driver_poll()
            sleep(0.1)
    
    def normal_behavior(self):
        # Sets some "normal" conditions for the vehicle
        if self.simulation.current_time != "noon":
            self.dispatcher.send(self.driver.set_lights, headlights=1)
        self.dispatcher.send(self.driver.ai.set_mode, "traffic")
        self.dispatcher.send(self.driver.ai.set_aggression, 0.2)
        self.dispatcher.send(self.driver.ai.drive_in_lane, True)
                

    def driver_poll(self):           
        def _snapshot_driver_state(): 
            try:  
                failed = False
                current_time = time() 
                self.driver.sensors.poll('electrics', 'damage')
    
                steering = self.simulation.vehicle_controller.driver_electrics.get('steering', 0.0)  
                braking = self.simulation.vehicle_controller.driver_electrics.get('brake', 0.0)  
                damage = self.simulation.vehicle_controller.driver_damage.get('damage', 0.0)  

                imu_data = self.simulation.vehicle_controller.driver_imu_sensor.poll()
                if isinstance(imu_data, dict) and imu_data:
                    acceleration = np.array(imu_data['accSmooth']) 
                    dt = current_time - self.previous_time
                    velocity = self.previous_velocity + acceleration * dt
                else:
                    velocity = self.previous_velocity
                    failed = True

                road_data = self.simulation.vehicle_controller.driver_roads_sensor.poll()  
                if isinstance(road_data, dict) and road_data:
                    latest_time = max(road_data.keys())  
                    latest_reading = road_data[latest_time]  
                    lane_center = latest_reading["dist2CL"] * 3.281  
                    lane_right = latest_reading["dist2Right"] * 3.281    
                    lane_left = latest_reading["dist2Left"] * 3.281  
                    lane_halfwidth = latest_reading["halfWidth"] * 3.281  
                    lane_data = (lane_center, lane_right, lane_left, lane_halfwidth)  
                    #speed_limit = road_data['speedLimit'] 
                else:  
                    lane_data = (0.0, 0.0, 0.0, 0.0)
                    #speed_limit = 0.0
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
                #if 'speed_limit' not in locals():
                    #speed_limit = 0.0
                failed = True

            return velocity, steering, braking, damage, lane_data, failed, #speed_limit
        try:
            velocity, steering, braking, damage, lane_data, failed = self.dispatcher.send_sync(_snapshot_driver_state, timeout=const.TICK_DURATION_SECONDS/1.5)
        except TimeoutError:
            failed = True

        if not failed:
            #if (self.speed_limit != speed_limit) and (speed_limit > 0):
                #self.speed_limit = speed_limit
                #self.driver.ai.set_speed(speed_limit*2.237, mode="limit")
                #print(f"New speed limit: {self.speed_limit} mph")
            # Do something here
            pass