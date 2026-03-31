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
                 vehicle, 
                 tick):
        self.class_index = class_index
        self.track_index = track_index
        self.tick = tick
        self.fsm = fsm
        # Catch for empty vehicles to let them send empty resets
        if vehicle is None:
            self.empty_action()
            return
        self.simulation = simulation
        self.dispatcher = simulation.dispatcher
        self.driver = simulation.vehicle_controller.driver
        self.vehicle = vehicle
        self.run()
 
    def empty_action(self):
        self.tick.waited_action_iterate(self.write_reset)

    def run(self):
        # Delays until warmup is started
        self.tick.waited_action(self.normal_behavior)
        self.imu_sensor = self.dispatcher.send_sync(
            AdvancedIMU,
            name="imu_sensor_" + str(self.class_index) + "_" + str(self.track_index),
            bng=self.simulation.beamng,
            vehicle=self.vehicle
        )       
        # Lambda to select either an empty event or sirent event, passed to waited_action_iterate
        action = lambda: random.choices([self.random_empty, self.random_siren_event],
                                    weights=[0.50, 0.50], k=1)[0]()
        self.tick.waited_action_iterate(action)

    def normal_behavior(self):
        # Sets some "normal" conditions for the vehicle
        # Lightbar condition is what controls the siren state, 0 is off, 1 is on but not audible, 2 is on and audible.
        self.dispatcher.send(self.vehicle.set_lights, lightbar=0)
        self.dispatcher.send(self.vehicle.ai.set_mode, "traffic")
        self.dispatcher.send(self.vehicle.ai.set_aggression, 0.1)
        self.dispatcher.send(self.vehicle.ai.drive_in_lane, True)
        #self.dispatcher.send(self.vehicle.ai.set_speed, 15.65, mode="limit")

    def random_siren_event(self):
        position, failed = self.position_data()
        if failed:
            print(f"CE({self.class_index}), TE({self.track_index}): Failed to get position data for siren event.")
            return
        
        # Random duration between 10-60 seconds with 100ms hops
        event_end_frame = self.tick.frame_index + math.floor(random.uniform(10*const.TICK_RATE, 60*const.TICK_RATE))
        
        # When the vehicle is within an audible range (not defined exactly) it'll trigger a siren event
        # Otherwise, it writes a reset and simply heads towards the player so its closer for the next event
        action = None
        if (position < 400):
            print(f"CE({self.class_index}), TE({self.track_index}): Starting siren event at frame {self.tick.frame_index}, at distance {position:.2f} m.")
            #Setup random siren behavior here
            self.dispatcher.send(self.vehicle.set_lights, lightbar=2)
            behaviors = [  
                lambda: self.follow(event_end_frame),  
                lambda: (
                    self.dispatcher.send(self.vehicle.ai.set_mode, "random"),  
                    self.dispatcher.send(self.vehicle.ai.set_aggression, 0.1),
                    self.dispatcher.send(self.vehicle.ai.drive_in_lane, True)        
                )
            ]
            behavior = random.choices(behaviors, weights=[0.5, 0.5], k=1)[0]    
            behavior()
            action = lambda: self.write_event()
        else:
            print(f"CE({self.class_index}), TE({self.track_index}): Starting light follow at frame {self.tick.frame_index}, at distance {position:.2f} m.")
            self.dispatcher.send(self.vehicle.set_lights, lightbar=0)
            self.follow(event_end_frame)
            self.write_reset()

        while self.tick.frame_index < event_end_frame and not self.tick.shutdown.is_set():
            if action is not None:
                action()

    def random_empty(self):
        self.normal_behavior()

        # Random duration between 5-30 seconds with 100ms hops
        print(f"CE({self.class_index}), TE({self.track_index}): Starting empty event at frame {self.tick.frame_index}.")
        event_end_frame = self.tick.frame_index + math.floor(random.uniform(5*const.TICK_RATE, 30*const.TICK_RATE))
        self.write_reset()
        self.tick.waited_action_iterate(max_frame=event_end_frame)

    def position_data(self, relative=False):   
        def _snapshot_positions():
            try:  
                failed = False
                vehicle_imu_data = self.imu_sensor.poll()
                driver_imu_data = self.vehicle_controller.driver_imu_sensor.poll()
                if isinstance(vehicle_imu_data, dict) and vehicle_imu_data:
                    sound_position = vehicle_imu_data['pos']
                else:
                    sound_position = (0.0, 0.0, 0.0)
                    failed = True
                if isinstance(driver_imu_data, dict) and driver_imu_data:
                    origin_position = driver_imu_data['pos']
                else:                    
                    origin_position = (0.0, 0.0, 0.0)
                    failed = True
            except:
                print("Error occurred while snapshotting EV positions.")
                origin_position = (0.0, 0.0, 0.0)
                sound_position = (0.0, 0.0, 0.0)
                failed = True
            return origin_position, sound_position, failed
        
        try:
             origin_position, sound_position, failed = self.dispatcher.send_sync(_snapshot_positions, timeout=const.TICK_DURATION_SECONDS/1.5)
        except TimeoutError:
            failed = True

        if not failed:
            dx = origin_position[0] - sound_position[0]
            dy = origin_position[1] - sound_position[1]
            dz = origin_position[2] - sound_position[2]
            magnitude = math.sqrt(dx**2 + dy**2 + dz**2)
            if relative and magnitude > 0.0:
                return ((dx / magnitude, dy / magnitude, dz / magnitude), failed)
            elif relative:
                return ((0.0, 0.0, 0.0), failed)
            else:
                return (magnitude, failed)
        else:
            return ((0.0, 0.0, 0.0) if relative else 0.0, failed)


    def follow(self , end_frame):
        def _snapshot_following():
            try:  
                failed = False
                vehicle_imu_data =self.imu_sensor.poll()
                driver_imu_data = self.vehicle_controller.driver_imu_sensor.poll()
                if isinstance(vehicle_imu_data, dict) and vehicle_imu_data:
                    follower_pos = vehicle_imu_data['pos']
                else:
                    follower_pos = (0.0, 0.0, 0.0)
                    failed = True
                if isinstance(driver_imu_data, dict) and driver_imu_data:
                    followed_pos = driver_imu_data['pos']
                else:                    
                    followed_pos = (0.0, 0.0, 0.0)
                    failed = True
                
            except:
                print("Error occurred while snapshotting EV positions.")
                follower_pos = (0.0, 0.0, 0.0)
                followed_pos = (0.0, 0.0, 0.0)
                failed = True
            return follower_pos, followed_pos, failed
        
        try:
            follower_pos, followed_pos, failed = self.dispatcher.send_sync(_snapshot_following, timeout=const.TICK_DURATION_SECONDS/1.5)
        except TimeoutError:
            failed = True

        if not failed:
            wp1 = {  
                'x': follower_pos[0],  
                'y': follower_pos[1],   
                'z': follower_pos[2],  
                't': 0.0  
            }  

            wp2 = {  
                'x': followed_pos[0],  
                'y': followed_pos[1],   
                'z': followed_pos[2],  
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
            msg = (self.tick.frame_index, self.class_index, position[0], position[1], position[2])
            try:
                self.fsm.labelqueue[self.track_index].put_nowait(msg)
            except queue.Full:
                _ = self.fsm.labelqueue[self.track_index].get_nowait()
                self.fsm.labelqueue[self.track_index].task_done()
                self.fsm.labelqueue[self.track_index].put_nowait(msg)

    
    def write_reset(self):
        msg = (self.tick.frame_index, self.class_index,  0.0, 0.0, 0.0)
        try:
            self.fsm.labelqueue[self.track_index].put_nowait(msg)
        except queue.Full:
            _ = self.fsm.labelqueue[self.track_index].get_nowait()
            self.fsm.labelqueue[self.track_index].task_done()
            self.fsm.labelqueue[self.track_index].put_nowait(msg)