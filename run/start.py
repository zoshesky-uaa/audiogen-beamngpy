from beamngpy import BeamNGpy, Scenario
from beamngpy.logging import BNGDisconnectedError
from run.scheduler import Scheduler
from spawns import vehicles
from time import sleep
import random


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
                sleep(5)
        self.beamng.settings.set_nondeterministic() 

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
    
    def scenario_setup(self, count, ai=True):
        self.beamng.ui.display_message("Starting scenario " + str(count) + "...")
        self.vehicle_controller = vehicles.builder(simulation=self)
        self.scenario = Scenario(self.vehicle_controller.environment.name, ('Scenario ' + str(count)))
        self.event_schedular = Scheduler(self) 
        #Driver
        self.event_schedular.append_event(0, ai=ai)
        self.scenario.make(self.beamng)
        self.beamng.scenario.load(self.scenario)
        self.beamng.scenario.start()
        self.beamng.control.pause()
        self.beamng.ui.display_message("Scenario started.")
        self.simulation_traffic_setup()
    
    def simulation_traffic_setup(self):
        pre_vehicles = self.beamng.vehicles.get_current().keys()
        n_amount = random.randint(5, 20)
        #n_parked = random.randint(5, 10)
        total = n_amount + 1

        # Automatic traffic
        self.beamng.traffic.spawn(max_amount=n_amount)

        self.beamng.ui.display_message("Number of traffic vehicles: " + str(n_amount) + ". Setting up traffic vehicles.")
        while len(self.beamng.vehicles.get_current()) <  (total):
            sleep(1)

        traffic = self.beamng.vehicles.get_current().keys() - pre_vehicles

        for vid in traffic:
            vehicle = self.beamng.vehicles.get_current()[vid]
            self.event_schedular.append_event(1, vehicle)
            try: 
                vehicle.connect(self.beamng, tries=20)
            except Exception as e:
                print(f"Failed to connect vehicle {vid}: {e}")
                self.beamng.vehicles.despawn(vehicle)
                continue

        n_sirens = random.randint(0, 8)
        self.beamng.ui.display_message("Number of emergency vehicles: " + str(n_sirens) + ". Setting up emergency vehicles.")
        
        # Emergency Vehicle (Siren)
        for i in range(n_sirens):
            vehicle = self.vehicle_controller.emergency_vehicle_spawn()
            self.event_schedular.append_event(3, vehicle)
            try: 
                vehicle.connect(self.beamng, tries=20)
            except Exception as e:
                print(f"Failed to connect vehicle {vid}: {e}")
                self.beamng.vehicles.despawn(vehicle)
                continue
    
    def scenario_cleanup(self):
        if hasattr(self, 'event_schedular'):
            self.event_schedular.stop_all()
            self.event_schedular = None
        if hasattr(self, 'scenario'):
            self.beamng.scenario.stop()
            self.scenario.delete(self.beamng)
            self.scenario = None  
        if hasattr(self, 'vehicle_controller'):
            self.vehicle_controller.reset()
            self.vehicle_controller = None


    def close(self):
        self.beamng.close()