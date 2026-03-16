import math
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
        self.vehicle.set_license_plate("TRAFFIC")
        self.tick.waited_action(self.normal_behavior)
        self.tick.waited_action_iterate()

    def normal_behavior(self):
        self.vehicle.ai.set_aggression(0.2)
        self.vehicle.ai.drive_in_lane(True)
        self.vehicle.ai.set_speed(15.65, mode="limit")
        self.vehicle.ai.set_mode("traffic")

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




