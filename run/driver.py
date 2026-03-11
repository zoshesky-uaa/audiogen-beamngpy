from time import sleep

class DriverRecorder:
    def __init__(self, 
                 simulation, 
                 fsm, 
                 tick,
                 ai=True):
        self.simulation = simulation
        self.fsm = fsm
        self.tick = tick
        self.vehicle = simulation.vehicle_controller.driver_presetup()
        self.wait(ai=ai)
    
    def wait(self, ai=True):
        self.tick.wait_next()
        self.simulation.vehicle_controller.switch_to_driver()
        if ai:
            self.normal_behavior()
        print("Driver connected.")
        self.run()
        #if not ai:
    
    def normal_behavior(self):
        self.vehicle.ai.set_aggression(0.2)
        self.vehicle.ai.drive_in_lane(True)
        self.vehicle.ai.set_speed(15.65, mode="limit")
        self.vehicle.ai.set_mode("traffic")

    def run(self):
        from run import scheduler
        while self.tick.frame_index < scheduler.END_FRAME and not self.tick.shutdown.is_set():
            sleep(0.1)