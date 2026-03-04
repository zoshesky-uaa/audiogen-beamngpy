from beamngpy import BeamNGpy, Scenario
from beamngpy.logging import BNGDisconnectedError
import time
from spawns import vehicles

class Simulation:
    def __init__(self):
        self.beamng = BeamNGpy(
            host="localhost",        
            port=25252,           
            home=r"E:\BeamNG.tech.v0.38.3.0"  
        )
        while True: 
            try:
                self.beamng.open(launch=True)
                break
            except BNGDisconnectedError:  
                print("Retrying connection...")  
                time.sleep(5)
        self.beamng.settings.set_nondeterministic() 
        self.vehicle_controller = vehicles.builder(simulation=self)
        self.scenario = Scenario(self.vehicle_controller.environment.name, 'example')

        '''
        available = self.beamng.vehicles.get_available()
        # prepare a log file next to the script
        log_path = Path(__file__).parent / "vehicle_catalog.txt"
        with open(log_path, "w", encoding="utf-8") as logf:
            # Access the nested 'vehicles' dictionary
            vehicles_dict = available['vehicles']
            for key in vehicles_dict.keys():
                vehicle_data = vehicles_dict[key]
                line = f"Vehicle: {vehicle_data['name']}"
                logf.write(line + "\n")
                if 'configurations' in vehicle_data:
                    cfg_line = f"  Configurations: {vehicle_data['configurations']}"
                    logf.write(cfg_line + "\n")   
        '''

    def start_scenario(self, ai=True):
        self.vehicle_controller.spawn_driver()
        self.scenario.make(self.beamng)
        self.beamng.scenario.load(self.scenario)

    
    def close(self):
        self.beamng.close()