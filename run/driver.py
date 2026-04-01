class DriverRecorder:
    def __init__(self,
                 fsm, 
                 simulation,
                 vehicle_update_tick,
                 main_tick,
                 ai=True):
        self.driver_ref = simulation.vehicle_controller.driver_ref
        self.dispatcher = simulation.dispatcher
        self.fsm = fsm
        self.vehicle_update_tick = vehicle_update_tick
        self.main_tick = main_tick
        self.simulation = simulation
        self.run(ai=ai)


    def run(self, ai=True):
        # Delays until warmup is started
        self.main_tick.waited_action()
        # Forces simulation to switch current camera (including the audio listener) back to the driver, sort of a hack
        self.dispatcher.send_sync(self.simulation.vehicle_controller.switch_to_driver)
        #Write a else case for this for manual control parameters in the future
        if ai:
            self.normal_behavior()
        print("Driver connected.")   
        

    def normal_behavior(self):
        # Sets some "normal" conditions for the vehicle
        if self.simulation.current_time != "noon":
            self.dispatcher.send(self.driver_ref.vehicle.set_lights, headlights=1)
        self.dispatcher.send(self.driver_ref.vehicle.ai.set_mode, "traffic")
        self.dispatcher.send(self.driver_ref.vehicle.ai.set_aggression, 0.2)
        self.dispatcher.send(self.driver_ref.vehicle.ai.drive_in_lane, True)
            