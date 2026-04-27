import math
import random

import const


class VehicleSoundEvent:
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
        if vehicle_ref is None:
            self.empty_action()
            return
        self.run()

    def empty_action(self):
        self.main_tick.waited_action_iterate(self.write_reset)

    def run(self):
        self.main_tick.waited_action(self.normal_behavior)
        action = lambda: random.choices(
            [self.random_empty, self.random_siren_event],
            weights=[0.50, 0.50],
            k=1,
        )[0]()
        self.main_tick.waited_action_iterate(action)

    def normal_behavior(self):
        if not getattr(self.vehicle_ref, "alive", True):
            return
        self.vehicle_ref.vehicle.set_lights(lightbar=0)
        self.vehicle_ref.vehicle.ai.set_mode("traffic")
        self.vehicle_ref.vehicle.ai.set_aggression(0.1)
        self.vehicle_ref.vehicle.ai.drive_in_lane(True)

    def _has_position_data(self):
        return (
            getattr(self.vehicle_ref, "alive", True)
            and getattr(self.driver_ref, "alive", True)
            and getattr(self.vehicle_ref, "state_available", True)
            and getattr(self.driver_ref, "state_available", True)
        )

    def random_siren_event(self):
        if not self._has_position_data():
            self.write_reset()
            return
        distance = self.position_data()
        event_end_frame = self.main_tick.frame_index + math.floor(
            random.uniform(10 * const.TICK_RATE, 60 * const.TICK_RATE)
        )

        action = None
        if distance < 400 and distance != 0:
            print(
                f"CE({self.class_index}), TE({self.track_index}): "
                f"Starting siren event at recording frame {self.main_tick.frame_index}, "
                f"at distance {distance:.2f} m."
            )
            self.vehicle_ref.vehicle.set_lights(lightbar=2)
            behaviors = [
                lambda: self.follow(event_end_frame),
                lambda: (
                    self.vehicle_ref.vehicle.ai.set_mode("random"),
                    self.vehicle_ref.vehicle.ai.set_aggression(0.1),
                    self.vehicle_ref.vehicle.ai.drive_in_lane(True),
                ),
            ]
            random.choices(behaviors, weights=[0.5, 0.5], k=1)[0]()
            action = self.write_event
        else:
            print(
                f"CE({self.class_index}), TE({self.track_index}): "
                f"Starting light follow at recording frame {self.main_tick.frame_index}, "
                f"at distance {distance:.2f} m."
            )
            self.vehicle_ref.vehicle.set_lights(lightbar=0)
            self.follow(event_end_frame)
            self.write_reset()

        self.main_tick.waited_action_iterate(action, max_frame=event_end_frame)

    def random_empty(self):
        if not getattr(self.vehicle_ref, "alive", True) or not getattr(self.driver_ref, "alive", True):
            self.write_reset()
            return
        self.normal_behavior()
        print(f"CE({self.class_index}), TE({self.track_index}): Starting empty event at recording frame {self.main_tick.frame_index}.")
        event_end_frame = self.main_tick.frame_index + math.floor(
            random.uniform(5 * const.TICK_RATE, 30 * const.TICK_RATE)
        )
        self.write_reset()
        self.main_tick.waited_action_iterate(max_frame=event_end_frame)

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

    def follow(self, end_frame):
        if not self._has_position_data():
            return
        follower_state = self.vehicle_ref.state
        followed_state = self.driver_ref.state
        duration = max(0.0, (end_frame - self.main_tick.frame_index) * const.TICK_DURATION_SECONDS)

        wp1 = {
            "x": follower_state.position[0],
            "y": follower_state.position[1],
            "z": follower_state.position[2],
            "t": 0.0,
        }
        wp_mid = {
            "x": (follower_state.position[0] + followed_state.position[0]) * 0.5,
            "y": (follower_state.position[1] + followed_state.position[1]) * 0.5,
            "z": (follower_state.position[2] + followed_state.position[2]) * 0.5,
            "t": duration * 0.5,
        }
        wp2 = {
            "x": followed_state.position[0],
            "y": followed_state.position[1],
            "z": followed_state.position[2],
            "t": duration,
        }

        self.vehicle_ref.vehicle.ai.set_script([wp1, wp_mid, wp2])

    def write_event(self):
        if self.main_tick.shutdown.is_set():
            return
        position = self.position_data(relative=True)
        msg = (self.main_tick.frame_index, position[0], position[1], position[2])
        self.fsm.labelqueue[self.class_index][self.track_index].append(msg)

    def write_reset(self):
        if self.main_tick.shutdown.is_set():
            return
        msg = (self.main_tick.frame_index, 0.0, 0.0, 0.0)
        self.fsm.labelqueue[self.class_index][self.track_index].append(msg)
