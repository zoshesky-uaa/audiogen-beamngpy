import math
import random
import const
import queue
from beamngpy.sensors import AdvancedIMU
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
        self.dispatcher = simulation.dispatcher
        self.driver_ref = simulation.vehicle_controller.driver_ref
        self.vehicle_ref = vehicle_ref
        self.run()
 
    def empty_action(self):
        self.main_tick.waited_action_iterate(self.write_reset)

    def run(self):
        # Delays until warmup is started
        self.main_tick.waited_action(self.normal_behavior)    
        # Lambda to select either an empty event or sirent event, passed to waited_action_iterate
        action = lambda: random.choices([self.random_empty, self.random_siren_event],
                                    weights=[0.50, 0.50], k=1)[0]()
        self.main_tick.waited_action_iterate(action)

    def normal_behavior(self):
        # Sets some "normal" conditions for the vehicle
        # Lightbar condition is what controls the siren state, 0 is off, 1 is on but not audible, 2 is on and audible.
        self.dispatcher.send(self.vehicle_ref.vehicle.set_lights, lightbar=0)
        self.dispatcher.send(self.vehicle_ref.vehicle.ai.set_mode, "traffic")
        self.dispatcher.send(self.vehicle_ref.vehicle.ai.set_aggression, 0.1)
        self.dispatcher.send(self.vehicle_ref.vehicle.ai.drive_in_lane, True)
        #self.dispatcher.send(self.vehicle_ref.vehicle.ai.set_speed, 15.65, mode="limit")

    def random_siren_event(self):
        position = self.position_data()
        
        # Random duration between 10-60 seconds with 100ms hops, using vehicle update tick
        event_end_frame = self.vehicle_update_tick.frame_index + math.floor(random.uniform(10*2*const.TICK_RATE, 60*2*const.TICK_RATE))
        
        # When the vehicle is within an audible range (not defined exactly) it'll trigger a siren event
        # Otherwise, it writes a reset and simply heads towards the player so its closer for the next event
        action = None
        if (position < 400):
            print(f"CE({self.class_index}), TE({self.track_index}): Starting siren event at vehicle frame {self.vehicle_update_tick.frame_index}, at distance {position:.2f} m.")
            #Setup random siren behavior here
            self.dispatcher.send(self.vehicle_ref.vehicle.set_lights, lightbar=2)
            behaviors = [  
                lambda: self.follow(event_end_frame),  
                lambda: (
                    self.dispatcher.send(self.vehicle_ref.vehicle.ai.set_mode, "random"),  
                    self.dispatcher.send(self.vehicle_ref.vehicle.ai.set_aggression, 0.1),
                    self.dispatcher.send(self.vehicle_ref.vehicle.ai.drive_in_lane, True)        
                )
            ]
            behavior = random.choices(behaviors, weights=[0.5, 0.5], k=1)[0]    
            behavior()
            action = lambda: self.write_event()
        else:
            print(f"CE({self.class_index}), TE({self.track_index}): Starting light follow at frame {self.tick.frame_index}, at distance {position:.2f} m.")
            self.dispatcher.send(self.vehicle_ref.vehicle.set_lights, lightbar=0)
            self.follow(event_end_frame)
            self.write_reset()

        self.vehicle_update_tick.waited_action_iterate(action)
        

    def random_empty(self):
        self.normal_behavior()
        # Random duration between 5-30 seconds with 100ms hops, using vehicle update tick
        print(f"CE({self.class_index}), TE({self.track_index}): Starting empty event at vehicle frame {self.vehicle_update_tick.frame_index}.")
        event_end_frame = self.vehicle_update_tick.frame_index + math.floor(random.uniform(5*2*const.TICK_RATE, 30*2*const.TICK_RATE))
        self.write_reset()
        self.vehicle_update_tick.waited_action_iterate(max_frame=event_end_frame)

    def position_data(self, relative=False):   
        current_state = self.vehicle_ref.state
        current_state_driver = self.driver_ref.state
        dx = current_state_driver.position[0] - current_state.position[0]
        dy = current_state_driver.position[1] - current_state.position[1]
        dz = current_state_driver.position[2] - current_state.position[2]
        magnitude = math.sqrt(dx**2 + dy**2 + dz**2)
        if relative and magnitude > 0.0:
            return (dx / magnitude, dy / magnitude, dz / magnitude)
        elif relative:
            return (0.0, 0.0, 0.0)
        else:
            return (magnitude)

    def follow(self , end_frame):
        follower_state = self.vehicle_ref.state
        followed_state = self.driver_ref.state
  
        wp1 = {  
            'x': follower_state.position[0],  
            'y': follower_state.position[1],   
            'z': follower_state.position[2],  
            't': 0.0  
        }  

        wp2 = {  
            'x': followed_state.position[0],  
            'y': followed_state.position[1],   
            'z': followed_state.position[2],  
            't': (const.TICK_DURATION_SECONDS*end_frame- self.main_tick.frame_index*const.TICK_DURATION_SECONDS)  
        }

        self.dispatcher.send(self.vehicle_ref.vehicle.ai.drive_using_waypoints,  
            wp_target_list=[wp1, wp2],  
            aggression=0.5,  
            avoid_cars=True,  
            drive_in_lane=False,  
        )  

    def write_event(self):
        position = self.position_data(relative=True)
        msg = (self.main_tick.frame_index, position[0], position[1], position[2])
        self.fsm.labelqueue[self.class_index][self.track_index].append(msg)
    
    def write_reset(self):
        msg = (self.main_tick.frame_index,  0.0, 0.0, 0.0)
        self.fsm.labelqueue[self.class_index][self.track_index].append(msg)