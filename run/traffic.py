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
                 simulation, 
                 class_index, 
                 track_index,  
                 fsm, 
                 vehicle_ref,
                 vehicle_update_tick,
                 main_tick):
        self.class_index = class_index
        self.track_index = track_index
        self.vehicle_update_tick = vehicle_update_tick
        self.main_tick = main_tick
        self.fsm = fsm
        # Catch for empty vehicles to let them send empty resets
        if vehicle_ref is None:
            self.empty_action()
            return
        self.simulation = simulation
        self.driver_ref = simulation.vehicle_controller.driver_ref
        self.vehicle_ref = vehicle_ref
        self.run()
 
    def empty_action(self):
        #self.tick.waited_action_iterate(self.write_reset)
        return

    def run(self):
        self.main_tick.waited_action(self.normal_behavior)
        # No behavior set here currently
        #self.main_tick.waited_action_iterate()

    def normal_behavior(self):
        self.vehicle_ref.vehicle.ai.set_mode("traffic")
        self.vehicle_ref.vehicle.ai.set_aggression(0.2)
        self.vehicle_ref.vehicle.ai.drive_in_lane(True)

    '''
    # Horns can't be triggered directly via BeamNGpy, we will need to use Lua GE commands for this
    def random_honk_event(self):
        # Random duration between 0.5-3 seconds with 100ms hops
        end_frame = self.frame_index + math.floor(random.uniform(50, 300))
    '''




