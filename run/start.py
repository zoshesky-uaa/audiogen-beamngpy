from beamngpy import BeamNGpy, Scenario, Vehicle
from beamngpy.logging import BNGDisconnectedError
from run import scheduler, dispatcher
import threading
from spawns import vehicles
from time import sleep
import random
import const

class Simulation:
    def __init__(self):
        self.beamng = BeamNGpy(
            host="localhost",        
            port=25252,           
            home=const.BEAMNG_LOCATION,
        )
        while True: 
            try:
                self.beamng.open(launch=True)
                break
            except BNGDisconnectedError:  
                print("Retrying connection...")  
                sleep(5)
        #self.beamng.settings.set_nondeterministic() 
        self.beamng.settings.set_steps_per_second(120) 
        self.on = True
        self.dispatcher = dispatcher.Dispatcher(lambda: self.on)
        self.dispatcher_thread = threading.Thread(target=self.dispatcher.run, daemon=True)
        self.dispatcher_thread.start()

    def random_weather_setup(self):
        weather_presets = ['clear', 'cloudy', 'rainy', 'stormy', 'foggy']  
        self.current_weather = random.choice(weather_presets)  
        self.dispatcher.send(self.beamng.env.set_weather_preset, self.current_weather, time=5)

    def random_tod_setup(self):
        time_presets =  ['morning', 'noon', 'evening', 'night'] 
        self.current_time = random.choice(time_presets)
        match self.current_time:
            case 'evening': self.dispatcher.send(self.beamng.env.set_tod, 0.25)
            case 'night': self.dispatcher.send(self.beamng.env.set_tod, 0.5)
            case 'morning': self.dispatcher.send(self.beamng.env.set_tod, 0.75)
            case 'noon': self.dispatcher.send(self.beamng.env.set_tod, 1)

    def convert_to_imperial(self):
        self.dispatcher.send(self.beamng.settings.change, 'units_speed', 'mph')
        self.dispatcher.send(self.beamng.settings.change, 'units_distance', 'mi')
        self.dispatcher.send(self.beamng.settings.apply_graphics)

    def clean_scenario_startup(self, scenario_name, level_name):
        try:  
            # Stop current scenario if running  
            if self.beamng._scenario:  
                self.beamng.scenario.stop()  
        except:  
            pass  

        try:  
            scenarios = self.beamng.scenario.get_level_scenarios(level_name)  
            for scenario in scenarios:  
                if scenario.name == scenario_name:  
                    scenario.delete(self.beamng)  
                    print(f"Deleted existing scenario: {scenario_name}")  
                    break  
        except Exception as e:  
            print(f"Failed to delete scenario {scenario_name}: {e}")  

    def scenario_setup(self, count, ai=True):
        print("Starting scenario " + str(count) + "...")
        self.vehicle_controller = vehicles.builder(simulation=self)
        scenario_name = f'Scenario_{count}'  
        level_name = self.vehicle_controller.environment.name
        self.clean_scenario_startup(scenario_name, level_name)
        self.scenario = Scenario(level_name, scenario_name) 
        self.event_schedular = scheduler.Scheduler(self) 
        
        self.vehicle_controller.driver_presetup()
        self.event_schedular.append_event(0, ai=ai)
        #Send sync for blocking each step
        self.dispatcher.send_sync(self.scenario.make, self.beamng)
        self.dispatcher.send_sync(self.beamng.scenario.load, self.scenario)
        self.dispatcher.send_sync(self.beamng.scenario.start)
        self.dispatcher.send_sync(self.beamng.control.pause)

        self.random_weather_setup()
        self.random_tod_setup()
        self.convert_to_imperial()
        print("Scenario started.")

        self.simulation_traffic_setup()
    
    def simulation_traffic_setup(self):
        # ---- Return values needed (send/sync)---- #
        pre_vehiclelist = self.dispatcher.send_sync(self.beamng.vehicles.get_current)
        if isinstance(pre_vehiclelist, dict) and all(isinstance(v, Vehicle) for v in pre_vehiclelist.values()):
            n_amount = random.randint(const.MINIMUM_TRAFFIC_VEHICLES, const.MAXIMUM_TRAFFIC_VEHICLES)
            #n_parked = random.randint(5, 10)
            total = n_amount + 1

            # Automatic traffic, blocking
            self.dispatcher.send_sync(self.beamng.traffic.spawn, max_amount=n_amount)

            print("Number of traffic vehicles: " + str(n_amount) + ". Setting up traffic vehicles.")
            # Unsafe
            while len(self.dispatcher.send_sync(self.beamng.vehicles.get_current)) <  (total):
                sleep(1)

            vehiclelist = self.dispatcher.send_sync(self.beamng.vehicles.get_current)
            if isinstance(vehiclelist, dict) and all(isinstance(v, Vehicle) for v in vehiclelist.values()):
                traffic = vehiclelist.keys() - pre_vehiclelist.keys()
                
                for vid in traffic:
                    vehicle = vehiclelist[vid]
                    try: 
                        self.dispatcher.send_sync(vehicle.connect, self.beamng, tries=20)
                        self.event_schedular.append_event(1, vehicle)
                    except Exception as e:
                        print(f"Failed to connect vehicle {vid}: {e}")
                        self.dispatcher.send(self.beamng.vehicles.despawn, vehicle)
                        continue
            
        n_sirens = random.randint(const.MINIMUM_EMERGENCY_VEHICLES, const.MAXIMUM_EMERGENCY_VEHICLES)
        print("Number of emergency vehicles: " + str(n_sirens) + ". Setting up emergency vehicles.")
        
        # Emergency Vehicle (Siren)
        for i in range(n_sirens):
            vehicle = self.vehicle_controller.emergency_vehicle_spawn()
            try: 
                self.dispatcher.send_sync(vehicle.connect, self.beamng, tries=20)
                self.event_schedular.append_event(3, vehicle)
            except Exception as e:
                print(f"Failed to connect vehicle {vehicle.vid}: {e}")
                self.dispatcher.send(self.beamng.vehicles.despawn, vehicle)
                continue

    
    def scenario_cleanup(self):
        if hasattr(self, 'event_schedular'):
            self.event_schedular.stop_all()
            self.event_schedular = None
        if hasattr(self, 'scenario'):
            self.dispatcher.send(self.beamng.scenario.stop)
            self.dispatcher.send(self.scenario.delete, self.beamng)
            self.scenario = None  
        if hasattr(self, 'vehicle_controller'):
            self.dispatcher.send(self.vehicle_controller.reset)
            self.vehicle_controller = None


    def close(self):
        self.dispatcher.send(self.beamng.close)
        sleep(10)
        self.on = False
        self.dispatcher_thread.join(timeout=10.0)
        