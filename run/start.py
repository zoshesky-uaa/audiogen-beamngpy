from beamngpy import BeamNGpy, Scenario, Vehicle
from beamngpy.logging import BNGDisconnectedError
from run import scheduler, dispatcher, driver
import threading
from spawns import vehicles
from time import sleep, time
import random
import const
from math import ceil
from spawns import west_coast_usa

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
        # A flag to state the simulation is on, used for dispatcher thread
        self.on = True
        
        # Serializes calls for BeamNG, with a check for the simulation being on
        self.dispatcher = dispatcher.Dispatcher(lambda: self.on)
        self.dispatcher_thread = threading.Thread(target=self.dispatcher.run, daemon=True)
        self.dispatcher_thread.start()

    # Selects a random weather preset, not sure about all the options
    def random_weather_setup(self):
        # Get correct presets, some of these dont exist
        weather_presets = ['clear', 'cloudy', 'rainy', 'stormy', 'foggy']  
        #self.current_weather = random.choice(weather_presets)  
        #self.dispatcher.send(self.beamng.env.set_weather_preset, self.current_weather, time=5)

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
        self.dispatcher.send(self.beamng.settings.change, 'uiUnits', 'imperial')
        self.dispatcher.send(self.beamng.settings.change, 'uiUnitLength', 'imperial')
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
        # Environment choice
        self.environment = random.choices([west_coast_usa.builder()],
                                           weights=[1], k=1)[0]
        
        # Scenario setup
        scenario_name = f'Scenario_{count}'  
        level_name = self.environment.name
        self.scenario = Scenario(level_name, scenario_name) 
        self.clean_scenario_startup(scenario_name, level_name)
   
        # Intializes the vehicle controller, which handles location spawns based on the environment
        self.vehicle_controller = vehicles.builder(simulation=self)
   
        # Intializes the scenario and adds driver vehicle to it
        self.vehicle_controller.driver_presetup()

        # Initializes the scheduler and appends the driver to it
        self.event_schedular = scheduler.Scheduler(self) 
        self.event_schedular.append_event(0, ai=ai)



        #Send sync for blocking each step to ensure they're loaded in order
        self.dispatcher.send_sync(self.scenario.make, self.beamng)
        self.dispatcher.send_sync(self.beamng.scenario.load, self.scenario)
        self.dispatcher.send_sync(self.beamng.scenario.start)
        self.dispatcher.send_sync(self.beamng.control.pause)

        # Sets the initial focus to the driver vehicle
        self.vehicle_controller.camera_setup()
        
        # Setups conditions for the scenario
        self.random_weather_setup()
        self.random_tod_setup()
        self.convert_to_imperial()

        self.beamng.settings.set_deterministic(ceil(const.TICK_RATE*2))
        print("Scenario started.")
        
        # Gets the road network for the scenario for use in vehicle spawning
        self.vehicle_controller.get_road_network()

        # Spawns traffic and emergency vehicles
        self.simulation_traffic_setup() 

    def simulation_traffic_setup(self):
        # Traffic API is problematic spawning method, so I have to do this manually now
        n_amount = random.randint(const.MINIMUM_TRAFFIC_VEHICLES, const.MAXIMUM_TRAFFIC_VEHICLES)
        # Sets what vehicles can be controlled and given sound events within the maximum range
        control_count =  n_amount % (const.MAXIMUM_CONTROLLABLE_VEHICLES + 1)
        # Used to add delays between spawns to help out the Lua GE
        print("Number of traffic vehicles: " + str(n_amount) + ". Setting up traffic vehicles.")
        for i in range(n_amount):
            vehicle = self.vehicle_controller.vehicle_spawn(EV=False)
            sleep(0.25)
            try:
                self.dispatcher.send_sync(vehicle.connect, self.beamng, tries=10)  
                if control_count > 0:
                    self.event_schedular.append_event(1, vehicle)  
                    control_count -= 1  
                    print(f"Traffic vehicle {vehicle.vid} successfully spawned and connected")  
                else:  
                    vehicle.ai.set_mode("traffic")
                    print(f"Traffic vehicle {vehicle.vid} successfully spawned")   
            except Exception as e:  
                print(f"Traffic vehicle {vehicle.vid} failed to connect: {e}")
                self.dispatcher.send(self.beamng.vehicles.despawn, vehicle)
                continue

        # Spawns a random number of emergency vehicles based on the constants defined
        n_police_rand = random.randint(const.MINIMUM_EMERGENCY_VEHICLES, const.MAXIMUM_EMERGENCY_VEHICLES)
        control_count =  n_police_rand % (const.MAXIMUM_CONTROLLABLE_VEHICLES + 1)

        print("Number of emergency vehicles: " + str(n_police_rand) + ". Setting up emergency vehicles.")
        for i in range(n_police_rand):
            # Custom spawn for specifically emergency vehicles
            # Note: Finding a non-static spawning method for these emergency vehicles would be ideal
            vehicle = self.vehicle_controller.vehicle_spawn(EV=True)
            try:
                sleep(0.25)
                self.dispatcher.send_sync(vehicle.connect, self.beamng, tries=10)
                if control_count > 0:
                    self.event_schedular.append_event(3, vehicle)
                    control_count -= 1
                    print(f"Emergency vehicle {vehicle.vid} successfully spawned and connected")
                else:
                    vehicle.ai.set_mode("traffic") 
                    print(f"Emergency vehicle {vehicle.vid} successfully spawned") 
            except Exception as e:
                print(f"Emergency vehicle {vehicle.vid} failed to spawn or connect: {e}")
                self.dispatcher.send(self.beamng.vehicles.despawn, vehicle)
                continue

    # Stops all events, deletes the scenario, and despawns all vehicles if possible
    def scenario_cleanup(self):    
        if hasattr(self, 'event_schedular'):
            self.event_schedular.stop_all()
            self.event_schedular = None
        if hasattr(self, 'scenario'):
            self.dispatcher.send_sync(self.beamng.scenario.stop)
            sleep(1.0)
            self.dispatcher.send_sync(self.scenario.delete, self.beamng)
            self.scenario = None  

    # Closes the connection to BeamNG and stops the dispatcher thread that recieves the commands
    def close(self):
        self.dispatcher.send_sync(self.beamng.close)
        sleep(5)
        self.on = False
        self.dispatcher_thread.join(timeout=10.0)
        