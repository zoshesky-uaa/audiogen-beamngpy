from time import sleep
import math
import random

"""
SoundEvent class to represent audio events in the simulation
Class Events:
1 = Other Vehicles Prescence
2 = Horn
3 = Siren
"""

class VehicleSoundEvent:
    def __init__(self, class_index, track_index, simulation, fsm, tick):
        self.class_index = class_index
        self.track_index = track_index
        self.simulation = simulation
        self.fsm = fsm
        self.active_event = False
        self.tick = tick
        match class_index:
            case 1:
                self.vehicle = simulation.vehicle_controller.spawn_other_vehicle()
            case 3:
                self.vehicle = simulation.vehicle_controller.spawn_EV()
                self.ev_run()
            case _: return
        

    def ev_run(self):
        from run import scheduler
        while self.tick.frame_index < scheduler.END_FRAME:
            print(f"CE({self.class_index}), TE({self.track_index}): Not active. Choosing next...")
            chosen = random.choices([self.random_empty, self.random_siren_event],
                                    weights=[0.75, 0.25], k=1)[0]
            chosen()
            sleep(0.1)
        self.simulation.remove_vehicle(self.vehicle)
            
    def random_siren_event(self):
        # Random duration between 10-60 seconds with 100ms hops
        print(f"CE({self.class_index}), TE({self.track_index}): Starting siren event...")
        event_end_frame = self.tick.frame_index + math.floor(random.uniform(50, 600))

        self.vehicle.set_lights(lightbar=2)
        self.write_event()

        while self.tick.frame_index < event_end_frame:
            self.tick.wait_next()
            self.write_event()

        self.vehicle.set_lights(lightbar=0)

    def random_empty(self):
        # Random duration between 5-30 seconds with 100ms hops
        print(f"CE({self.class_index}), TE({self.track_index}): Starting empty event...")
        event_end_frame = self.tick.frame_index + math.floor(random.uniform(50, 300))
        
        while self.tick.frame_index < event_end_frame:
            self.tick.wait_next()

    def relative_position_data(self):
        self.simulation.vehicle_controller.driver.sensors.poll()  
        self.vehicle.sensors.poll()     
        origin_position = self.simulation.vehicle_controller.driver.state['pos']  
        sound_position = self.vehicle.state['pos']
                
        dx = origin_position[0] - sound_position[0]
        dy = origin_position[1] - sound_position[1]
        dz = origin_position[2] - sound_position[2]
        magnitude = math.sqrt(dx**2 + dy**2 + dz**2)

        if magnitude > 0:
            return (dx / magnitude, dy / magnitude, dz / magnitude)
        else:
            return (0.0, 0.0, 0.0)
    
    def write_event(self):
        position = self.relative_position_data()
        self.fsm.write_event_csv(self.class_index, self.track_index, position, self.tick.frame_index)       

    '''
    # Horns can't be triggered via BeamNGpy
    def random_honk_event(self):
        # Random duration between 0.5-3 seconds with 100ms hops
        end_frame = self.frame_index + math.floor(random.uniform(50, 300))
    '''




