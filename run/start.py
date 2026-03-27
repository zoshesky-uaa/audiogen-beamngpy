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
        # BeamNGpy connection setup
        self.beamng = BeamNGpy(
            host="localhost",        
            port=25252,           
            home=const.BEAMNG_LOCATION,
            debug=True
        )

        # Helper recursion check for BeamNG connection
        def open_beamng(counter):
            try:
                self.beamng.open(launch=True)
            except BNGDisconnectedError:
                print("Retrying connection...")
                sleep(3)
                counter += 1
                if counter >= 10:
                    self.beamng.close()
                    raise RuntimeError("Could not connect to BeamNG")
                open_beamng(counter)

        open_beamng(0)

        # Sets the simulation run at 120 step or 120 frames per second
        # Graphics update, physics updates are a confusing matter but I want to make sure the polling rate is relatively high
        self.beamng.settings.set_steps_per_second(120) 

        # A flag to state the simulation is on, used for dispatcher thread
        self.on = True

        # Serializes calls for BeamNG, with a check for the simulation being on
        self.dispatcher = dispatcher.Dispatcher(lambda: self.on)
        self.dispatcher_thread = threading.Thread(target=self.dispatcher.run, daemon=True)
        self.dispatcher_thread.start()

    # Selects a random weather preset, not sure about all the options
    def random_weather_setup(self):
        weather_presets = ['clear', 'cloudy', 'rainy', 'stormy', 'foggy']  
        self.current_weather = random.choice(weather_presets)  
        self.dispatcher.send(self.beamng.env.set_weather_preset, self.current_weather, time=5)

    # Selects a random time of day for simulation
    def random_tod_setup(self):
        time_presets =  ['morning', 'noon', 'evening', 'night'] 
        self.current_time = random.choice(time_presets)
        match self.current_time:
            case 'evening': self.dispatcher.send(self.beamng.env.set_tod, 0.25)
            case 'night': self.dispatcher.send(self.beamng.env.set_tod, 0.5)
            case 'morning': self.dispatcher.send(self.beamng.env.set_tod, 0.75)
            case 'noon': self.dispatcher.send(self.beamng.env.set_tod, 1)

    # Converts the simulation to imperial units
    def convert_to_imperial(self):
        self.dispatcher.send(self.beamng.settings.change, 'speedUnits', 'mph')
        self.dispatcher.send(self.beamng.settings.change, 'distanceUnits', 'mi')
        self.dispatcher.send(self.beamng.settings.apply_graphics)

    # Does cleanup for existing scenarios that exists (unlikely) and does cleanup for their files (likely)
    def clean_scenario_startup(self, scenario_name, level_name):
        try:  
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
        # Intializes the vehicle controller, which handles location spawns based on the environment
        self.vehicle_controller = vehicles.builder(simulation=self)

        # Name of current simulation and environment from the controller
        scenario_name = f'Scenario_{count}'  
        level_name = self.vehicle_controller.environment.name

        # Cleanup from previous scenarios with same name and environment
        self.clean_scenario_startup(scenario_name, level_name)

        # Intializes the scenario and adds driver vehicle to it
        self.scenario = Scenario(level_name, scenario_name) 
        self.vehicle_controller.driver_presetup()

        # Initializes the scheduler and appends the driver to it
        self.event_schedular = scheduler.Scheduler(self) 
        self.event_schedular.append_event(0, ai=ai)

        #Send sync for blocking each step to ensure they're loaded in order
        self.dispatcher.send_sync(self.scenario.make, self.beamng)
        self.dispatcher.send_sync(self.beamng.scenario.load, self.scenario)
        self.dispatcher.send_sync(self.beamng.scenario.start)
        self.dispatcher.send_sync(self.beamng.control.pause)

        # Setups conditions for the scenario
        self.random_weather_setup()
        self.random_tod_setup()
        self.convert_to_imperial()
        print("Scenario started.")

        # Spawns traffic and emergency vehicles
        self.simulation_traffic_setup()
    
    def simulation_traffic_setup(self):
        # Gets current vehicles in the simulation
        pre_vehiclelist = self.dispatcher.send_sync(self.beamng.vehicles.get_current)
        # Type check for vehicles dict, repeated a few times 
        if isinstance(pre_vehiclelist, dict) and all(isinstance(v, Vehicle) for v in pre_vehiclelist.values()):
            # Spawns a random number of traffic vehicles based on the constants defined, reduce to 0 for quicker testing
            n_amount = random.randint(const.MINIMUM_TRAFFIC_VEHICLES, const.MAXIMUM_TRAFFIC_VEHICLES)
            # n_parked = random.randint(5, 10)
            # Traffic vehicle count + driver
            total = n_amount + 1

            # Automatic traffic, this is asynchronous spawn and needs checks
            self.dispatcher.send(self.beamng.traffic.spawn, max_amount=n_amount)

            print("Number of traffic vehicles: " + str(n_amount) + ". Setting up traffic vehicles.")
            
            # Unsafe check for spawn completion
            while len(self.dispatcher.send_sync(self.beamng.vehicles.get_current)) <  (total):
                sleep(1)

            vehiclelist = self.dispatcher.send_sync(self.beamng.vehicles.get_current)
            if isinstance(vehiclelist, dict) and all(isinstance(v, Vehicle) for v in vehiclelist.values()):
                # Assuming only one vehicle was spawned this will remove the driver vehicle
                pre_vehicle_id = next(iter(pre_vehiclelist.keys()))  
                traffic = {k: v for k, v in vehiclelist.items() if k != pre_vehicle_id}
            
                for vid in traffic:
                    vehicle = vehiclelist[vid]
                    try: 
                        self.dispatcher.send_sync(vehicle.connect, self.beamng, tries=10)
                        self.event_schedular.append_event(1, vehicle)
                    except Exception as e:
                        print(f"Failed to connect vehicle {vid}: {e}")
                        self.dispatcher.send(self.beamng.vehicles.despawn, vehicle)
                        continue
        
        # Spawns a random number of emergency vehicles based on the constants defined
        n_sirens = random.randint(const.MINIMUM_EMERGENCY_VEHICLES, const.MAXIMUM_EMERGENCY_VEHICLES)
        print("Number of emergency vehicles: " + str(n_sirens) + ". Setting up emergency vehicles.")
        
        # Emergency Vehicle (Siren)
        for i in range(n_sirens):
            # Custom spawn for specifically emergency vehicles
            # Note: Finding a non-static spawning method for these emergency vehicles would be ideal
            vehicle = self.vehicle_controller.emergency_vehicle_spawn()
            try: 
                self.dispatcher.send_sync(vehicle.connect, self.beamng, tries=20)
                self.event_schedular.append_event(3, vehicle)
            except Exception as e:
                print(f"Failed to connect vehicle {vehicle.vid}: {e}")
                self.dispatcher.send(self.beamng.vehicles.despawn, vehicle)
                continue
            
        # Empty vehicles for wrting resets, useful for data debugging
        # for i in range(const.MINIMUM_EMERGENCY_VEHICLES - n_sirens):
        #     self.event_schedular.append_event(3, None)

    # Stops all events, deletes the scenario, and despawns all vehicles if possible
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

    # Closes the connection to BeamNG and stops the dispatcher thread that recieves the commands
    def close(self):
        self.dispatcher.send(self.beamng.close)
        sleep(5)
        self.on = False
        self.dispatcher_thread.join(timeout=10.0)
        