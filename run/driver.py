class DriverRecorder:
    def __init__(
        self,
        fsm,
        simulation,
        vehicle_update_tick,
        main_tick,
        ai=True,
    ):
        self.driver_ref = simulation.vehicle_controller.driver_ref
        self.fsm = fsm
        self.vehicle_update_tick = vehicle_update_tick
        self.main_tick = main_tick
        self.simulation = simulation
        self._next_keep_alive_frame = 0
        self.run(ai=ai)

    def run(self, ai=True):
        self.main_tick.waited_action()
        if self.main_tick.shutdown.is_set() or not getattr(self.driver_ref, "alive", True):
            return
        self.simulation.beamng.vehicles.switch(self.driver_ref.vehicle)
        if ai:
            self.normal_behavior()
        print("Driver connected.")

    def normal_behavior(self):
        if not getattr(self.driver_ref, "alive", True):
            return
        if self.simulation.current_time != "noon":
            self.driver_ref.vehicle.set_lights(headlights=1)
        self.driver_ref.vehicle.ai.set_mode("traffic")
        self.driver_ref.vehicle.ai.set_aggression(0.2)
        self.driver_ref.vehicle.ai.drive_in_lane(True)

