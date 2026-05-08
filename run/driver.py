from beamngpy.sensors import Damage  

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
        damage_sensor = Damage()
        self.driver_ref.vehicle.sensors.attach("damage", damage_sensor)
        self.run(ai=ai)

    def run(self, ai=True):
        self.main_tick.waited_action()
        if self.main_tick.shutdown.is_set() or not getattr(self.driver_ref, "alive", True):
            return
        self.simulation.beamng.vehicles.switch(self.driver_ref.vehicle)
        if ai:
            self.normal_behavior()
        print("Driver connected.")
        self.main_tick.waited_action_iterate(self.damage_check)

    def normal_behavior(self):
        if not getattr(self.driver_ref, "alive", True):
            return
        if self.simulation.current_time != "noon":
            self.driver_ref.vehicle.set_lights(headlights=1)
        self.driver_ref.vehicle.ai.set_mode("traffic")
        self.driver_ref.vehicle.ai.set_aggression(0.2)
        self.driver_ref.vehicle.ai.drive_in_lane(True)

    def damage_check(self):
        self.driver_ref.vehicle.sensors.poll() 
        damage_data = self.driver_ref.vehicle.sensors['damage']  
        damage_value = damage_data.get('damage', 0)  
        if damage_value > 0.01:
            self.simulation.invalidate_trial(f"Driver damaged, test invalidated.", stop_run=True)

