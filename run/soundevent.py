import math
import random
import const
from run import exceptions

class VehicleSoundEvent:
    PERCEPTIBILITY_THRESHOLD = 0.01
    AUDIO_MIN_DISTANCE = 10.0  # Distance where volume is at 100%
    AUDIO_MAX_DISTANCE = 450.0 # Distance where volume hits 0% (500m is the max in BeamNG)
    ROLLOFF_FACTOR = 1.0
    PERCEPTIABLE = True

    def __init__(
        self,
        simulation,
        class_index,
        track_index,
        fsm,
        vehicle_ref,
        vehicle_update_tick,
        main_tick,
    ):
        self.class_index = class_index
        self.track_index = track_index
        self.vehicle_update_tick = vehicle_update_tick
        self.main_tick = main_tick
        self.fsm = fsm
        self.simulation = simulation
        self.driver_ref = simulation.vehicle_controller.driver_ref
        self.vehicle_ref = vehicle_ref
        self._chase_frozen = False  
        if vehicle_ref is None:
            self.empty_action()
            return
        self.run()

    def empty_action(self):
        self.main_tick.waited_action_iterate(self.write_reset)

    def run(self):
        self.main_tick.waited_action(self.normal_behavior)
        action = lambda: random.choices(
            [self.random_empty, self.random_sound_event],
            weights=[0.50, 0.50],
            k=1)[0]()
        self.main_tick.waited_action_iterate(action)

    @exceptions.interruptable
    def normal_behavior(self):
        match self.class_index:
            case 99:
                self.vehicle_ref.vehicle.queue_lua_command("electrics.horn(false)", False)
            case 0 | 1 | 2: 
                self.vehicle_ref.vehicle.set_lights(lightbar=0)
                self.vehicle_ref.vehicle.ai.set_mode("traffic")
                self.vehicle_ref.vehicle.ai.set_aggression(0.2)
                self.vehicle_ref.vehicle.ai.drive_in_lane(True)

    def _has_position_data(self):
        return (
            getattr(self.vehicle_ref, "state_available", True)
            and getattr(self.driver_ref, "state_available", True)
        )
    
    def _wait_for_position(self):
        print(f"CE({self.class_index}), TE({self.track_index}): Waiting for position data to become available...")
        while not self._has_position_data():
            self.main_tick.wait_next(self.main_tick.frame_index)
        return True
    
    def random_empty(self):
        if not getattr(self.vehicle_ref, "alive", True) or not getattr(self.driver_ref, "alive", True):
            return
        print(f"CE({self.class_index}), TE({self.track_index}): Starting empty event at recording frame {self.main_tick.frame_index}.")
        # 12 seconds to 24 seconds
        event_end_frame = self.main_tick.frame_index + math.floor(
            random.uniform(4 * const.t_prime, 8 * const.t_prime)
        )

        self.main_tick.waited_action_iterate(max_frame=event_end_frame)

    def random_sound_event(self):
        if not self._wait_for_position():
            return
        current_frame = self.main_tick.frame_index     
        distance = self.position_data()

        if distance < self.AUDIO_MAX_DISTANCE and distance != 0:
            match self.class_index:
                case 0 | 1 | 2:
                    print(
                        f"CE({self.class_index}), TE({self.track_index}): "
                        f"Starting siren event at recording frame {current_frame}, "
                        f"at distance {distance:.2f} m."
                    )
                    # 12 seconds to 30 seconds
                    event_end_frame = current_frame + math.floor(
                        random.uniform(4 * const.t_prime, 10 * const.t_prime)
                    )
                    self.vehicle_ref.vehicle.set_lights(lightbar=2)
                    self.vehicle_ref.vehicle.ai.drive_in_lane(False)
                case 99:
                    print(
                        f"CE({self.class_index}), TE({self.track_index}): "
                        f"Starting horn event at recording frame {current_frame}, "
                        f"at distance {distance:.2f} m."
                    )
                    # 3 seconds to 9 seconds
                    event_end_frame = current_frame + math.floor(
                        random.uniform(1 * const.t_prime, 3 * const.t_prime)
                    )
                    if (self.beamng_cmd_check()):
                        self.vehicle_ref.vehicle.queue_lua_command("electrics.horn(true)", False) 
                case _:
                    pass
            self.random_follow(event_end_frame)
        else:
            print(
                f"CE({self.class_index}), TE({self.track_index}): "
                f"Starting light follow at recording frame {current_frame}, "
                f"at distance {distance:.2f} m."
            )
            self.chase_follow()

        self.normal_behavior() 
        self.write_reset()
    
    @exceptions.interruptable
    def position_data(self, relative=False):
        if not self._has_position_data():
            return (0.0, 0.0, 0.0) if relative else 0.0
        current_state = self.vehicle_ref.state
        current_state_driver = self.driver_ref.state
        dx = current_state_driver.position[0] - current_state.position[0]
        dy = current_state_driver.position[1] - current_state.position[1]
        dz = current_state_driver.position[2] - current_state.position[2]
        magnitude = math.sqrt(dx**2 + dy**2 + dz**2)
        if relative and magnitude > 0.0:
            return (dx / magnitude, dy / magnitude, dz / magnitude)
        if relative:
            return (0.0, 0.0, 0.0)
        return magnitude
    
    @exceptions.interruptable
    def chase_follow(self):
        self.vehicle_ref.vehicle.ai.set_target(self.driver_ref.vehicle.vid, mode="chase")

        def chase_step():
            if not self._has_position_data():
                return True
            distance = self.position_data()
            audibility = self.calculate_estimated_audibility(distance)
            if audibility > self.PERCEPTIBILITY_THRESHOLD:
                return False
        
        while (chase_step()):
            self.main_tick.wait_next()


    @exceptions.interruptable
    def _update_random_event(self):
        distance = self.position_data()
        if distance <= 0.0:
            return

        audibility = self.calculate_estimated_audibility(distance)
        if audibility > self.PERCEPTIBILITY_THRESHOLD:
            self.write_event() # Keeps your original hardcoded 1.0 SED message
            self.PERCEPTIABLE = True
            return
        
        # If the sound drops below the threshold, it is physically inaudible.
        if not self.PERCEPTIABLE:
            return
        
        # The exact tick the sound vanishes, write the 0.0 reset.
        self.write_reset() 
        self.PERCEPTIABLE = False

    @exceptions.interruptable
    def random_follow(self, end_frame):
        if not self._has_position_data():
            return
        self.PERCEPTIABLE = True
        self.vehicle_ref.vehicle.ai.set_mode("random")

        def random_step():
            self._update_random_event()

        self.main_tick.waited_action_iterate(random_step, max_frame=end_frame)

    def calculate_estimated_audibility(self, distance):
        if distance <= self.AUDIO_MIN_DISTANCE:
            return 1.0  # 100% volume inside the minimum distance radius
            
        if distance >= self.AUDIO_MAX_DISTANCE:
            return 0.0  # Completely culled by FMOD's max distance limit

        inverse_volume = self.AUDIO_MIN_DISTANCE / (
            self.AUDIO_MIN_DISTANCE + self.ROLLOFF_FACTOR * (distance - self.AUDIO_MIN_DISTANCE)
        )
        
        fade_range = 50.0
        if distance > (self.AUDIO_MAX_DISTANCE - fade_range):
            fade_multiplier = (self.AUDIO_MAX_DISTANCE - distance) / fade_range
            inverse_volume *= fade_multiplier
        return max(0.0, min(1.0, inverse_volume))

    @exceptions.interruptable
    def write_event(self):
        position = self.position_data(relative=True)
        doa_msg = (self.main_tick.frame_index, self.class_index, self.track_index, position[0], position[1], position[2])
        sed_msg = (self.main_tick.frame_index, self.class_index, self.track_index, 1.0)
        self.fsm.doa_queue.append(doa_msg)
        self.fsm.sed_queue.append(sed_msg)

    @exceptions.interruptable
    def write_reset(self):
        reset_frame = self.main_tick.frame_index + 1
        if reset_frame > (const.label_max-1):
            return
        doa_msg = (reset_frame, self.class_index, self.track_index, 0.0, 0.0, 0.0)
        sed_msg = (reset_frame, self.class_index, self.track_index, 0.0)
        self.fsm.doa_queue.append(doa_msg)
        self.fsm.sed_queue.append(sed_msg)

