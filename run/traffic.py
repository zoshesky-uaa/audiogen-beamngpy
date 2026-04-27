import math


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
        self.main_tick.waited_action_iterate(self.write_state)

    def normal_behavior(self):
        if not getattr(self.vehicle_ref, "alive", True):
            return
        self.vehicle_ref.vehicle.ai.set_mode("traffic")
        self.vehicle_ref.vehicle.ai.set_aggression(0.2)
        self.vehicle_ref.vehicle.ai.drive_in_lane(True)

    def _has_position_data(self):
        return (
            getattr(self.vehicle_ref, "alive", True)
            and getattr(self.driver_ref, "alive", True)
            and getattr(self.vehicle_ref, "state_available", True)
            and getattr(self.driver_ref, "state_available", True)
        )

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

    def write_state(self):
        distance = self.position_data()
        if distance < 400 and distance != 0:
            self.write_event()
        else:
            self.write_reset()

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
