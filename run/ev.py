import math
import random
import const
from time import sleep

"""
SoundEvent class to represent audio events in the simulation
Class Events:
1 = Other Vehicles Prescence
2 = Horn
3 = Siren
"""

class VehicleSoundEvent:
    def __init__(self,
                 driver,
                 dispatcher, 
                 class_index, 
                 track_index, 
                 fsm,
                 vehicle, 
                 tick):
        
        self.class_index = class_index
        self.track_index = track_index
        self.dispatcher = dispatcher
        self.driver = driver
        self.fsm = fsm
        self.vehicle = vehicle
        self.tick = tick
        self.run()
 

    def run(self):
        self.dispatcher.send(self.vehicle.set_license_plate, "EV")
        self.tick.waited_action(self.normal_behavior)
        self.tick.waited_action_iterate(random.choices([self.random_empty, self.random_siren_event],
                                    weights=[0.70, 0.30], k=1)[0])

    def normal_behavior(self):
        self.dispatcher.send(self.vehicle.set_lights, lightbar=0)
        self.dispatcher.send(self.vehicle.ai.set_aggression, 0.3)
        self.dispatcher.send(self.vehicle.ai.drive_in_lane, True)
        self.dispatcher.send(self.vehicle.ai.set_speed, 15.65, mode="limit")
        self.dispatcher.send(self.vehicle.ai.set_mode, "traffic")

    def abnormal_behavior(self):
        self.dispatcher.send(self.vehicle.set_lights, lightbar=2)
        self.dispatcher.send(self.vehicle.ai.set_aggression, 0.4)
        self.dispatcher.send(self.vehicle.ai.drive_in_lane, True)
        self.dispatcher.send(self.vehicle.ai.set_speed, 45, mode="limit")
        behaviors = [  
            lambda: self.dispatcher.send(self.vehicle.ai.set_target, self.driver.vid, mode="chase"),  
            lambda: self.dispatcher.send(self.vehicle.ai.set_mode, "random")  
        ]  
        behavior = random.choices(behaviors, weights=[0.5, 0.5], k=1)[0]  
        behavior()

    def random_siren_event(self):
        position = self.position_data()
        if (position < 400):
            self.abnormal_behavior()

            # Random duration between 10-60 seconds with 100ms hops
            print(f"CE({self.class_index}), TE({self.track_index}): Starting siren event at frame {self.tick.frame_index}, at distance {position:.2f} m.")
            event_end_frame = self.tick.frame_index + math.floor(random.uniform(10*const.TICK_RATE, 60*const.TICK_RATE))
            while (self.tick.frame_index < event_end_frame) and (not self.tick.shutdown.is_set()):
                self.write_event()
                sleep(const.TICK_DURATION_SECONDS/3)

    def random_empty(self):
        self.normal_behavior()

        # Random duration between 5-30 seconds with 100ms hops
        print(f"CE({self.class_index}), TE({self.track_index}): Starting empty event at frame {self.tick.frame_index}.")
        event_end_frame = self.tick.frame_index + math.floor(random.uniform(5*const.TICK_RATE, 30*const.TICK_RATE))
        while (self.tick.frame_index < event_end_frame) and (not self.tick.shutdown.is_set()):
            self.write_reset()
            sleep(const.TICK_DURATION_SECONDS/3)

    def position_data(self, relative=False):
        def _snapshot_positions():
            self.driver.sensors.poll()
            self.vehicle.sensors.poll()
            driver_state = self.driver.state if isinstance(self.driver.state, dict) else {}
            vehicle_state = self.vehicle.state if isinstance(self.vehicle.state, dict) else {}
            origin_position = driver_state.get('pos', (0.0, 0.0, 0.0))
            sound_position = vehicle_state.get('pos', (0.0, 0.0, 0.0))
            return origin_position, sound_position
        
        origin_position, sound_position = self.dispatcher.send_sync(_snapshot_positions)

        dx = origin_position[0] - sound_position[0]
        dy = origin_position[1] - sound_position[1]
        dz = origin_position[2] - sound_position[2]
        magnitude = math.sqrt(dx**2 + dy**2 + dz**2)

        if (magnitude > 0) and relative:
            return (dx / magnitude, dy / magnitude, dz / magnitude)
        elif relative:
            return (0.0, 0.0, 0.0)
        else:
            return (magnitude)
    
    def write_event(self):
        position = self.position_data(relative=True)
        self.fsm.write_soundevent_csv(self.class_index, self.track_index, position)       
    
    def write_reset(self):
        self.fsm.write_soundevent_csv(self.class_index, self.track_index, (0.0, 0.0, 0.0))