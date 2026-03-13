from beamngpy import BeamNGpy, Scenario
from beamngpy.logging import BNGDisconnectedError
from run.scheduler import Scheduler
from spawns import vehicles
from time import sleep
import random
import const

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
    def random_weather_setup(self):
        weather_presets = ['clear', 'cloudy', 'rainy', 'stormy', 'foggy']  
        self.current_weather = random.choice(weather_presets)  
        self.beamng.env.set_weather_preset(self.current_weather, time=0)  

    def random_tod_setup(self):
        time_presets =  ['morning', 'noon', 'evening', 'night'] 
        self.current_time = random.choice(time_presets)
        match self.current_time:
            case 'evening': self.beamng.env.set_tod(0.25)
            case 'night': self.beamng.env.set_tod(0.5)     
            case 'morning': self.beamng.env.set_tod(0.75)
            case 'noon': self.beamng.env.set_tod(1)

    def convert_to_imperial(self):
        self.beamng.settings.change('units_speed', 'mph')   
        self.beamng.settings.change('units_distance', 'mi')   
        self.beamng.settings.apply_graphics()

    def scenario_setup(self, count, ai=True):
        
        print("Starting scenario " + str(count) + "...")

        self.vehicle_controller = vehicles.builder(simulation=self)
        self.scenario = Scenario(self.vehicle_controller.environment.name, ('Scenario ' + str(count)))
        self.event_schedular = Scheduler(self) 

        self.vehicle_controller.driver_presetup()
        self.event_schedular.append_event(0, ai=ai)
        self.scenario.make(self.beamng)
        self.beamng.scenario.load(self.scenario)
        self.beamng.scenario.start()
        self.beamng.control.pause()

        self.random_weather_setup()
        self.random_tod_setup()
        self.convert_to_imperial()
        print("Scenario started.")

        self.simulation_traffic_setup()
    
    def simulation_traffic_setup(self):
        pre_vehicles = set(self.beamng.vehicles.get_current().keys())
        n_amount = random.randint(const.MINIMUM_TRAFFIC_VEHICLES, const.MAXIMUM_TRAFFIC_VEHICLES)
        #n_parked = random.randint(5, 10)
        total = n_amount + 1

        # Automatic traffic
        self.beamng.traffic.spawn(max_amount=n_amount)

        print("Number of traffic vehicles: " + str(n_amount) + ". Setting up traffic vehicles.")
        while len(self.beamng.vehicles.get_current()) <  (total):
            sleep(1)

        traffic = self.beamng.vehicles.get_current().keys() - pre_vehicles

        for vid in traffic:
            vehicle = self.beamng.vehicles.get_current()[vid]
            try: 
                vehicle.connect(self.beamng, tries=20)
                self.event_schedular.append_event(1, vehicle)
            except Exception as e:
                print(f"Failed to connect vehicle {vid}: {e}")
                self.beamng.vehicles.despawn(vehicle)
                continue

        n_sirens = random.randint(const.MINIMUM_EMERGENCY_VEHICLES, const.MAXIMUM_EMERGENCY_VEHICLES)
        print("Number of emergency vehicles: " + str(n_sirens) + ". Setting up emergency vehicles.")
        
        # Emergency Vehicle (Siren)
        for i in range(n_sirens):
            vehicle = self.vehicle_controller.emergency_vehicle_spawn()
            try: 
                vehicle.connect(self.beamng, tries=20)
                self.event_schedular.append_event(3, vehicle)
            except Exception as e:
                print(f"Failed to connect vehicle {vehicle.vid}: {e}")
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