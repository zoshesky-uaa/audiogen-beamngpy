from beamngpy import BeamNGpy, Scenario, Vehicle
from beamngpy.logging import BNGDisconnectedError
import time
import random
from pathlib import Path

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
        self.scenario = Scenario('west_coast_usa', 'example')

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

        

    def start_scenario(self):
        self.scenario.make(self.beamng)
        self.beamng.scenario.load(self.scenario)
        self.beamng.scenario.start()

    def random_vehicle(self):
        # Make a list instead due to props being in this list
        #keys = self.beamng.vehicles.get_available().keys()
        #random_key = random.choice(list(keys))
        #vehicle = Vehicle('random_vehicle_' + random_key, model=random_key, licence='PYTHON')
        vehicle = Vehicle('etk800', model='etk800', licence='PYTHON')
        return vehicle

    def vehicle_setup(self, vehicle, location, rotation):
        self.scenario.add_vehicle(vehicle, pos=location, rot_quat=rotation, cling=True)

    def vehicle_connect(self, vehicle):
        if not vehicle.is_connected():  
            vehicle.connect(self.beamng)
        vehicle.ai.set_mode('traffic')

    def random_emergency_vehicle(self):
        return random.choice([
            Vehicle('MD_Ambulance', model='md_series', part_config='vehicles/md_series/md_70_ambulance_4wd.pc', licence='PYTHON'),
            #Vehicle('Ambulance', model='Gavril H-Series H45 Ambulance (A)', licence='PYTHON'),
            #Vehicle('Fire Chief', model='Gavril Roamer Fire Chief (A)', licence='PYTHON'),
            Vehicle('Police', model='fullsize', part_config='vehicles/fullsize/police.pc', licence='PYTHON'),
            #Vehicle('Ambulance', model='Gavril D-Series D45 Ambulance (A)', licence='PYTHON')
        ])
    
    def close(self):
        self.beamng.close()