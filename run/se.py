# Tick system to ensure synchronization for data collection
from time import sleep
import threading
import math
import random

"""
SoundEvent class to represent audio events in the simulation
Class Events:
1 = Vehicle Presence/Tires
2 = Horn
3 = Siren
"""

class VehicleSoundEvent:
    def __init__(self, class_index, track_index, beanmgpy, vehicle, driver, FSM, tick=None):
        self.class_index = class_index
        self.track_index = track_index
        self.beamngpy = beanmgpy
        self.vehicle = vehicle
        self.driver = driver
        self.FSM = FSM
        self.active_event = False
        self.position = (0, 0, 0)
        # optional shared tick controller; assigned by caller if available
        self.tick = tick
    
    def random_siren_event(self):
        # Random duration between 10-60 seconds with 100ms hops
        print("Starting random siren event...")
        end_frame = self.tick.frame_index + math.floor(random.uniform(50, 600))
        self.vehicle.set_lights(lightbar=2)

        self.active_event = True
        self.write_event()

        while self.tick.frame_index < end_frame:
            self.tick.wait_next()
            self.write_event()

        self.vehicle.set_lights(lightbar=0)
        self.active_event = False

    def random_empty(self):
        # Random duration between 5-30 seconds with 100ms hops
        print("Starting random empty event...")
        end_frame = self.tick.frame_index + math.floor(random.uniform(50, 300))

        self.active_event = True
        
        while self.tick.frame_index < end_frame:
            self.tick.wait_next()

        self.active_event = False

    def relative_position_data(self):
        self.driver.sensors.poll()  
        self.vehicle.sensors.poll()     
        origin_position = self.driver.state['pos']  
        sound_position = self.vehicle.state['pos']
                
        dx = origin_position[0] - sound_position[0]
        dy = origin_position[1] - sound_position[1]
        dz = origin_position[2] - sound_position[2]
        magnitude = math.sqrt(dx**2 + dy**2 + dz**2)

        if magnitude > 0:
            self.position = (dx / magnitude, dy / magnitude, dz / magnitude)
        else:
            self.position = (0.0, 0.0, 0.0)
    
    def write_event(self):
        self.relative_position_data()
        self.FSM.write_event_csv(self)       

    '''
    # Horns can't be triggered via BeamNGpy
    def random_honk_event(self):
        # Random duration between 0.5-3 seconds with 100ms hops
        end_frame = self.frame_index + math.floor(random.uniform(50, 300))
    '''


def thread_queue(count, funcs, args):
    threads = []
    for i in range(count):
        tick = threading.Event()
        thread = threading.Thread(target=funcs[i], args=(args[i], tick), daemon=True)
        threads.append((thread, tick))
        thread.start()
    return threads