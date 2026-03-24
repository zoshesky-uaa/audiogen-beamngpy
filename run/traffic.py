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
        self.dispatcher.send(self.vehicle.set_license_plate, "TRAFFIC")
        self.tick.waited_action(self.normal_behavior)
        self.tick.waited_action_iterate()

    def normal_behavior(self):
        self.dispatcher.send(self.vehicle.ai.set_mode, "traffic")
        self.dispatcher.send(self.vehicle.ai.set_aggression, 0.1)
        self.dispatcher.send(self.vehicle.ai.drive_in_lane, True)
        #self.dispatcher.send(self.vehicle.ai.set_speed, 15.65, mode="limit")
 

    def position_data(self, relative=False):
        if not self.vehicle.is_connected():  
            print("Vehicle disconnected - attempting reconnection")  
            try:  
                self.vehicle.connect(self.simulation.beamng)  
            except Exception as e:  
                print(f"Reconnection failed: {e}")  
                return  
            
        def _snapshot_positions():
            try:  
                failed = False
                self.driver.sensors.poll()
                self.vehicle.sensors.poll()
                driver_state = self.driver.state if isinstance(self.driver.state, dict) else {}
                vehicle_state = self.vehicle.state if isinstance(self.vehicle.state, dict) else {}
                origin_position = driver_state.get('pos', (0.0, 0.0, 0.0))
                sound_position = vehicle_state.get('pos', (0.0, 0.0, 0.0))
            except:
                print("Error occurred while snapshotting EV positions.")
                origin_position = (0.0, 0.0, 0.0)
                sound_position = (0.0, 0.0, 0.0)
                failed = True
            return origin_position, sound_position, failed
        
        origin_position, sound_position, failed = self.dispatcher.send_sync(_snapshot_positions)
        
        if not failed:
            dx = origin_position[0] - sound_position[0]
            dy = origin_position[1] - sound_position[1]
            dz = origin_position[2] - sound_position[2]
            magnitude = math.sqrt(dx**2 + dy**2 + dz**2)
        else:
            magnitude = (0.0, 0.0, 0.0) if relative else 0.0

        if (magnitude > 0.0) and relative:
            return ((dx / magnitude, dy / magnitude, dz / magnitude), failed)
        elif relative:
            return (0.0, 0.0, 0.0), failed
        else:
            return (magnitude), failed
    
    def write_event(self):
        position, failed = self.position_data(relative=True)
        if not failed:
            self.fsm.write_soundevent_csv(self.class_index, self.track_index, position)       
    
    def write_reset(self):
        self.fsm.write_soundevent_csv(self.class_index, self.track_index, (0.0, 0.0, 0.0))
    
    '''
    # Horns can't be triggered via BeamNGpy
    def random_honk_event(self):
        # Random duration between 0.5-3 seconds with 100ms hops
        end_frame = self.frame_index + math.floor(random.uniform(50, 300))
    '''




