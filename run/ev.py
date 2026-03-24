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
                                    weights=[0.80, 0.20], k=1)[0])

    def normal_behavior(self):
        self.dispatcher.send(self.vehicle.set_lights, lightbar=0)
        self.dispatcher.send(self.vehicle.ai.set_mode, "traffic")
        self.dispatcher.send(self.vehicle.ai.set_aggression, 0.1)
        self.dispatcher.send(self.vehicle.ai.drive_in_lane, True)
        #self.dispatcher.send(self.vehicle.ai.set_speed, 15.65, mode="limit")


    def abnormal_behavior(self, end_frame):
        self.dispatcher.send(self.vehicle.set_lights, lightbar=2)
        behaviors = [  
            lambda: self.follow(end_frame),  
            lambda: (
                self.dispatcher.send(self.vehicle.ai.set_mode, "random"),  
                self.dispatcher.send(self.vehicle.ai.set_aggression, 0.1),
                self.dispatcher.send(self.vehicle.ai.drive_in_lane, True)        
            )
        ]  
        behavior = random.choices(behaviors, weights=[0.5, 0.5], k=1)[0]  
        behavior()
        #self.dispatcher.send(self.vehicle.ai.set_speed, 45, mode="limit")

    def light_follow(self, end_frame):
        self.dispatcher.send(self.vehicle.set_lights, lightbar=0)
        self.follow(end_frame)
        #self.dispatcher.send(self.vehicle.ai.set_speed, 45, mode="limit")

    def random_siren_event(self):
        position, failed = self.position_data()
        if failed:
            print(f"CE({self.class_index}), TE({self.track_index}): Failed to get position data for siren event.")
            return
        # Random duration between 10-60 seconds with 100ms hops
        event_end_frame = self.tick.frame_index + math.floor(random.uniform(10*const.TICK_RATE, 60*const.TICK_RATE))

        if (position < 400):
            self.abnormal_behavior(event_end_frame)
            print(f"CE({self.class_index}), TE({self.track_index}): Starting siren event at frame {self.tick.frame_index}, at distance {position:.2f} m.")
            while (self.tick.frame_index < event_end_frame) and (not self.tick.shutdown.is_set()):
                self.write_event()
                sleep(const.TICK_DURATION_SECONDS/3)
        else:
            self.light_follow(event_end_frame)
            print(f"CE({self.class_index}), TE({self.track_index}): Starting light follow at frame {self.tick.frame_index}, at distance {position:.2f} m.")
            while (self.tick.frame_index < event_end_frame) and (not self.tick.shutdown.is_set()):
                self.write_reset()
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


    def follow(self , end_frame):
        def _snapshot_following():
            try:  
                failed = False
                self.driver.sensors.poll()
                self.vehicle.sensors.poll()
                follower_state = self.driver.state if isinstance(self.driver.state, dict) else {}
                followed_state = self.vehicle.state if isinstance(self.vehicle.state, dict) else {}
                follower_pos = follower_state.get('pos', (0.0, 0.0, 0.0))
                followed_pos = followed_state.get('pos', (0.0, 0.0, 0.0))
                followed_vel = followed_state.get('vel', (0.0, 0.0, 0.0))
                
            except:
                print("Error occurred while snapshotting EV positions.")
                follower_pos = (0.0, 0.0, 0.0)
                followed_pos = (0.0, 0.0, 0.0)
                followed_vel = (0.0, 0.0, 0.0)
                failed = True
            return follower_pos, followed_pos, followed_vel,  failed
        
        follower_pos, followed_pos, followed_vel, failed = self.dispatcher.send_sync(_snapshot_following)
       
        if not failed:
            wp1 = {  
                'x': follower_pos[0],  
                'y': follower_pos[1],   
                'z': follower_pos[2],  
                't': 0.0  
            }  

            wp2 = {  
                'x': followed_pos[0]+followed_vel[0],  
                'y': followed_pos[1]+followed_vel[1],   
                'z': followed_pos[2]+followed_vel[2],  
                't': (const.TICK_DURATION_SECONDS*end_frame- self.tick.frame_index*const.TICK_DURATION_SECONDS)  
            }

            self.vehicle.ai.drive_using_waypoints(  
                wp_target_list=[wp1, wp2],  
                aggression=0.5,  
                avoid_cars=True,  
                drive_in_lane=False,  
            )  

    def write_event(self):
        position, failed = self.position_data(relative=True)
        if not failed:
            self.fsm.write_soundevent_csv(self.class_index, self.track_index, position)       
    
    def write_reset(self):
        self.fsm.write_soundevent_csv(self.class_index, self.track_index, (0.0, 0.0, 0.0))