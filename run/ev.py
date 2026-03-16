import math
import random
import const

"""
SoundEvent class to represent audio events in the simulation
Class Events:
1 = Other Vehicles Prescence
2 = Horn
3 = Siren
"""

class VehicleSoundEvent:
    def __init__(self, 
                 class_index, 
                 track_index, 
                 simulation, 
                 fsm,
                 vehicle, 
                 tick):
        
        self.class_index = class_index
        self.track_index = track_index
        self.simulation = simulation
        self.fsm = fsm
        self.vehicle = vehicle
        self.tick = tick
        self.run()
 

    def run(self):
        self.vehicle.set_license_plate("EV")
        self.tick.waited_action(self.normal_behavior)
        while self.tick.frame_index < const.END_FRAME and not self.tick.shutdown.is_set():
            chosen = random.choices([self.random_empty, self.random_siren_event],
                                    weights=[0.70, 0.30], k=1)[0]
            chosen()

    def normal_behavior(self):
        self.vehicle.set_lights(lightbar=0)
        self.vehicle.ai.set_aggression(0.3)
        self.vehicle.ai.drive_in_lane(True)
        self.vehicle.ai.set_speed(15.65, mode="limit")
        self.vehicle.ai.set_mode("traffic")

    def abnormal_behavior(self):
        self.vehicle.set_lights(lightbar=2)
        self.vehicle.ai.set_aggression(0.4)
        self.vehicle.ai.drive_in_lane(True)
        self.vehicle.ai.set_speed(45, mode="limit")
        behaviors = [  
            lambda: self.vehicle.ai.set_target(self.simulation.vehicle_controller.driver.vid, mode="chase"),  
            lambda: self.vehicle.ai.set_mode("random")  
        ]  
        behavior = random.choices(behaviors, weights=[0.5, 0.5], k=1)[0]  
        behavior()

    def random_siren_event(self):
        position = self.position_data()
        if (position < 300):
            self.abnormal_behavior()

            # Random duration between 10-60 seconds with 100ms hops
            print(f"CE({self.class_index}), TE({self.track_index}): Starting siren event at frame {self.tick.frame_index}, at distance {position:.2f} m.")
            event_end_frame = self.tick.frame_index + math.floor(random.uniform(10*const.TICK_RATE, 60*const.TICK_RATE))

            self.tick.waited_action_iterate(self.write_event, self.tick.frame_index, event_end_frame)

    def random_empty(self):
        self.normal_behavior()

        # Random duration between 5-30 seconds with 100ms hops
        print(f"CE({self.class_index}), TE({self.track_index}): Starting empty event at frame {self.tick.frame_index}.")
        event_end_frame = self.tick.frame_index + math.floor(random.uniform(5*const.TICK_RATE, 30*const.TICK_RATE))
        
        self.tick.waited_action_iterate(self.write_reset, self.tick.frame_index, event_end_frame)

    def position_data(self, relative=False):
        self.simulation.vehicle_controller.driver.sensors.poll()  
        self.vehicle.sensors.poll()     
        origin_position = self.simulation.vehicle_controller.driver.state['pos']  
        sound_position = self.vehicle.state['pos']
                
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
        self.fsm.write_soundevent_csv(self.track_index, position)       
    
    def write_reset(self):
        self.fsm.write_soundevent_csv(self.track_index, (0.0, 0.0, 0.0))

    '''
    # Horns can't be triggered via BeamNGpy
    def random_honk_event(self):
        # Random duration between 0.5-3 seconds with 100ms hops
        end_frame = self.frame_index + math.floor(random.uniform(50, 300))
    '''